"""Self-serve plan billing - checkout, confirm idempotency, upgrade vs
renewal expiry math, scheduled downgrade preserving access, webhook
dispatch routing, and the renewal/auto-downgrade Celery task."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.services import billing_service as billing_svc
from app.services import payment_service
from tests.conftest import TEST_DATABASE_URL

_SYNC_TEST_URL = TEST_DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")


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
    client.post = AsyncMock(return_value=response)
    client.get = AsyncMock(return_value=response)
    return client


async def _make_org(db, *, plan="free", plan_expires_at=None, pending_plan_change=None):
    from app.models.organization import Organization
    from app.models.user import User
    from app.utils.auth import hash_password

    owner = User(
        full_name="Billing Owner",
        email=f"billing-owner-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("password123"),
        role="organizer",
        is_verified=True,
    )
    db.add(owner)
    await db.flush()
    org = Organization(
        owner_id=owner.id,
        name="Billing Test Org",
        slug=f"billing-org-{uuid.uuid4().hex[:8]}",
        plan=plan,
        currency="NGN",
        plan_expires_at=plan_expires_at,
        pending_plan_change=pending_plan_change,
    )
    db.add(org)
    await db.flush()
    return owner, org


# ── start_plan_checkout ──────────────────────────────────────────────────────


async def test_start_plan_checkout_creates_pending_invoice(db, monkeypatch):
    from app.models.payment import PlanInvoice

    _, org = await _make_org(db, plan="free")
    monkeypatch.setattr(
        billing_svc.payment_service,
        "initialize_plan_payment",
        AsyncMock(return_value="https://pay.example/x"),
    )

    url = await billing_svc.start_plan_checkout(db, org, "growth")
    assert url == "https://pay.example/x"

    invoice = (await db.execute(select(PlanInvoice))).scalar()
    assert invoice.plan == "growth"
    assert invoice.status == "pending"
    # amount is grossed up to include an estimated gateway processing fee -
    # Heelo still nets the full list price, the buyer/org pays the rest.
    list_price = float(billing_svc.PLAN_PRICES["growth"])
    assert invoice.gateway_fee_amount > 0
    assert float(invoice.amount) == list_price + invoice.gateway_fee_amount
    assert float(invoice.amount) > list_price


async def test_start_plan_checkout_rejects_lower_tier(db):
    import pytest
    from fastapi import HTTPException

    _, org = await _make_org(db, plan="pro")
    with pytest.raises(HTTPException) as exc:
        await billing_svc.start_plan_checkout(db, org, "growth")
    assert exc.value.status_code == 400


async def test_start_plan_checkout_rejects_unknown_plan(db):
    import pytest
    from fastapi import HTTPException

    _, org = await _make_org(db, plan="free")
    with pytest.raises(HTTPException) as exc:
        await billing_svc.start_plan_checkout(db, org, "enterprise")
    assert exc.value.status_code == 400


async def test_start_plan_checkout_expires_prior_pending_invoice(db, monkeypatch):
    """An org that abandons a Growth checkout and starts a fresh Pro one
    must not leave the old Growth invoice payable - otherwise completing
    that stale link later could downgrade a paying org back to Growth."""
    from app.models.payment import PlanInvoice

    _, org = await _make_org(db, plan="free")
    monkeypatch.setattr(
        billing_svc.payment_service,
        "initialize_plan_payment",
        AsyncMock(return_value="https://pay.example/x"),
    )

    await billing_svc.start_plan_checkout(db, org, "growth")
    first_invoice = (await db.execute(select(PlanInvoice))).scalar()

    await billing_svc.start_plan_checkout(db, org, "pro")
    await db.refresh(first_invoice)

    assert first_invoice.status == "expired"


async def test_confirm_plan_invoice_rejects_stale_expired_invoice(db):
    """A stale, expired invoice must never be confirmable, even if payment
    completes at the provider after the org already moved to a new plan."""
    _, org = await _make_org(db, plan="pro", plan_expires_at=datetime.now(UTC) + timedelta(days=25))
    stale_invoice = await _make_invoice(db, org, plan="growth")
    stale_invoice.status = "expired"
    await db.flush()

    await billing_svc.confirm_plan_invoice(db, stale_invoice)
    await db.refresh(org)

    assert org.plan == "pro"
    assert stale_invoice.status == "expired"


# ── confirm_plan_invoice ─────────────────────────────────────────────────────


async def _make_invoice(db, org, *, plan, amount=15000.0):
    from app.models.payment import PlanInvoice

    invoice = PlanInvoice(
        org_id=org.id,
        plan=plan,
        amount=amount,
        currency="NGN",
        status="pending",
    )
    db.add(invoice)
    await db.flush()
    return invoice


async def test_confirm_plan_invoice_first_upgrade_sets_plan_and_expiry(db):
    _, org = await _make_org(db, plan="free")
    invoice = await _make_invoice(db, org, plan="growth")

    await billing_svc.confirm_plan_invoice(db, invoice)
    await db.refresh(org)

    assert org.plan == "growth"
    assert invoice.status == "paid"
    assert org.plan_expires_at is not None
    delta = org.plan_expires_at - datetime.now(UTC)
    assert timedelta(days=29) < delta < timedelta(days=31)


async def test_confirm_plan_invoice_renewal_extends_from_current_expiry(db):
    current_expiry = datetime.now(UTC) + timedelta(days=5)
    _, org = await _make_org(db, plan="growth", plan_expires_at=current_expiry)
    invoice = await _make_invoice(db, org, plan="growth")

    await billing_svc.confirm_plan_invoice(db, invoice)
    await db.refresh(org)

    assert org.plan == "growth"
    expected = current_expiry + timedelta(days=30)
    assert abs((org.plan_expires_at - expected).total_seconds()) < 5


async def test_confirm_plan_invoice_tier_change_starts_fresh_period(db):
    """Upgrading mid-cycle (e.g. Growth with 20 days left -> Pro) starts a
    fresh 30-day Pro period rather than prorating the remaining Growth days -
    the documented, simplest-correct behavior for this no-stored-card model."""
    current_expiry = datetime.now(UTC) + timedelta(days=20)
    _, org = await _make_org(db, plan="growth", plan_expires_at=current_expiry)
    invoice = await _make_invoice(db, org, plan="pro")

    await billing_svc.confirm_plan_invoice(db, invoice)
    await db.refresh(org)

    assert org.plan == "pro"
    delta = org.plan_expires_at - datetime.now(UTC)
    assert timedelta(days=29) < delta < timedelta(days=31)


async def test_confirm_plan_invoice_is_idempotent(db):
    _, org = await _make_org(db, plan="free")
    invoice = await _make_invoice(db, org, plan="growth")

    await billing_svc.confirm_plan_invoice(db, invoice)
    await db.refresh(org)
    first_expiry = org.plan_expires_at

    await billing_svc.confirm_plan_invoice(db, invoice)
    await db.refresh(org)

    assert org.plan_expires_at == first_expiry


async def test_confirm_plan_invoice_clears_pending_downgrade(db):
    _, org = await _make_org(
        db,
        plan="growth",
        plan_expires_at=datetime.now(UTC) + timedelta(days=2),
        pending_plan_change="free",
    )
    invoice = await _make_invoice(db, org, plan="growth")

    await billing_svc.confirm_plan_invoice(db, invoice)
    await db.refresh(org)

    assert org.pending_plan_change is None


# ── schedule_downgrade / cancel_scheduled_downgrade ─────────────────────────


async def test_schedule_downgrade_preserves_access_until_expiry(db):
    expiry = datetime.now(UTC) + timedelta(days=10)
    _, org = await _make_org(db, plan="growth", plan_expires_at=expiry)

    await billing_svc.schedule_downgrade(db, org)
    await db.refresh(org)

    assert org.plan == "growth"  # unchanged - still has paid access
    assert org.pending_plan_change == "free"


async def test_schedule_downgrade_immediate_when_no_expiry(db):
    _, org = await _make_org(db, plan="growth", plan_expires_at=None)

    await billing_svc.schedule_downgrade(db, org)
    await db.refresh(org)

    assert org.plan == "free"


async def test_cancel_scheduled_downgrade(db):
    expiry = datetime.now(UTC) + timedelta(days=10)
    _, org = await _make_org(db, plan="growth", plan_expires_at=expiry, pending_plan_change="free")

    await billing_svc.cancel_scheduled_downgrade(db, org)
    await db.refresh(org)

    assert org.pending_plan_change is None


async def test_list_invoices_newest_first(db):
    # created_at uses server_default=func.now(), which is frozen for the
    # whole transaction in Postgres - set explicit timestamps so ordering
    # isn't a same-transaction tie.
    _, org = await _make_org(db, plan="free")
    inv1 = await _make_invoice(db, org, plan="growth")
    inv1.created_at = datetime.now(UTC) - timedelta(minutes=5)
    inv2 = await _make_invoice(db, org, plan="pro")
    inv2.created_at = datetime.now(UTC)
    await db.flush()

    invoices = await billing_svc.list_invoices(db, org.id)
    assert [i.id for i in invoices][:2] == [inv2.id, inv1.id]


# ── Webhook dispatch (plan invoice vs ticket order) ─────────────────────────


async def test_paystack_webhook_confirms_plan_invoice(client: AsyncClient, db, monkeypatch):
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "test-secret")
    _, org = await _make_org(db, plan="free")
    invoice = await _make_invoice(db, org, plan="growth")
    reference = f"heelo_plan_{invoice.id}"

    fake_client = _fake_async_client(
        _fake_httpx_get_response(
            {
                "status": True,
                "data": {
                    "status": "success",
                    "reference": reference,
                    "amount": int(float(invoice.amount) * 100),
                    "currency": invoice.currency,
                },
            }
        )
    )
    monkeypatch.setattr(payment_service.httpx, "AsyncClient", lambda: fake_client)

    body = json.dumps({"event": "charge.success", "data": {"reference": reference}}).encode()
    resp = await client.post(
        "/api/v1/webhooks/paystack",
        content=body,
        headers={"content-type": "application/json", "x-paystack-signature": _paystack_sig(body)},
    )
    assert resp.status_code == 200

    await db.refresh(org)
    assert org.plan == "growth"


async def test_paystack_webhook_rejects_plan_invoice_amount_mismatch(
    client: AsyncClient, db, monkeypatch
):
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "test-secret")
    _, org = await _make_org(db, plan="free")
    invoice = await _make_invoice(db, org, plan="growth")
    reference = f"heelo_plan_{invoice.id}"

    fake_client = _fake_async_client(
        _fake_httpx_get_response(
            {
                "status": True,
                "data": {
                    "status": "success",
                    "reference": reference,
                    "amount": 100,  # far below the real invoice amount
                    "currency": invoice.currency,
                },
            }
        )
    )
    monkeypatch.setattr(payment_service.httpx, "AsyncClient", lambda: fake_client)

    body = json.dumps({"event": "charge.success", "data": {"reference": reference}}).encode()
    resp = await client.post(
        "/api/v1/webhooks/paystack",
        content=body,
        headers={"content-type": "application/json", "x-paystack-signature": _paystack_sig(body)},
    )
    assert resp.status_code == 200  # webhook always 200s; confirmation just doesn't happen

    await db.refresh(org)
    assert org.plan == "free"


# ── Celery task: reminders + auto-downgrade ─────────────────────────────────


def _patch_sync_db(monkeypatch, billing_tasks):
    sync_engine = create_engine(_SYNC_TEST_URL)
    TestSyncSession = sessionmaker(bind=sync_engine)
    monkeypatch.setattr(billing_tasks, "_db", lambda: TestSyncSession())
    return sync_engine


async def test_process_plan_renewals_sends_reminder_for_expiring_org(db, monkeypatch):
    from app.tasks import billing as billing_tasks

    _patch_sync_db(monkeypatch, billing_tasks)
    _, org = await _make_org(
        db, plan="growth", plan_expires_at=datetime.now(UTC) + timedelta(days=2)
    )
    await db.commit()

    billing_tasks.process_plan_renewals()

    await db.refresh(org)
    assert org.plan_reminder_sent_at is not None
    assert org.plan == "growth"  # not yet lapsed, untouched


async def test_process_plan_renewals_does_not_remind_twice_in_same_window(db, monkeypatch):
    from app.tasks import billing as billing_tasks

    _patch_sync_db(monkeypatch, billing_tasks)
    already_sent = datetime.now(UTC) - timedelta(hours=1)
    _, org = await _make_org(
        db, plan="growth", plan_expires_at=datetime.now(UTC) + timedelta(days=2)
    )
    org.plan_reminder_sent_at = already_sent
    await db.commit()

    billing_tasks.process_plan_renewals()

    await db.refresh(org)
    assert org.plan_reminder_sent_at == already_sent  # unchanged - not re-sent


async def test_process_plan_renewals_downgrades_lapsed_org(db, monkeypatch):
    from app.tasks import billing as billing_tasks

    _patch_sync_db(monkeypatch, billing_tasks)
    _, org = await _make_org(
        db, plan="growth", plan_expires_at=datetime.now(UTC) - timedelta(days=1)
    )
    await db.commit()

    billing_tasks.process_plan_renewals()

    await db.refresh(org)
    assert org.plan == "free"
    assert org.plan_expires_at is None


async def test_process_plan_renewals_ignores_orgs_with_no_expiry(db, monkeypatch):
    from app.tasks import billing as billing_tasks

    _patch_sync_db(monkeypatch, billing_tasks)
    _, org = await _make_org(db, plan="enterprise", plan_expires_at=None)
    await db.commit()

    billing_tasks.process_plan_renewals()

    await db.refresh(org)
    assert org.plan == "enterprise"


def test_get_plan_price_multicurrency():
    from decimal import Decimal
    from app.services.billing_service import get_plan_price

    assert get_plan_price("growth", "NGN") == Decimal("7500")
    assert get_plan_price("pro", "NGN") == Decimal("25000")
    assert get_plan_price("growth", "USD") == Decimal("19")
    assert get_plan_price("pro", "USD") == Decimal("49")
    assert get_plan_price("growth", "GBP") == Decimal("15")
    assert get_plan_price("pro", "EUR") == Decimal("45")
    assert get_plan_price("growth", "CAD") == Decimal("25")
