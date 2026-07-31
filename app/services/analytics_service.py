from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ticketing import Order, PromoCode, Registration, TicketType


async def get_event_summary(db: AsyncSession, event_id: uuid.UUID) -> dict:
    reg_rows = await db.execute(
        select(Registration.status, func.count(Registration.id).label("n"))
        .where(Registration.event_id == event_id)
        .group_by(Registration.status)
    )
    by_status = {row.status: row.n for row in reg_rows}

    confirmed = by_status.get("confirmed", 0)
    checked_in = by_status.get("checked_in", 0)
    pending = by_status.get("pending", 0)
    cancelled = by_status.get("cancelled", 0)
    total_attendees = confirmed + checked_in

    rev = (
        await db.execute(
            select(
                func.coalesce(func.sum(Order.net_amount), 0).label("net"),
                func.coalesce(func.sum(Order.total_amount), 0).label("gross"),
                func.coalesce(func.sum(Order.discount_amount), 0).label("discounts"),
                func.count(Order.id).label("orders"),
            ).where(Order.event_id == event_id, Order.payment_status == "paid")
        )
    ).one()

    avg_order = float(rev.net) / rev.orders if rev.orders > 0 else 0
    checkin_rate = round(checked_in / total_attendees * 100, 1) if total_attendees > 0 else 0.0

    return {
        "total_registrations": total_attendees,
        "total_checked_in": checked_in,
        "total_confirmed": confirmed,
        "pending_registrations": pending,
        "cancelled_registrations": cancelled,
        "net_revenue": float(rev.net),
        "gross_revenue": float(rev.gross),
        "total_discounts": float(rev.discounts),
        "total_orders": rev.orders,
        "avg_order_value": round(avg_order, 2),
        "checkin_rate": checkin_rate,
    }


async def get_ticket_breakdown(db: AsyncSession, event_id: uuid.UUID) -> list[dict]:
    tts = await db.scalars(
        select(TicketType)
        .where(TicketType.event_id == event_id)
        .order_by(TicketType.sort_order, TicketType.created_at)
    )
    result = []
    for tt in tts.all():
        sold = tt.quantity_sold
        reserved = tt.quantity_reserved
        capacity = tt.quantity
        available = max(0, capacity - sold - reserved) if capacity is not None else None
        revenue = sold * float(tt.price)
        sold_pct = round(sold / capacity * 100) if capacity else None

        result.append(
            {
                "id": str(tt.id),
                "name": tt.name,
                "tier": tt.tier,
                "price": float(tt.price),
                "currency": tt.currency,
                "quantity_sold": sold,
                "quantity_reserved": reserved,
                "capacity": capacity,
                "available": available,
                "revenue": revenue,
                "sold_pct": sold_pct,
                "is_free": float(tt.price) == 0,
            }
        )
    return result


async def get_sales_over_time(db: AsyncSession, event_id: uuid.UUID) -> list[dict]:
    period = func.date_trunc("day", Order.created_at).label("period")
    rows = await db.execute(
        select(
            period,
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.net_amount), 0).label("revenue"),
        )
        .where(Order.event_id == event_id, Order.payment_status == "paid")
        .group_by(period)
        .order_by(period)
    )
    return [
        {
            "date": row.period.date().isoformat(),
            "orders": row.orders,
            "revenue": float(row.revenue),
        }
        for row in rows
    ]


async def get_registration_over_time(db: AsyncSession, event_id: uuid.UUID) -> list[dict]:
    period = func.date_trunc("day", Registration.created_at).label("period")
    rows = await db.execute(
        select(period, func.count(Registration.id).label("count"))
        .where(
            Registration.event_id == event_id,
            Registration.status.in_(["confirmed", "checked_in"]),
        )
        .group_by(period)
        .order_by(period)
    )
    return [{"date": row.period.date().isoformat(), "count": row.count} for row in rows]


async def get_utm_breakdown(db: AsyncSession, event_id: uuid.UUID) -> list[dict]:
    rows = await db.execute(
        select(
            func.coalesce(Order.utm_source, "(direct)").label("source"),
            func.coalesce(Order.utm_medium, "").label("medium"),
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.net_amount), 0).label("revenue"),
        )
        .where(Order.event_id == event_id, Order.payment_status == "paid")
        .group_by(text("1"), text("2"))
        .order_by(func.sum(Order.net_amount).desc())
        .limit(20)
    )
    return [
        {
            "source": row.source,
            "medium": row.medium or "—",
            "orders": row.orders,
            "revenue": float(row.revenue),
        }
        for row in rows
    ]


async def get_promo_breakdown(db: AsyncSession, event_id: uuid.UUID) -> list[dict]:
    promos = await db.scalars(
        select(PromoCode)
        .where(PromoCode.event_id == event_id)
        .order_by(PromoCode.used_count.desc())
    )
    return [
        {
            "code": p.code,
            "discount_type": p.discount_type,
            "discount_value": float(p.discount_value),
            "used_count": p.used_count,
            "max_uses": p.max_uses,
            "is_active": p.is_active,
            "expires_at": p.expires_at.isoformat() if p.expires_at else None,
        }
        for p in promos.all()
    ]


async def get_live_stats(db: AsyncSession, event_id: uuid.UUID) -> dict:
    reg_rows = await db.execute(
        select(Registration.status, func.count(Registration.id).label("n"))
        .where(Registration.event_id == event_id)
        .group_by(Registration.status)
    )
    by_status = {row.status: row.n for row in reg_rows}

    confirmed = by_status.get("confirmed", 0)
    checked_in = by_status.get("checked_in", 0)
    pending = by_status.get("pending", 0)
    total_attendees = confirmed + checked_in

    net = (
        await db.execute(
            select(func.coalesce(func.sum(Order.net_amount), 0).label("net")).where(
                Order.event_id == event_id, Order.payment_status == "paid"
            )
        )
    ).scalar() or 0

    checkin_rate = round(checked_in / total_attendees * 100, 1) if total_attendees > 0 else 0.0

    return {
        "total_registrations": total_attendees,
        "total_checked_in": checked_in,
        "pending_registrations": pending,
        "net_revenue": float(net),
        "checkin_rate": checkin_rate,
        "ts": datetime.now(UTC).isoformat(),
    }
