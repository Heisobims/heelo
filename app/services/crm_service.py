from __future__ import annotations

import csv
import io
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.ticketing import Registration, TicketType


async def list_registrations(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    event_id: uuid.UUID | None = None,
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict], int]:
    stmt = (
        select(
            Registration,
            Event.title.label("ev_title"),
            Event.id.label("ev_id"),
            TicketType.name.label("tt_name"),
            TicketType.currency.label("tt_currency"),
            TicketType.price.label("tt_price"),
        )
        .join(Event, Event.id == Registration.event_id)
        .join(TicketType, TicketType.id == Registration.ticket_type_id)
        .where(Event.org_id == org_id)
    )
    if event_id:
        stmt = stmt.where(Registration.event_id == event_id)
    if status:
        stmt = stmt.where(Registration.status == status)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                Registration.attendee_name.ilike(like),
                Registration.attendee_email.ilike(like),
            )
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total: int = await db.scalar(count_stmt) or 0

    result = await db.execute(
        stmt.order_by(Registration.created_at.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    )
    rows = result.all()

    out = []
    for r in rows:
        reg: Registration = r[0]
        out.append({
            "id": str(reg.id),
            "attendee_name": reg.attendee_name,
            "attendee_email": reg.attendee_email,
            "attendee_phone": reg.attendee_phone or "",
            "status": reg.status,
            "event_id": str(r.ev_id),
            "event_title": r.ev_title,
            "ticket_name": r.tt_name,
            "currency": r.tt_currency,
            "price": float(r.tt_price),
            "checked_in_at": reg.checked_in_at,
            "created_at": reg.created_at,
        })
    return out, total


async def get_events_for_org(db: AsyncSession, org_id: uuid.UUID) -> list[Event]:
    rows = await db.scalars(
        select(Event)
        .where(Event.org_id == org_id, Event.deleted_at.is_(None))
        .order_by(Event.start_datetime.desc())
    )
    return list(rows.all())


async def get_attendee_history(
    db: AsyncSession, org_id: uuid.UUID, email: str
) -> tuple[list[dict], dict]:
    stmt = (
        select(
            Registration,
            Event.title.label("ev_title"),
            Event.start_datetime.label("ev_start"),
            Event.id.label("ev_id"),
            TicketType.name.label("tt_name"),
            TicketType.currency.label("tt_currency"),
            TicketType.price.label("tt_price"),
        )
        .join(Event, Event.id == Registration.event_id)
        .join(TicketType, TicketType.id == Registration.ticket_type_id)
        .where(Event.org_id == org_id, Registration.attendee_email == email)
        .order_by(Registration.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    regs: list[dict] = []
    total_spend = 0.0
    currency = "NGN"
    attended_event_ids: set[str] = set()

    for r in rows:
        reg: Registration = r[0]
        paid = reg.status in ("confirmed", "checked_in")
        if paid:
            total_spend += float(r.tt_price)
            attended_event_ids.add(str(r.ev_id))
        currency = r.tt_currency
        regs.append({
            "id": str(reg.id),
            "event_id": str(r.ev_id),
            "event_title": r.ev_title,
            "event_start": r.ev_start,
            "ticket_name": r.tt_name,
            "currency": r.tt_currency,
            "price": float(r.tt_price),
            "status": reg.status,
            "checked_in_at": reg.checked_in_at,
            "created_at": reg.created_at,
        })

    first_seen = regs[-1]["created_at"] if regs else None
    last_seen = regs[0]["created_at"] if regs else None

    summary = {
        "email": email,
        "name": rows[0][0].attendee_name if rows else email,
        "phone": rows[0][0].attendee_phone or "" if rows else "",
        "total_registrations": len(regs),
        "events_attended": len(attended_event_ids),
        "total_spend": round(total_spend, 2),
        "currency": currency,
        "first_seen": first_seen,
        "last_seen": last_seen,
    }
    return regs, summary


async def export_csv_string(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    event_id: uuid.UUID | None = None,
    status: str | None = None,
    search: str | None = None,
) -> str:
    rows, _ = await list_registrations(
        db, org_id,
        event_id=event_id, status=status, search=search,
        page=1, per_page=10_000,
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Name", "Email", "Phone", "Event", "Ticket", "Status",
                     "Amount", "Currency", "Checked In", "Registered At"])
    for r in rows:
        writer.writerow([
            r["attendee_name"],
            r["attendee_email"],
            r["attendee_phone"],
            r["event_title"],
            r["ticket_name"],
            r["status"],
            r["price"],
            r["currency"],
            r["checked_in_at"].strftime("%Y-%m-%d %H:%M") if r["checked_in_at"] else "",
            r["created_at"].strftime("%Y-%m-%d %H:%M") if r["created_at"] else "",
        ])
    return buf.getvalue()
