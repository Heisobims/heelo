"""WhatsApp Celery task bodies - send_registration_confirmation and
send_registration_cancellation. Previously only the pure formatting helpers
(location_label, date_label, structured reply keywords) had coverage; these
exercise the DB-touching task bodies themselves: consent gating, payment
status gating, dedup-relevant state writes, and error handling."""

from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import whatsapp_service as wa
from tests.conftest import TEST_DATABASE_URL

_SYNC_TEST_URL = TEST_DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")


def _patch_sync_db(monkeypatch, wa_tasks):
    sync_engine = create_engine(_SYNC_TEST_URL)
    TestSyncSession = sessionmaker(bind=sync_engine)
    monkeypatch.setattr(wa_tasks, "_db", lambda: TestSyncSession())
    return sync_engine


async def _paid_order_with_registration(
    db, published_event, ticket_type, *, whatsapp_consent=True, reg_status="confirmed"
):
    from app.models.ticketing import Order, Registration
    from app.services import payment_service as pay_svc

    fee_rate = float(pay_svc.PLATFORM_FEE_PERCENT)
    order = Order(
        event_id=published_event.id,
        buyer_name="Jane Doe",
        buyer_email="jane@example.com",
        buyer_phone="+2348012345678",
        whatsapp_consent=whatsapp_consent,
        total_amount=float(ticket_type.price),
        net_amount=float(ticket_type.price) * (1 - fee_rate),
        platform_fee=float(ticket_type.price) * fee_rate,
        currency=ticket_type.currency,
        payment_provider="paystack",
        payment_reference=f"ref-{uuid.uuid4()}",
        payment_status="paid",
    )
    db.add(order)
    await db.flush()

    reg = Registration(
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        order_id=order.id,
        attendee_name="Jane Doe",
        attendee_email="jane@example.com",
        attendee_phone="+2348012345678",
        whatsapp_consent=whatsapp_consent,
        qr_code=f"qr-{uuid.uuid4()}",
        status=reg_status,
        referral_token=f"ref-{uuid.uuid4().hex[:12]}",
    )
    db.add(reg)
    await db.commit()
    await db.refresh(order)
    await db.refresh(reg)
    return order, reg


# ── send_registration_confirmation ──────────────────────────────────────────────


async def test_send_registration_confirmation_sends_and_marks_sent_at(
    db, published_event, ticket_type, monkeypatch
):
    from app.tasks import whatsapp as wa_tasks

    engine = _patch_sync_db(monkeypatch, wa_tasks)
    order, reg = await _paid_order_with_registration(db, published_event, ticket_type)

    sent = {}
    monkeypatch.setattr(wa, "send_registration_confirmation_sync", lambda **kw: sent.update(kw))

    wa_tasks.send_registration_confirmation(str(order.id))

    assert sent["phone"] == "+2348012345678"
    await db.refresh(reg)
    assert reg.whatsapp_sent_at is not None
    engine.dispose()


async def test_send_registration_confirmation_skips_without_consent(
    db, published_event, ticket_type, monkeypatch
):
    from app.tasks import whatsapp as wa_tasks

    engine = _patch_sync_db(monkeypatch, wa_tasks)
    order, reg = await _paid_order_with_registration(
        db, published_event, ticket_type, whatsapp_consent=False
    )

    called = {"n": 0}
    monkeypatch.setattr(
        wa, "send_registration_confirmation_sync", lambda **kw: called.__setitem__("n", 1)
    )

    wa_tasks.send_registration_confirmation(str(order.id))

    assert called["n"] == 0
    await db.refresh(reg)
    assert reg.whatsapp_sent_at is None
    engine.dispose()


async def test_send_registration_confirmation_skips_unpaid_order(
    db, published_event, ticket_type, monkeypatch
):
    from app.tasks import whatsapp as wa_tasks

    engine = _patch_sync_db(monkeypatch, wa_tasks)
    order, reg = await _paid_order_with_registration(db, published_event, ticket_type)
    order.payment_status = "pending"
    await db.commit()

    called = {"n": 0}
    monkeypatch.setattr(
        wa, "send_registration_confirmation_sync", lambda **kw: called.__setitem__("n", 1)
    )

    wa_tasks.send_registration_confirmation(str(order.id))

    assert called["n"] == 0
    engine.dispose()


async def test_send_registration_confirmation_skips_when_no_confirmed_registrations(
    db, published_event, ticket_type, monkeypatch
):
    from app.tasks import whatsapp as wa_tasks

    engine = _patch_sync_db(monkeypatch, wa_tasks)
    order, reg = await _paid_order_with_registration(
        db, published_event, ticket_type, reg_status="cancelled"
    )

    called = {"n": 0}
    monkeypatch.setattr(
        wa, "send_registration_confirmation_sync", lambda **kw: called.__setitem__("n", 1)
    )

    wa_tasks.send_registration_confirmation(str(order.id))

    assert called["n"] == 0
    engine.dispose()


async def test_send_registration_confirmation_handles_send_failure_gracefully(
    db, published_event, ticket_type, monkeypatch
):
    """A WhatsApp API failure must not crash the task or corrupt state -
    whatsapp_sent_at should stay unset so the state accurately reflects that
    nothing was actually delivered."""
    from app.tasks import whatsapp as wa_tasks

    engine = _patch_sync_db(monkeypatch, wa_tasks)
    order, reg = await _paid_order_with_registration(db, published_event, ticket_type)

    def _boom(**kw):
        raise RuntimeError("WhatsApp API is down")

    monkeypatch.setattr(wa, "send_registration_confirmation_sync", _boom)

    wa_tasks.send_registration_confirmation(str(order.id))  # must not raise

    await db.refresh(reg)
    assert reg.whatsapp_sent_at is None
    engine.dispose()


async def test_send_registration_confirmation_noop_for_missing_order(monkeypatch):
    from app.tasks import whatsapp as wa_tasks

    engine = _patch_sync_db(monkeypatch, wa_tasks)
    wa_tasks.send_registration_confirmation(str(uuid.uuid4()))  # must not raise
    engine.dispose()


# ── send_registration_cancellation ──────────────────────────────────────────────


async def test_send_registration_cancellation_sends_when_consented(
    db, published_event, ticket_type, monkeypatch
):
    from app.tasks import whatsapp as wa_tasks

    engine = _patch_sync_db(monkeypatch, wa_tasks)
    order, reg = await _paid_order_with_registration(db, published_event, ticket_type)
    reg.status = "cancelled"
    await db.commit()

    sent = {}
    monkeypatch.setattr(wa, "send_registration_cancellation_sync", lambda **kw: sent.update(kw))

    wa_tasks.send_registration_cancellation(str(reg.id))

    assert sent["phone"] == "+2348012345678"
    assert sent["refunded"] is False
    engine.dispose()


async def test_send_registration_cancellation_skips_without_consent(
    db, published_event, ticket_type, monkeypatch
):
    from app.tasks import whatsapp as wa_tasks

    engine = _patch_sync_db(monkeypatch, wa_tasks)
    order, reg = await _paid_order_with_registration(
        db, published_event, ticket_type, whatsapp_consent=False
    )

    called = {"n": 0}
    monkeypatch.setattr(
        wa, "send_registration_cancellation_sync", lambda **kw: called.__setitem__("n", 1)
    )

    wa_tasks.send_registration_cancellation(str(reg.id))

    assert called["n"] == 0
    engine.dispose()


async def test_send_registration_cancellation_noop_for_missing_registration(monkeypatch):
    from app.tasks import whatsapp as wa_tasks

    engine = _patch_sync_db(monkeypatch, wa_tasks)
    wa_tasks.send_registration_cancellation(str(uuid.uuid4()))  # must not raise
    engine.dispose()
