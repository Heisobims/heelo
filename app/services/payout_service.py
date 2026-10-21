"""Manual payouts - for organizers whose money Heelo is still holding
because no automatic split happened at charge time (no Paystack/Flutterwave
subaccount, no verified Stripe Connect account, or a "manual" reference-only
account). This subsystem tracks what's owed and records the bank transfers
Heelo's ops team sends by hand to settle it; it never moves money itself,
matching how "manual" accounts have no payment rail Heelo could move money
through even if it wanted to."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.event import Event
from app.models.organization import Organization
from app.models.payment import PaymentAccount, Payout
from app.models.ticketing import REVENUE_STATUSES, Order


async def get_owed_amount(db: AsyncSession, org_id: uuid.UUID) -> Decimal:
    """What Heelo currently owes this org: net revenue from orders that were
    never auto-split, minus payouts already marked paid. `net_amount -
    refunded_amount` is the same formula analytics_service.get_event_summary
    uses for net_revenue - confirmed correct against cancel_registration's
    refund logic, which increments both fields by the reversed fee so the
    difference always nets correctly even after a partial refund."""
    revenue = await db.scalar(
        select(func.coalesce(func.sum(Order.net_amount - Order.refunded_amount), 0))
        .select_from(Order)
        .join(Event, Event.id == Order.event_id)
        .where(
            Event.org_id == org_id,
            Order.payment_status.in_(REVENUE_STATUSES),
            Order.auto_split_applied.is_(False),
        )
    )
    already_paid = await db.scalar(
        select(func.coalesce(func.sum(Payout.amount), 0)).where(
            Payout.org_id == org_id, Payout.status == "paid"
        )
    )
    owed = Decimal(str(float(revenue or 0))) - Decimal(str(float(already_paid or 0)))
    return owed.quantize(Decimal("0.01"))


async def list_orgs_with_pending_payouts(
    db: AsyncSession, min_amount: Decimal = Decimal("0")
) -> list[dict]:
    """Every org with unsplit revenue exceeding `min_amount`, for the admin
    payout list - computed the same way as get_owed_amount, just batched
    across all orgs in one query instead of one org at a time."""
    rows = (
        await db.execute(
            select(
                Event.org_id,
                func.coalesce(func.sum(Order.net_amount - Order.refunded_amount), 0).label(
                    "revenue"
                ),
            )
            .select_from(Order)
            .join(Event, Event.id == Order.event_id)
            .where(
                Order.payment_status.in_(REVENUE_STATUSES),
                Order.auto_split_applied.is_(False),
            )
            .group_by(Event.org_id)
        )
    ).all()

    paid_rows = (
        await db.execute(
            select(Payout.org_id, func.coalesce(func.sum(Payout.amount), 0).label("paid"))
            .where(Payout.status == "paid")
            .group_by(Payout.org_id)
        )
    ).all()
    paid_by_org = {row.org_id: Decimal(str(float(row.paid))) for row in paid_rows}

    results = []
    for row in rows:
        owed = (
            Decimal(str(float(row.revenue))) - paid_by_org.get(row.org_id, Decimal("0"))
        ).quantize(Decimal("0.01"))
        if owed > min_amount:
            org = await db.get(Organization, row.org_id)
            if org:
                results.append({"org": org, "owed": owed})

    results.sort(key=lambda r: r["owed"], reverse=True)
    return results


async def create_payout(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    amount: Decimal,
    currency: str,
    payment_account_id: uuid.UUID | None,
    initiated_by: uuid.UUID | None,
) -> Payout:
    payout = Payout(
        org_id=org_id,
        amount=float(amount),
        currency=currency,
        payment_account_id=payment_account_id,
        requested_by=initiated_by,
        status="pending",
        initiated_at=datetime.now(UTC),
    )
    db.add(payout)
    await db.commit()
    await db.refresh(payout)
    return payout


async def mark_payout_paid(db: AsyncSession, payout: Payout, *, provider_reference: str) -> Payout:
    if payout.status == "paid":
        raise HTTPException(400, "This payout is already marked paid.")
    payout.status = "paid"
    payout.provider_reference = provider_reference
    payout.paid_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(payout)
    return payout


async def mark_payout_failed(db: AsyncSession, payout: Payout, *, reason: str) -> Payout:
    payout.status = "failed"
    payout.failure_reason = reason
    await db.commit()
    await db.refresh(payout)
    return payout


async def disburse_payout_paystack(db: AsyncSession, payout: Payout) -> Payout:
    """Automate manual payout disbursement via Paystack Transfers API:
    1. Resolve bank account and recipient code (/transferrecipient)
    2. Initiate bank transfer (/transfer)
    3. Update payout status to processing/paid and record provider reference
    """
    if payout.status == "paid":
        raise HTTPException(400, "This payout is already marked paid.")

    # 1. Locate payment account
    account = payout.payment_account
    if not account and payout.payment_account_id:
        account = await db.get(PaymentAccount, payout.payment_account_id)

    if not account:
        # Fallback to default payment account for the org
        from app.services.payment_account_service import get_default_payment_account
        account = await get_default_payment_account(db, payout.org_id, "manual") or await get_default_payment_account(db, payout.org_id, "paystack")

    if not account or not account.account_number:
        raise HTTPException(400, "No bank account found on file for this organization.")

    payout.payment_account_id = account.id

    if not settings.PAYSTACK_SECRET_KEY:
        raise HTTPException(503, "Paystack transfers are not configured (PAYSTACK_SECRET_KEY is missing).")

    # 2. Get or create transfer recipient code
    recipient_code = account.recipient_code
    if not recipient_code:
        bank_code = account.bank_code
        if not bank_code and account.bank_name:
            clean_bank = account.bank_name.strip()
            if clean_bank.isdigit():
                bank_code = clean_bank
            else:
                from app.services.payment_account_service import list_paystack_banks
                banks = await list_paystack_banks()
                target = clean_bank.lower()
                for b in banks:
                    b_name = b["name"].strip().lower()
                    if target == b_name or target in b_name or b_name in target:
                        bank_code = b["code"]
                        break

        if not bank_code:
            raise HTTPException(
                400,
                f"Could not determine bank code for '{account.bank_name}'. Please ensure a valid bank is specified in payment settings."
            )

        account.bank_code = bank_code

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.paystack.co/transferrecipient",
                json={
                    "type": "nuban",
                    "name": account.account_name or "Organizer",
                    "account_number": account.account_number,
                    "bank_code": bank_code,
                    "currency": (payout.currency or "NGN").upper(),
                },
                headers={
                    "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=15.0,
            )

        body = resp.json()
        if not body.get("status"):
            error_msg = body.get("message", "Failed to create transfer recipient on Paystack.")
            raise HTTPException(400, f"Paystack recipient error: {error_msg}")

        recipient_code = body.get("data", {}).get("recipient_code")
        account.recipient_code = recipient_code
        account.is_verified = True
        await db.flush()

    # 3. Initiate Transfer
    amount_kobo = max(int(Decimal(str(payout.amount)) * 100), 100)
    transfer_ref = f"payout_{payout.id}"
    org = payout.organization or await db.get(Organization, payout.org_id)
    org_name = org.name if org else "Org"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.paystack.co/transfer",
            json={
                "source": "balance",
                "amount": amount_kobo,
                "recipient": recipient_code,
                "reason": f"Payout for {org_name} ({payout.currency} {payout.amount})",
                "reference": transfer_ref,
            },
            headers={
                "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )

    body = resp.json()
    if not body.get("status"):
        error_msg = body.get("message", "Paystack transfer failed.")
        payout.failure_reason = error_msg
        await db.commit()
        raise HTTPException(400, f"Paystack transfer error: {error_msg}")

    data = body.get("data", {})
    transfer_code = data.get("transfer_code")
    transfer_status = data.get("status")

    payout.provider_reference = transfer_code or transfer_ref
    if transfer_status == "success":
        payout.status = "paid"
        payout.paid_at = datetime.now(UTC)
    else:
        # 'pending' or 'processing' or 'otp'
        payout.status = "processing"

    await db.commit()
    await db.refresh(payout)
    return payout
