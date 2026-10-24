"""
Periodic cleanup for ticketing.

Paid checkouts reserve capacity (TicketType.quantity_reserved) at order
creation, released back only when payment is confirmed. If a buyer abandons
checkout (closes the tab, payment gateway session expires, no webhook ever
fires), nothing previously released that reservation - capacity leaked
permanently and a popular event could falsely show "sold out". This task
finds long-pending orders and releases them.
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


# Payment gateway checkout sessions are normally completed within minutes -
# after this window an unpaid order is treated as abandoned.
_RESERVATION_TIMEOUT_MINUTES = 30


@shared_task(name="app.tasks.ticketing.release_stale_reservations")
def release_stale_reservations() -> None:
    from sqlalchemy import update as _update

    from app.models.ticketing import Order, OrderItem, Registration, TicketType

    cutoff = datetime.now(UTC) - timedelta(minutes=_RESERVATION_TIMEOUT_MINUTES)

    with _db() as db:
        stale_orders = (
            db.query(Order)
            .filter(Order.payment_status == "pending", Order.created_at < cutoff)
            .all()
        )
        if not stale_orders:
            return

        released_count = 0
        for order in stale_orders:
            # Atomic claim - a payment webhook/callback could be confirming
            # this exact order right now (payment_service.confirm_order()
            # claims the same way), so only release capacity for orders this
            # UPDATE actually flips to 'failed'; skip any a concurrent
            # confirmation already won.
            claim = db.execute(
                _update(Order)
                .where(Order.id == order.id, Order.payment_status == "pending")
                .values(payment_status="failed")
            )
            if claim.rowcount == 0:
                continue

            items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
            for item in items:
                tt = db.query(TicketType).filter(TicketType.id == item.ticket_type_id).first()
                if tt and tt.quantity is not None:
                    tt.quantity_reserved = max(0, tt.quantity_reserved - item.quantity)

            db.query(Registration).filter(Registration.order_id == order.id).update(
                {"status": "cancelled"}, synchronize_session=False
            )
            released_count += 1

        db.commit()
        log.info("ticketing.stale_reservations_released", order_count=released_count)


@shared_task(name="app.tasks.ticketing.expire_waitlist_offers")
def expire_waitlist_offers() -> None:
    """
    A cancellation offers the freed spot to the next waitlisted person with a
    24h claim window (see ticketing_service.notify_next_waitlist_entry). If
    they never act, nothing previously moved on to the person behind them -
    the spot just sat unclaimed forever. This finds expired, unclaimed offers,
    drops them from the queue, and offers the spot to whoever's next.
    """
    from app.models.ticketing import Waitlist

    now = datetime.now(UTC)

    with _db() as db:
        expired = (
            db.query(Waitlist)
            .filter(Waitlist.notified_at.isnot(None), Waitlist.offer_expires_at < now)
            .all()
        )
        if not expired:
            return

        ticket_type_ids = {entry.ticket_type_id for entry in expired}
        for entry in expired:
            db.delete(entry)
        db.commit()
        log.info("ticketing.waitlist_offers_expired", count=len(expired))

        for ticket_type_id in ticket_type_ids:
            next_wl = (
                db.query(Waitlist)
                .filter(Waitlist.ticket_type_id == ticket_type_id, Waitlist.notified_at.is_(None))
                .order_by(Waitlist.position)
                .first()
            )
            if not next_wl:
                continue

            next_wl.notified_at = now
            next_wl.offer_expires_at = now + timedelta(hours=24)
            db.commit()

            try:
                from app.tasks.email import send_waitlist_notification as _email_wl

                _email_wl.delay(str(next_wl.id))
            except Exception as err:
                log.warning(
                    "ticketing.waitlist_email_enqueue_failed",
                    waitlist_id=str(next_wl.id),
                    error=str(err),
                )
            try:
                from app.tasks.whatsapp import send_waitlist_notification as _wa_wl

                _wa_wl.delay(str(next_wl.id))
            except Exception as err:
                log.warning(
                    "ticketing.waitlist_whatsapp_enqueue_failed",
                    waitlist_id=str(next_wl.id),
                    error=str(err),
                )


@shared_task(name="app.tasks.ticketing.send_abandoned_checkout_nudges")
def send_abandoned_checkout_nudges() -> None:
    """Find unpaid orders created between 20 mins and 24 hours ago that haven't
    received a recovery nudge, and dispatch recovery email/WhatsApp."""
    from app.models.ticketing import Order

    now = datetime.now(UTC)
    min_age = now - timedelta(minutes=20)
    max_age = now - timedelta(hours=24)

    with _db() as db:
        abandoned_orders = (
            db.query(Order)
            .filter(
                Order.payment_status == "pending",
                Order.created_at <= min_age,
                Order.created_at >= max_age,
                Order.abandoned_recovery_sent_at.is_(None),
                Order.buyer_email.isnot(None),
            )
            .limit(100)
            .all()
        )

        for order in abandoned_orders:
            order.abandoned_recovery_sent_at = now
            db.commit()

            try:
                from app.tasks.email import send_abandoned_checkout_recovery as _send_recovery

                _send_recovery.delay(str(order.id))
            except Exception as err:
                log.warning(
                    "ticketing.abandoned_recovery_enqueue_failed",
                    order_id=str(order.id),
                    error=str(err),
                )
