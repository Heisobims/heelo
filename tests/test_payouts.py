"""Manual payouts (app/services/payout_service.py) - tracking and settling
money Heelo holds for organizers with no auto-split rail (no verified
Paystack/Flutterwave/Stripe account). Covers the owed-amount math (including
a partial refund), the admin create/mark-paid/mark-failed routes, and the
weekly digest task."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from httpx import AsyncClient

from app.services import payout_service as payout_svc


async def _make_order(
    db,
    published_event,
    *,
    net_amount: float,
    total_amount: float | None = None,
    refunded_amount: float = 0.0,
    auto_split_applied: bool = False,
    payment_status: str = "paid",
    buyer_email: str = "buyer@example.com",
):
    from app.models.ticketing import Order

    order = Order(
        event_id=published_event.id,
        buyer_name="Buyer",
        buyer_email=buyer_email,
        total_amount=total_amount if total_amount is not None else net_amount,
        net_amount=net_amount,
        platform_fee=0.0,
        refunded_amount=refunded_amount,
        currency="NGN",
        payment_provider="manual" if not auto_split_applied else "paystack",
        payment_status=payment_status,
        auto_split_applied=auto_split_applied,
    )
    db.add(order)
    await db.flush()
    return order


# ── get_owed_amount ──────────────────────────────────────────────────────────


async def test_owed_amount_counts_unsplit_paid_orders(db, org, published_event):
    await _make_order(db, published_event, net_amount=1000.0)
    owed = await payout_svc.get_owed_amount(db, org.id)
    assert owed == Decimal("1000.00")


async def test_owed_amount_excludes_auto_split_orders(db, org, published_event):
    """An order that was already paid out automatically (real Paystack/
    Flutterwave/Stripe split) must not also show as manually owed."""
    await _make_order(db, published_event, net_amount=1000.0, auto_split_applied=True)
    owed = await payout_svc.get_owed_amount(db, org.id)
    assert owed == Decimal("0.00")


async def test_owed_amount_reflects_partial_refund(db, org, published_event):
    """net_amount - refunded_amount is the exact formula used elsewhere for
    net revenue - confirmed correct against cancel_registration's refund
    logic (which increments both fields by the reversed fee)."""
    await _make_order(db, published_event, net_amount=1000.0, refunded_amount=400.0)
    owed = await payout_svc.get_owed_amount(db, org.id)
    assert owed == Decimal("600.00")


async def test_owed_amount_subtracts_paid_payouts(db, org, published_event):
    await _make_order(db, published_event, net_amount=1000.0)
    await payout_svc.create_payout(
        db,
        org.id,
        amount=Decimal("400.00"),
        currency="NGN",
        payment_account_id=None,
        initiated_by=None,
    )
    payout = await payout_svc.create_payout(
        db,
        org.id,
        amount=Decimal("400.00"),
        currency="NGN",
        payment_account_id=None,
        initiated_by=None,
    )
    # Only paid payouts reduce what's owed - a pending one doesn't yet.
    owed_before_paid = await payout_svc.get_owed_amount(db, org.id)
    assert owed_before_paid == Decimal("1000.00")

    await payout_svc.mark_payout_paid(db, payout, provider_reference="TXN123")
    owed_after_paid = await payout_svc.get_owed_amount(db, org.id)
    assert owed_after_paid == Decimal("600.00")


async def test_owed_amount_ignores_pending_orders(db, org, published_event):
    await _make_order(db, published_event, net_amount=1000.0, payment_status="pending")
    owed = await payout_svc.get_owed_amount(db, org.id)
    assert owed == Decimal("0.00")


# ── list_orgs_with_pending_payouts ──────────────────────────────────────────


async def test_list_orgs_with_pending_payouts_includes_owed_orgs(db, org, published_event):
    await _make_order(db, published_event, net_amount=1000.0)
    results = await payout_svc.list_orgs_with_pending_payouts(db)
    org_ids = [r["org"].id for r in results]
    assert org.id in org_ids
    match = next(r for r in results if r["org"].id == org.id)
    assert match["owed"] == Decimal("1000.00")


async def test_list_orgs_with_pending_payouts_excludes_fully_paid_orgs(db, org, published_event):
    await _make_order(db, published_event, net_amount=1000.0)
    payout = await payout_svc.create_payout(
        db,
        org.id,
        amount=Decimal("1000.00"),
        currency="NGN",
        payment_account_id=None,
        initiated_by=None,
    )
    await payout_svc.mark_payout_paid(db, payout, provider_reference="TXN999")
    results = await payout_svc.list_orgs_with_pending_payouts(db)
    assert all(r["org"].id != org.id for r in results)


# ── mark_payout_paid / mark_payout_failed ───────────────────────────────────


async def test_mark_payout_paid_sets_fields(db, org):
    payout = await payout_svc.create_payout(
        db,
        org.id,
        amount=Decimal("500.00"),
        currency="NGN",
        payment_account_id=None,
        initiated_by=None,
    )
    assert payout.status == "pending"
    updated = await payout_svc.mark_payout_paid(db, payout, provider_reference="REF-1")
    assert updated.status == "paid"
    assert updated.provider_reference == "REF-1"
    assert updated.paid_at is not None


async def test_mark_payout_paid_rejects_already_paid(db, org):
    import pytest
    from fastapi import HTTPException

    payout = await payout_svc.create_payout(
        db,
        org.id,
        amount=Decimal("500.00"),
        currency="NGN",
        payment_account_id=None,
        initiated_by=None,
    )
    await payout_svc.mark_payout_paid(db, payout, provider_reference="REF-1")
    with pytest.raises(HTTPException):
        await payout_svc.mark_payout_paid(db, payout, provider_reference="REF-2")


async def test_mark_payout_failed_sets_reason(db, org):
    payout = await payout_svc.create_payout(
        db,
        org.id,
        amount=Decimal("500.00"),
        currency="NGN",
        payment_account_id=None,
        initiated_by=None,
    )
    updated = await payout_svc.mark_payout_failed(db, payout, reason="Wrong account number")
    assert updated.status == "failed"
    assert updated.failure_reason == "Wrong account number"


# ── Admin routes ─────────────────────────────────────────────────────────────


async def test_admin_create_payout_route(client: AsyncClient, org, admin_headers):
    # This route just records a Payout row against org_id - it doesn't
    # validate against a live owed-amount figure, so no order fixture needed.
    resp = await client.post(
        f"/api/v1/admin/organizations/{org.id}/payouts",
        json={"amount": 500.0, "currency": "NGN"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "pending"
    assert data["amount"] == 500.0


async def test_admin_create_payout_requires_admin(client: AsyncClient, org, user_headers):
    resp = await client.post(
        f"/api/v1/admin/organizations/{org.id}/payouts",
        json={"amount": 500.0, "currency": "NGN"},
        headers=user_headers,
    )
    assert resp.status_code == 403


async def test_admin_mark_payout_paid_route(client: AsyncClient, db, org, admin_headers):
    payout = await payout_svc.create_payout(
        db,
        org.id,
        amount=Decimal("500.00"),
        currency="NGN",
        payment_account_id=None,
        initiated_by=None,
    )
    resp = await client.post(
        f"/api/v1/admin/payouts/{payout.id}/mark-paid",
        json={"provider_reference": "TXN-ADMIN-1"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "paid"


async def test_admin_mark_payout_failed_route(client: AsyncClient, db, org, admin_headers):
    payout = await payout_svc.create_payout(
        db,
        org.id,
        amount=Decimal("500.00"),
        currency="NGN",
        payment_account_id=None,
        initiated_by=None,
    )
    resp = await client.post(
        f"/api/v1/admin/payouts/{payout.id}/mark-failed",
        json={"reason": "Bad bank details"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "failed"


async def test_admin_mark_payout_paid_404_for_unknown_payout(client: AsyncClient, admin_headers):
    import uuid

    resp = await client.post(
        f"/api/v1/admin/payouts/{uuid.uuid4()}/mark-paid",
        json={"provider_reference": "TXN"},
        headers=admin_headers,
    )
    assert resp.status_code == 404


async def test_admin_disburse_payout_route_success(client: AsyncClient, db, org, admin_headers, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.models.payment import PaymentAccount
    from app.config import settings

    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "sk_test_123")

    acct = PaymentAccount(
        org_id=org.id,
        provider="manual",
        provider_account_id="manual-123",
        account_name="Org Owner",
        bank_name="GTBank",
        bank_code="058",
        account_number="0123456789",
        recipient_code="RCP_test123",
        currency="NGN",
        is_default=True,
    )
    db.add(acct)
    await db.commit()

    payout = await payout_svc.create_payout(
        db,
        org.id,
        amount=Decimal("1500.00"),
        currency="NGN",
        payment_account_id=acct.id,
        initiated_by=None,
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": True,
        "message": "Transfer queued",
        "data": {
            "status": "success",
            "transfer_code": "TRF_abc123",
            "amount": 150000,
        },
    }

    mock_client_inst = MagicMock()
    mock_client_inst.__aenter__.return_value = mock_client_inst
    mock_client_inst.__aexit__.return_value = None
    mock_client_inst.post = AsyncMock(return_value=mock_resp)

    with patch("app.services.payout_service.httpx.AsyncClient", return_value=mock_client_inst):
        resp = await client.post(
            f"/api/v1/admin/payouts/{payout.id}/disburse",
            headers=admin_headers,
        )

    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["data"]["status"] == "paid"
    assert resp.json()["data"]["provider_reference"] == "TRF_abc123"

    await db.refresh(payout)
    assert payout.status == "paid"
    assert payout.provider_reference == "TRF_abc123"


async def test_paystack_webhook_transfer_success_marks_payout_paid(client: AsyncClient, db, org, monkeypatch):
    from unittest.mock import patch
    import json
    from app.config import settings

    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "sk_test_123")

    payout = await payout_svc.create_payout(
        db,
        org.id,
        amount=Decimal("2000.00"),
        currency="NGN",
        payment_account_id=None,
        initiated_by=None,
    )

    webhook_payload = {
        "event": "transfer.success",
        "data": {
            "reference": f"payout_{payout.id}",
            "transfer_code": "TRF_hook_999",
            "amount": 200000,
            "status": "success",
        },
    }

    with patch("app.services.payment_service.verify_paystack_signature", return_value=True):
        resp = await client.post(
            "/api/v1/webhooks/paystack",
            content=json.dumps(webhook_payload),
            headers={"x-paystack-signature": "dummy_sig", "Content-Type": "application/json"},
        )

    assert resp.status_code == 200
    await db.refresh(payout)
    assert payout.status == "paid"
    assert payout.provider_reference == "TRF_hook_999"


async def test_paystack_webhook_transfer_failed_marks_payout_failed(client: AsyncClient, db, org, monkeypatch):
    from unittest.mock import patch
    import json
    from app.config import settings

    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "sk_test_123")

    payout = await payout_svc.create_payout(
        db,
        org.id,
        amount=Decimal("3000.00"),
        currency="NGN",
        payment_account_id=None,
        initiated_by=None,
    )

    webhook_payload = {
        "event": "transfer.failed",
        "data": {
            "reference": f"payout_{payout.id}",
            "reason": "Account number is invalid",
        },
    }

    with patch("app.services.payment_service.verify_paystack_signature", return_value=True):
        resp = await client.post(
            "/api/v1/webhooks/paystack",
            content=json.dumps(webhook_payload),
            headers={"x-paystack-signature": "dummy_sig", "Content-Type": "application/json"},
        )

    assert resp.status_code == 200
    await db.refresh(payout)
    assert payout.status == "failed"
    assert "Account number is invalid" in payout.failure_reason


# ── Admin page ───────────────────────────────────────────────────────────────


async def test_admin_payouts_page_renders(client: AsyncClient, db, org, published_event, user):
    await _make_order(db, published_event, net_amount=1000.0)
    user.role = "admin"
    await db.commit()

    login = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "password123"}
    )
    assert login.status_code == 200

    resp = await client.get("/admin/payouts")
    assert resp.status_code == 200
    assert org.name in resp.text


# ── Celery digest task ───────────────────────────────────────────────────────


def test_pending_payouts_digest_skips_when_ops_email_unset(monkeypatch):
    from app.config import settings
    from app.tasks import billing as billing_tasks

    monkeypatch.setattr(settings, "OPS_ALERT_EMAIL", "")
    with patch("app.services.email_service.send_sync") as mock_send:
        billing_tasks.send_pending_payouts_digest()
    mock_send.assert_not_called()
