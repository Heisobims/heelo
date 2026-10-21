"""Browser-redirect payment callbacks (app/routers/pages.py) - previously
untested. Covers the Flutterwave callback's narrowed exception handling and
its order-context-preserving fallback redirect (instead of a bare homepage
redirect on failure)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient

from app.config import settings
from app.services import payment_service


def _fake_httpx_get_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


def _fake_async_client(response: MagicMock) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=response)
    return client


async def _pending_order(db, published_event, ticket_type, order_id=None):
    from app.models.ticketing import Order

    order_id = order_id or uuid.uuid4()
    fee_rate = float(payment_service.PLATFORM_FEE_PERCENT)
    o = Order(
        id=order_id,
        event_id=published_event.id,
        buyer_name="Jane Doe",
        buyer_email="jane@example.com",
        total_amount=float(ticket_type.price),
        net_amount=float(ticket_type.price) * (1 - fee_rate),
        platform_fee=float(ticket_type.price) * fee_rate,
        currency=ticket_type.currency,
        payment_provider="flutterwave",
        payment_reference=f"heelo_{order_id}",
        payment_status="pending",
    )
    db.add(o)
    await db.flush()
    return o


async def test_flutterwave_callback_success_redirects_to_confirmation(
    client: AsyncClient, db, published_event, ticket_type, monkeypatch
):
    monkeypatch.setattr(settings, "FLUTTERWAVE_SECRET_KEY", "test-secret")
    order = await _pending_order(db, published_event, ticket_type)

    fake_client = _fake_async_client(
        _fake_httpx_get_response(
            {
                "status": "success",
                "data": {
                    "status": "successful",
                    "tx_ref": order.payment_reference,
                    "amount": float(order.total_amount),
                    "currency": order.currency,
                },
            }
        )
    )
    monkeypatch.setattr(payment_service.httpx, "AsyncClient", lambda: fake_client)

    resp = await client.get(
        "/payments/flutterwave/callback",
        params={"status": "successful", "tx_ref": order.payment_reference, "transaction_id": "123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == f"/orders/{order.id}/confirmation"


async def test_flutterwave_callback_bad_transaction_id_preserves_order_context(
    client: AsyncClient, db, published_event, ticket_type
):
    """A non-numeric transaction_id must not 500 - and the redirect should
    still point back at the buyer's own order (recovered from tx_ref), not a
    bare homepage redirect that loses all context."""
    order = await _pending_order(db, published_event, ticket_type)

    resp = await client.get(
        "/payments/flutterwave/callback",
        params={
            "status": "successful",
            "tx_ref": order.payment_reference,
            "transaction_id": "not-a-number",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == f"/orders/{order.id}/confirmation?pending=1&error=1"


async def test_flutterwave_callback_verify_exception_preserves_order_context(
    client: AsyncClient, db, published_event, ticket_type, monkeypatch
):
    """A network/provider error during verification is caught narrowly (not
    conflated with a bad transaction_id) and still redirects with context."""
    monkeypatch.setattr(settings, "FLUTTERWAVE_SECRET_KEY", "test-secret")
    order = await _pending_order(db, published_event, ticket_type)

    async def _boom(*args, **kwargs):
        raise RuntimeError("provider unreachable")

    monkeypatch.setattr(payment_service, "verify_flutterwave", _boom)

    resp = await client.get(
        "/payments/flutterwave/callback",
        params={"status": "successful", "tx_ref": order.payment_reference, "transaction_id": "123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == f"/orders/{order.id}/confirmation?pending=1&error=1"


async def test_flutterwave_callback_unrecognized_reference_falls_back_to_home(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "FLUTTERWAVE_SECRET_KEY", "test-secret")
    fake_client = _fake_async_client(
        _fake_httpx_get_response({"status": "success", "data": {"status": "successful"}})
    )
    monkeypatch.setattr(payment_service.httpx, "AsyncClient", lambda: fake_client)

    resp = await client.get(
        "/payments/flutterwave/callback",
        params={"status": "successful", "tx_ref": "not-a-heelo-ref", "transaction_id": "123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/?error=payment_failed"
