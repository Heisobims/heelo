"""
Periodic cleanup for ticketing.

Paid checkouts reserve capacity (TicketType.quantity_reserved) at order
creation, released back only when payment is confirmed. If a buyer abandons
checkout (closes the tab, payment gateway session expires, no webhook ever
fires), nothing previously released that reservation — capacity leaked
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


# Payment gateway checkout sessions are normally completed within minutes —
# after this window an unpaid order is treated as abandoned.
_RESERVATION_TIMEOUT_MINUTES = 30


@shared_task(name="app.tasks.ticketing.release_stale_reservations")
def release_stale_reservations() -> None:
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

        for order in stale_orders:
            items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
            for item in items:
                tt = db.query(TicketType).filter(TicketType.id == item.ticket_type_id).first()
                if tt and tt.quantity is not None:
                    tt.quantity_reserved = max(0, tt.quantity_reserved - item.quantity)

            db.query(Registration).filter(Registration.order_id == order.id).update(
                {"status": "cancelled"}, synchronize_session=False
            )
            order.payment_status = "failed"

        db.commit()
        log.info("ticketing.stale_reservations_released", order_count=len(stale_orders))
