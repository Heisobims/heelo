"""
Periodic task for self-serve org-plan billing (manual renewal, not
auto-recurring): reminds orgs before their plan expires, and auto-downgrades
orgs whose plan has already lapsed without renewal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from celery import shared_task

from app.config import settings

log = structlog.get_logger()

_engine = None
_SyncSession = None


def _db():
    global _engine, _SyncSession
    if _engine is None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        _engine = create_engine(
            settings.DATABASE_URL_SYNC, pool_pre_ping=True, pool_size=2, max_overflow=4
        )
        _SyncSession = sessionmaker(bind=_engine)
    return _SyncSession()


# Send the renewal reminder once an org's plan is within this many days of
# expiring - and don't re-send until a fresh window opens (a renewal moves
# plan_expires_at forward, which naturally resets plan_reminder_sent_at too).
_REMINDER_WINDOW_DAYS = 3


@shared_task(name="app.tasks.billing.process_plan_renewals")
def process_plan_renewals() -> None:
    from sqlalchemy import and_, or_

    from app.models.organization import Organization
    from app.tasks.email import send_plan_downgraded, send_plan_renewal_reminder

    now = datetime.now(UTC)
    reminder_cutoff = now + timedelta(days=_REMINDER_WINDOW_DAYS)

    with _db() as db:
        # ── Reminders ────────────────────────────────────────────────────
        due_for_reminder = (
            db.query(Organization)
            .filter(
                Organization.plan != "free",
                Organization.plan_expires_at.isnot(None),
                Organization.plan_expires_at <= reminder_cutoff,
                Organization.plan_expires_at > now,
                or_(
                    Organization.plan_reminder_sent_at.is_(None),
                    Organization.plan_reminder_sent_at
                    < Organization.plan_expires_at - timedelta(days=_REMINDER_WINDOW_DAYS),
                ),
            )
            .all()
        )
        reminded = 0
        for org in due_for_reminder:
            org.plan_reminder_sent_at = now
            reminded += 1
        db.commit()

        for org in due_for_reminder:
            try:
                send_plan_renewal_reminder.delay(str(org.id))
            except Exception as err:
                log.warning("billing.reminder_enqueue_failed", org_id=str(org.id), error=str(err))

        # ── Auto-downgrade ──────────────────────────────────────────────
        lapsed = (
            db.query(Organization)
            .filter(
                and_(
                    Organization.plan != "free",
                    Organization.plan_expires_at.isnot(None),
                    Organization.plan_expires_at < now,
                )
            )
            .all()
        )
        downgraded = 0
        previous_plans: dict[str, str] = {}
        for org in lapsed:
            previous_plans[str(org.id)] = org.plan
            org.plan = org.pending_plan_change or "free"
            org.plan_expires_at = None
            org.pending_plan_change = None
            org.plan_reminder_sent_at = None
            downgraded += 1
            log.info(
                "billing.plan_downgraded",
                org_id=str(org.id),
                previous_plan=previous_plans[str(org.id)],
                new_plan=org.plan,
            )
        db.commit()

        for org in lapsed:
            try:
                send_plan_downgraded.delay(str(org.id), previous_plans[str(org.id)])
            except Exception as err:
                log.warning(
                    "billing.downgraded_email_enqueue_failed", org_id=str(org.id), error=str(err)
                )

    log.info("billing.process_plan_renewals.done", reminded=reminded, downgraded=downgraded)


@shared_task(name="app.tasks.billing.send_pending_payouts_digest")
def send_pending_payouts_digest() -> None:
    """Weekly summary of orgs Heelo owes a manual payout to (no auto-split
    rail - see app/services/payout_service.py, whose get_owed_amount/
    list_orgs_with_pending_payouts this mirrors in sync form, matching how
    process_plan_renewals above also duplicates its query in sync form
    rather than calling the async service directly)."""
    from decimal import Decimal

    from sqlalchemy import func

    from app.models.event import Event
    from app.models.organization import Organization
    from app.models.payment import Payout
    from app.models.ticketing import REVENUE_STATUSES, Order

    if not settings.OPS_ALERT_EMAIL:
        log.info("billing.pending_payouts_digest.skipped_no_ops_email")
        return

    with _db() as db:
        revenue_rows = (
            db.query(
                Event.org_id,
                func.coalesce(func.sum(Order.net_amount - Order.refunded_amount), 0).label(
                    "revenue"
                ),
            )
            .select_from(Order)
            .join(Event, Event.id == Order.event_id)
            .filter(
                Order.payment_status.in_(REVENUE_STATUSES),
                Order.auto_split_applied.is_(False),
            )
            .group_by(Event.org_id)
            .all()
        )
        paid_rows = (
            db.query(Payout.org_id, func.coalesce(func.sum(Payout.amount), 0).label("paid"))
            .filter(Payout.status == "paid")
            .group_by(Payout.org_id)
            .all()
        )
        paid_by_org = {row.org_id: Decimal(str(float(row.paid))) for row in paid_rows}

        pending: list[tuple[str, str, float]] = []
        for row in revenue_rows:
            owed = Decimal(str(float(row.revenue))) - paid_by_org.get(row.org_id, Decimal("0"))
            if owed > 0:
                org = db.query(Organization).filter(Organization.id == row.org_id).first()
                if org:
                    pending.append((org.name, org.currency or "NGN", float(owed)))

    if not pending:
        log.info("billing.pending_payouts_digest.nothing_owed")
        return

    pending.sort(key=lambda row: row[2], reverse=True)
    rows_html = "".join(
        f"<tr><td style='padding:6px 12px;'>{name}</td>"
        f"<td style='padding:6px 12px;'>{currency} {amount:,.2f}</td></tr>"
        for name, currency, amount in pending
    )
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: Arial, sans-serif; padding: 24px;">
      <h2>Pending manual payouts</h2>
      <p>{len(pending)} organization(s) currently owed a manual payout.</p>
      <table style="border-collapse: collapse;">{rows_html}</table>
      <p><a href="{settings.FRONTEND_URL}/admin/payouts">Review in admin →</a></p>
    </body>
    </html>
    """

    from app.services import email_service as em

    em.send_sync(
        to=settings.OPS_ALERT_EMAIL,
        subject=f"Heelo: {len(pending)} pending manual payout(s)",
        html=html,
    )
    log.info("billing.pending_payouts_digest.sent", org_count=len(pending))


@shared_task(name="app.tasks.billing.auto_release_vendor_escrow")
def auto_release_vendor_escrow() -> int:
    """Auto-release escrow to vendor payable balance when 48-hour delivery SLA has passed without dispute."""
    from datetime import UTC, datetime
    import uuid
    from app.models.vendor import Vendor, VendorBooking, VendorTransaction

    now = datetime.now(UTC)
    released_count = 0

    with _db() as db:
        eligible_bookings = (
            db.query(VendorBooking)
            .filter(
                VendorBooking.escrow_status == "held_in_escrow",
                VendorBooking.status.in_(["delivered", "confirmed", "in_progress"]),
                VendorBooking.auto_release_deadline.isnot(None),
                VendorBooking.auto_release_deadline <= now,
            )
            .all()
        )

        for booking in eligible_bookings:
            vendor = db.query(Vendor).filter(Vendor.id == booking.vendor_id).first()
            if vendor:
                earnings = float(booking.vendor_earnings)
                vendor.escrow_balance = max(0.0, float(vendor.escrow_balance) - earnings)
                vendor.payable_balance = float(vendor.payable_balance) + earnings
                vendor.total_earned = float(vendor.total_earned) + earnings

            booking.status = "completed"
            booking.escrow_status = "released"
            booking.escrow_released_at = now
            booking.completed_at = now

            tx = VendorTransaction(
                reference=f"REL-AUTO-{uuid.uuid4().hex[:8].upper()}",
                vendor_id=booking.vendor_id,
                booking_id=booking.id,
                type="escrow_release",
                gross_amount=float(booking.total_amount),
                platform_fee=float(booking.commission_amount),
                net_amount=float(booking.vendor_earnings),
                currency=booking.currency,
                status="completed",
                payment_provider=booking.payment_method or "paystack",
                metadata_json={"release_reason": "auto_release_timeout", "released_at": now.isoformat()},
            )
            db.add(tx)
            released_count += 1

        db.commit()

        # Send completion emails
        for booking in eligible_bookings:
            try:
                from app.tasks.email import send_vendor_booking_completed_notification
                send_vendor_booking_completed_notification.delay(str(booking.id))
            except Exception as err:
                log.warning("billing.auto_release_email_failed", booking_id=str(booking.id), error=str(err))

    log.info("billing.auto_release_vendor_escrow.completed", count=released_count)
    return released_count
