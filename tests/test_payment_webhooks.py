"""Payment webhooks (Paystack/Flutterwave) - signature verification, order
confirmation, and idempotent replay handling end-to-end through the router."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient

from app.config import settings
from app.services import payment_service


def _paystack_sig(body: bytes) -> str:
    return hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), body, hashlib.sha512).hexdigest()


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
        payment_provider="paystack",
        payment_reference=f"heelo_{order_id}",
        payment_status="pending",
    )
    db.add(o)
    await db.flush()
    return o


async def _pending_registration(db, published_event, ticket_type, order):
    from app.models.ticketing import Registration

    reg = Registration(
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        order_id=order.id,
        attendee_name="Jane Doe",
        attendee_email="jane@example.com",
        qr_code=f"qr-{uuid.uuid4()}",
        status="pending",
        referral_token=f"ref-{uuid.uuid4().hex[:12]}",
    )
    db.add(reg)
    await db.flush()
    return reg


async def test_paystack_webhook_rejects_invalid_signature(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "test-secret")
    body = json.dumps({"event": "charge.success", "data": {"reference": "heelo_x"}}).encode()
    resp = await client.post(
        "/api/v1/webhooks/paystack",
        content=body,
        headers={"content-type": "application/json", "x-paystack-signature": "not-valid"},
    )
    assert resp.status_code == 400


async def test_paystack_webhook_confirms_pending_order(
    client: AsyncClient, db, published_event, ticket_type, monkeypatch
):
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "test-secret")
    order = await _pending_order(db, published_event, ticket_type)
    reg = await _pending_registration(db, published_event, ticket_type, order)

    fake_client = _fake_async_client(
        _fake_httpx_get_response(
            {
                "status": True,
                "data": {
                    "status": "success",
                    "reference": order.payment_reference,
                    "amount": int(order.total_amount * 100),
                    "currency": order.currency,
                },
            }
        )
    )
    monkeypatch.setattr(payment_service.httpx, "AsyncClient", lambda: fake_client)

    body = json.dumps(
        {"event": "charge.success", "data": {"reference": order.payment_reference}}
    ).encode()
    resp = await client.post(
        "/api/v1/webhooks/paystack",
        content=body,
        headers={
            "content-type": "application/json",
            "x-paystack-signature": _paystack_sig(body),
        },
    )
    assert resp.status_code == 200

    await db.refresh(order)
    await db.refresh(reg)
    assert order.payment_status == "paid"
    assert reg.status == "confirmed"


async def test_paystack_webhook_replay_is_idempotent(
    client: AsyncClient, db, published_event, ticket_type, monkeypatch
):
    """Regression test for the Phase 2c confirm_order race fix: a webhook
    replayed after the order is already paid must not re-run ticket-count
    increments or registration confirmation a second time."""
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "test-secret")
    order = await _pending_order(db, published_event, ticket_type)
    await _pending_registration(db, published_event, ticket_type, order)

    fake_client = _fake_async_client(
        _fake_httpx_get_response(
            {
                "status": True,
                "data": {
                    "status": "success",
                    "reference": order.payment_reference,
                    "amount": int(order.total_amount * 100),
                    "currency": order.currency,
                },
            }
        )
    )
    monkeypatch.setattr(payment_service.httpx, "AsyncClient", lambda: fake_client)

    body = json.dumps(
        {"event": "charge.success", "data": {"reference": order.payment_reference}}
    ).encode()
    headers = {
        "content-type": "application/json",
        "x-paystack-signature": _paystack_sig(body),
    }

    resp1 = await client.post("/api/v1/webhooks/paystack", content=body, headers=headers)
    resp2 = await client.post("/api/v1/webhooks/paystack", content=body, headers=headers)
    assert resp1.status_code == 200
    assert resp2.status_code == 200

    from sqlalchemy import select

    from app.models.ticketing import TicketType

    await db.refresh(order)
    tt = await db.scalar(select(TicketType).where(TicketType.id == ticket_type.id))
    assert order.payment_status == "paid"
    assert tt.quantity_sold == 1  # not double-incremented by the replayed webhook


async def test_flutterwave_webhook_rejects_invalid_signature(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "FLUTTERWAVE_WEBHOOK_SECRET", "test-secret")
    body = json.dumps({"status": "successful", "data": {"id": 1, "tx_ref": "heelo_x"}}).encode()
    resp = await client.post(
        "/api/v1/webhooks/flutterwave",
        content=body,
        headers={"content-type": "application/json", "verif-hash": "wrong"},
    )
    assert resp.status_code == 400


async def test_flutterwave_webhook_confirms_pending_order(
    client: AsyncClient, db, published_event, ticket_type, monkeypatch
):
    monkeypatch.setattr(settings, "FLUTTERWAVE_WEBHOOK_SECRET", "test-secret")
    order_id = uuid.uuid4()
    order = await _pending_order(db, published_event, ticket_type, order_id=order_id)
    reg = await _pending_registration(db, published_event, ticket_type, order)

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

    body = json.dumps(
        {"status": "successful", "data": {"id": 99887766, "tx_ref": order.payment_reference}}
    ).encode()
    resp = await client.post(
        "/api/v1/webhooks/flutterwave",
        content=body,
        headers={"content-type": "application/json", "verif-hash": "test-secret"},
    )
    assert resp.status_code == 200

    await db.refresh(order)
    await db.refresh(reg)
    assert order.payment_status == "paid"
    assert reg.status == "confirmed"
