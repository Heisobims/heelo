"""Tests for app.services.payment_service refund functions.

These exercise refund_order_item() and its per-provider helpers directly
against an in-memory Order (no DB round-trip needed - the functions only
read attributes off the object and call out to the provider API).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.ticketing import Order
from app.services import payment_service


def _make_order(*, provider: str | None, reference: str | None = "ref-123") -> Order:
    return Order(
        id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        buyer_email="buyer@example.com",
        total_amount=5000.0,
        net_amount=4850.0,
        platform_fee=150.0,
        currency="NGN",
        payment_provider=provider,
        payment_reference=reference,
        payment_status="paid",
    )


def _fake_httpx_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


def _fake_async_client(response: MagicMock) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=response)
    return client


class TestRefundOrderItemDispatch:
    async def test_free_order_short_circuits_true(self):
        order = _make_order(provider="free", reference=None)
        assert await payment_service.refund_order_item(order, Decimal("10")) is True

    async def test_no_provider_short_circuits_true(self):
        order = _make_order(provider=None, reference=None)
        assert await payment_service.refund_order_item(order, Decimal("10")) is True

    async def test_unknown_provider_returns_false(self):
        order = _make_order(provider="applepay")
        assert await payment_service.refund_order_item(order, Decimal("10")) is False

    async def test_provider_exception_is_caught_and_returns_false(self):
        order = _make_order(provider="paystack")
        with patch.object(
            payment_service, "_refund_paystack", AsyncMock(side_effect=RuntimeError("boom"))
        ):
            assert await payment_service.refund_order_item(order, Decimal("10")) is False


class TestRefundPaystack:
    async def test_success(self):
        order = _make_order(provider="paystack")
        client = _fake_async_client(_fake_httpx_response({"status": True}))
        with patch("httpx.AsyncClient", return_value=client):
            assert await payment_service._refund_paystack(order, Decimal("50")) is True

    async def test_failure_status_false(self):
        order = _make_order(provider="paystack")
        client = _fake_async_client(_fake_httpx_response({"status": False, "message": "nope"}))
        with patch("httpx.AsyncClient", return_value=client):
            assert await payment_service._refund_paystack(order, Decimal("50")) is False

    async def test_no_reference_returns_false_without_calling_api(self):
        order = _make_order(provider="paystack", reference=None)
        with patch("httpx.AsyncClient") as mock_client_cls:
            assert await payment_service._refund_paystack(order, Decimal("50")) is False
            mock_client_cls.assert_not_called()

    async def test_amount_converted_to_kobo_with_minimum(self):
        order = _make_order(provider="paystack")
        client = _fake_async_client(_fake_httpx_response({"status": True}))
        with patch("httpx.AsyncClient", return_value=client):
            await payment_service._refund_paystack(order, Decimal("0.5"))
        _, kwargs = client.post.call_args
        assert kwargs["json"]["amount"] == 100  # floor of 50 kobo, clamped to the 100 minimum


class TestRefundFlutterwave:
    async def test_success(self):
        order = _make_order(provider="flutterwave")
        client = _fake_async_client(_fake_httpx_response({"status": "success"}))
        with patch("httpx.AsyncClient", return_value=client):
            assert await payment_service._refund_flutterwave(order, Decimal("50")) is True

    async def test_failure(self):
        order = _make_order(provider="flutterwave")
        client = _fake_async_client(_fake_httpx_response({"status": "error"}))
        with patch("httpx.AsyncClient", return_value=client):
            assert await payment_service._refund_flutterwave(order, Decimal("50")) is False

    async def test_no_reference_returns_false(self):
        order = _make_order(provider="flutterwave", reference=None)
        assert await payment_service._refund_flutterwave(order, Decimal("50")) is False


class TestRefundStripe:
    async def test_success_with_payment_intent_reference(self):
        order = _make_order(provider="stripe", reference="pi_123")
        fake_refund = MagicMock(status="succeeded")
        with patch("stripe.Refund.create", return_value=fake_refund) as mock_create:
            assert await payment_service._refund_stripe(order, Decimal("50")) is True
        assert mock_create.call_args.kwargs["payment_intent"] == "pi_123"
        assert mock_create.call_args.kwargs["amount"] == 5000

    async def test_pending_status_counts_as_success(self):
        order = _make_order(provider="stripe", reference="pi_123")
        fake_refund = MagicMock(status="pending")
        with patch("stripe.Refund.create", return_value=fake_refund):
            assert await payment_service._refund_stripe(order, Decimal("50")) is True

    async def test_failed_status_returns_false(self):
        order = _make_order(provider="stripe", reference="pi_123")
        fake_refund = MagicMock(status="failed")
        with patch("stripe.Refund.create", return_value=fake_refund):
            assert await payment_service._refund_stripe(order, Decimal("50")) is False

    async def test_no_reference_returns_false(self):
        order = _make_order(provider="stripe", reference=None)
        assert await payment_service._refund_stripe(order, Decimal("50")) is False

    async def test_checkout_session_reference_resolved_to_payment_intent(self):
        order = _make_order(provider="stripe", reference="cs_test_abc")
        fake_session = MagicMock(payment_intent="pi_resolved")
        fake_refund = MagicMock(status="succeeded")
        with (
            patch("stripe.checkout.Session.retrieve", return_value=fake_session),
            patch("stripe.Refund.create", return_value=fake_refund) as mock_create,
        ):
            assert await payment_service._refund_stripe(order, Decimal("50")) is True
        assert mock_create.call_args.kwargs["payment_intent"] == "pi_resolved"

    async def test_checkout_session_without_payment_intent_returns_false(self):
        order = _make_order(provider="stripe", reference="cs_test_abc")
        fake_session = MagicMock(payment_intent=None)
        with patch("stripe.checkout.Session.retrieve", return_value=fake_session):
            assert await payment_service._refund_stripe(order, Decimal("50")) is False
