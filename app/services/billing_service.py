"""Self-serve org-plan billing - upgrade/renew/downgrade.

Model: a plan upgrade is a real one-off checkout for 30 days of access, not
an auto-recurring subscription (no card is stored, nothing is silently
re-charged). Renewal is manual, nudged by reminder emails before expiry
(app/tasks/billing.py); an org that doesn't renew in time is automatically
moved to Free by that same task. Downgrades are scheduled, not immediate -
an org that asks to downgrade keeps its current plan/limits until
plan_expires_at, so already-paid-for time is never lost.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import structlog
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.payment import PlanInvoice
from app.services import payment_service

logger = structlog.get_logger()

# Multi-currency plan prices for international organizers
PLAN_PRICES_BY_CURRENCY: dict[str, dict[str, Decimal]] = {
    "NGN": {"growth": Decimal("7500"), "pro": Decimal("25000")},
    "USD": {"growth": Decimal("19"), "pro": Decimal("49")},
    "EUR": {"growth": Decimal("18"), "pro": Decimal("45")},
    "GBP": {"growth": Decimal("15"), "pro": Decimal("39")},
    "CAD": {"growth": Decimal("25"), "pro": Decimal("65")},
    "AUD": {"growth": Decimal("29"), "pro": Decimal("75")},
    "KES": {"growth": Decimal("2500"), "pro": Decimal("6500")},
    "GHS": {"growth": Decimal("250"), "pro": Decimal("650")},
    "ZAR": {"growth": Decimal("350"), "pro": Decimal("900")},
}

# Default NGN pricing (backward compatibility)
PLAN_PRICES: dict[str, Decimal] = PLAN_PRICES_BY_CURRENCY["NGN"]


def get_plan_price(plan: str, currency: str = "NGN") -> Decimal:
    curr = (currency or "NGN").upper()
    curr_map = PLAN_PRICES_BY_CURRENCY.get(curr)
    if not curr_map:
        # If western / global currency not explicitly matched, use USD; otherwise NGN
        curr_map = PLAN_PRICES_BY_CURRENCY["USD"] if curr in ("USD", "EUR", "GBP", "CAD", "AUD") else PLAN_PRICES_BY_CURRENCY["NGN"]
    return curr_map.get(plan, PLAN_PRICES[plan])

_PERIOD_DAYS = 30


def _plan_rank(plan: str) -> int:
    return {"free": 0, "growth": 1, "pro": 2, "enterprise": 3}.get(plan, 0)


async def start_plan_checkout(
    db: AsyncSession, org: Organization, plan: str, *, initiated_by: uuid.UUID | None = None
) -> str:
    """Create a pending invoice for `plan` and return the checkout URL."""
    if plan not in PLAN_PRICES:
        raise HTTPException(400, "That plan isn't available for self-serve checkout.")
    if _plan_rank(plan) < _plan_rank(org.plan):
        raise HTTPException(
            400, "That's a lower tier than your current plan. Use the downgrade option instead."
        )

    # Invalidate any invoice from an earlier, abandoned checkout attempt so
    # it can never be paid and confirmed later - without this, an org that
    # starts a Growth checkout, abandons it, then pays for Pro could have
    # the stale Growth link completed afterward and silently downgraded
    # back, discarding the Pro period it already paid for.
    await db.execute(
        update(PlanInvoice)
        .where(PlanInvoice.org_id == org.id, PlanInvoice.status == "pending")
        .values(status="expired")
    )

    currency = (org.currency or "NGN").upper()
    list_price = get_plan_price(plan, currency)
    # Heelo is the direct merchant here (no organizer subaccount involved),
    # so only the payment gateway's own processing fee needs grossing up -
    # there's no separate "platform fee" to add on top of itself.
    provider = payment_service.select_provider(currency)
    total, gateway_fee = payment_service.gross_up_gateway_fee_only(list_price, provider)

    invoice = PlanInvoice(
        org_id=org.id,
        plan=plan,
        amount=float(total),
        gateway_fee_amount=float(gateway_fee),
        currency=currency,
        status="pending",
        period_start=datetime.now(UTC),
        period_end=datetime.now(UTC) + timedelta(days=_PERIOD_DAYS),
        initiated_by=initiated_by,
    )
    db.add(invoice)
    await db.flush()

    url = await payment_service.initialize_plan_payment(db, invoice, org)
    logger.info(
        "billing.checkout_started", org_id=str(org.id), plan=plan, invoice_id=str(invoice.id)
    )
    return url


async def confirm_plan_invoice(db: AsyncSession, invoice: PlanInvoice) -> PlanInvoice:
    """Mark the invoice paid and apply the plan change. Idempotent - a
    webhook and a browser callback can both race to confirm the same
    invoice, so the status transition is an atomic claim, exactly like
    confirm_order() in payment_service.py."""
    claim = await db.execute(
        update(PlanInvoice)
        .where(PlanInvoice.id == invoice.id, PlanInvoice.status == "pending")
        .values(status="paid")
        .returning(PlanInvoice.id)
    )
    if claim.fetchone() is None:
        return invoice
    invoice.status = "paid"

    org = await db.get(Organization, invoice.org_id)
    now = datetime.now(UTC)

    if invoice.plan == org.plan:
        # Renewal - extend from the current expiry (or now, if somehow
        # already lapsed) so paid days are never lost.
        base = org.plan_expires_at if (org.plan_expires_at and org.plan_expires_at > now) else now
        org.plan_expires_at = base + timedelta(days=_PERIOD_DAYS)
    else:
        # Tier change - a fresh 30-day period at the new tier. No proration:
        # there's no stored card/billing engine to reconcile a partial
        # credit against, so this is the simplest correct behavior.
        org.plan = invoice.plan
        org.plan_expires_at = now + timedelta(days=_PERIOD_DAYS)

    org.pending_plan_change = None
    org.plan_reminder_sent_at = None
    await db.commit()

    logger.info(
        "billing.invoice_confirmed",
        org_id=str(org.id),
        plan=org.plan,
        plan_expires_at=org.plan_expires_at.isoformat(),
    )

    try:
        from app.tasks.email import send_plan_receipt

        send_plan_receipt.delay(str(invoice.id))
    except Exception as err:
        logger.warning(
            "billing.receipt_email_enqueue_failed", invoice_id=str(invoice.id), error=str(err)
        )

    return invoice


async def schedule_downgrade(db: AsyncSession, org: Organization) -> Organization:
    """Org keeps its current plan/limits until plan_expires_at, then the
    renewal task (app/tasks/billing.py) applies the downgrade to Free."""
    if org.plan == "free":
        return org
    if not org.plan_expires_at:
        # No paid period on record (e.g. an admin-set plan with no
        # expiry) - nothing to preserve, downgrade takes effect immediately.
        org.plan = "free"
        org.pending_plan_change = None
        await db.commit()
        return org

    org.pending_plan_change = "free"
    await db.commit()
    logger.info("billing.downgrade_scheduled", org_id=str(org.id))
    return org


async def cancel_scheduled_downgrade(db: AsyncSession, org: Organization) -> Organization:
    org.pending_plan_change = None
    await db.commit()
    return org


async def list_invoices(db: AsyncSession, org_id: uuid.UUID, limit: int = 20) -> list[PlanInvoice]:
    result = await db.scalars(
        select(PlanInvoice)
        .where(PlanInvoice.org_id == org_id)
        .order_by(PlanInvoice.created_at.desc())
        .limit(limit)
    )
    return list(result.all())
