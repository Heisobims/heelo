from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import HTTPException
from jose import JWTError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.checkin import Checkin
from app.models.ticketing import Registration
from app.utils.auth import decode_ticket_qr_token

logger = structlog.get_logger()


class AlreadyCheckedInError(Exception):
    """Raised when a registration is already checked in. Carries the registration for context."""

    def __init__(self, reg: Registration) -> None:
        self.reg = reg
        super().__init__("Already checked in.")


async def check_in_by_qr_token(
    db: AsyncSession,
    token: str,
    event_id: uuid.UUID,
) -> Registration:
    """Verify a QR code JWT and check in the matching registration."""
    try:
        payload = decode_ticket_qr_token(token)
    except JWTError as err:
        raise HTTPException(400, "Invalid QR code.") from err

    if payload.get("type") != "ticket":
        raise HTTPException(400, "Invalid QR code type.")

    try:
        reg_id = uuid.UUID(payload["rid"])
        token_event_id = uuid.UUID(payload["eid"])
    except (KeyError, ValueError) as err:
        raise HTTPException(400, "Malformed QR code.") from err

    if token_event_id != event_id:
        raise HTTPException(400, "QR code is for a different event.")

    return await _do_check_in(db, reg_id)


async def check_in_by_id(db: AsyncSession, registration_id: uuid.UUID) -> Registration:
    """Manually check in a registration by its UUID (staff portal)."""
    return await _do_check_in(db, registration_id)


async def _do_check_in(db: AsyncSession, reg_id: uuid.UUID) -> Registration:
    reg = await db.scalar(
        select(Registration)
        .where(Registration.id == reg_id)
        .options(selectinload(Registration.ticket_type))
    )
    if not reg:
        raise HTTPException(404, "Registration not found.")

    if reg.status == "checked_in":
        raise AlreadyCheckedInError(reg)

    if reg.status != "confirmed":
        raise HTTPException(
            400,
            f"Cannot check in: registration status is '{reg.status}'.",
        )

    reg.status = "checked_in"
    reg.checked_in_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(reg)

    try:
        from app.models.event import Event
        from app.services import webhook_service as _wh_svc

        ev = await db.scalar(select(Event).where(Event.id == reg.event_id))
        if ev:
            await _wh_svc.fire_event(
                db,
                org_id=ev.org_id,
                event_type="checkin.completed",
                payload={
                    "event": "checkin.completed",
                    "registration_id": str(reg.id),
                    "attendee_email": reg.attendee_email,
                    "attendee_name": reg.attendee_name,
                    "event_id": str(ev.id),
                    "checked_in_at": reg.checked_in_at.isoformat(),
                },
            )
    except Exception as err:
        logger.warning("checkin.webhook_failed", registration_id=str(reg.id), error=str(err))

    return reg


async def undo_check_in(db: AsyncSession, registration_id: uuid.UUID) -> Registration:
    """Revert a checked-in registration to confirmed."""
    reg = await db.scalar(
        select(Registration)
        .where(Registration.id == registration_id)
        .options(selectinload(Registration.ticket_type))
    )
    if not reg:
        raise HTTPException(404, "Registration not found.")
    if reg.status != "checked_in":
        raise HTTPException(400, "Registration is not checked in.")

    reg.status = "confirmed"
    reg.checked_in_at = None
    await db.commit()
    await db.refresh(reg)
    return reg


async def mark_virtual_join(db: AsyncSession, registration_id: uuid.UUID) -> Registration | None:
    """
    Attendee clicked their join link for a virtual/hybrid event. Records the first
    click as attendance (reusing the same checked_in_at/status fields in-person
    check-in uses, so virtual events show up in the same analytics) and logs a
    Checkin row for audit. Idempotent — repeat clicks (reloading the email, a
    second device) just no-op rather than erroring, since this sits in a redirect
    path the attendee shouldn't ever see fail.

    Returns None if the registration doesn't exist or isn't eligible (cancelled,
    refunded, never paid) so the caller can fall back to a generic response
    instead of granting "attendance" to a ticket that shouldn't have access.
    """
    reg = await db.scalar(
        select(Registration)
        .where(Registration.id == registration_id)
        .options(selectinload(Registration.event))
    )
    if not reg or not reg.event:
        return None
    if reg.status not in ("confirmed", "checked_in"):
        return None

    # This link is only ever sent for virtual/hybrid events — for an in-person
    # registration, don't mark attendance (that's what the door QR scan is for),
    # just let the caller redirect wherever makes sense (event page).
    if reg.event.format == "in_person":
        return reg

    if reg.status == "confirmed":
        reg.status = "checked_in"
        reg.checked_in_at = datetime.now(UTC)
        db.add(
            Checkin(
                registration_id=reg.id,
                event_id=reg.event_id,
                method="virtual_join",
                scanned_at=reg.checked_in_at,
            )
        )
        await db.commit()
        await db.refresh(reg)

    return reg


async def get_checkin_stats(db: AsyncSession, event_id: uuid.UUID) -> dict:
    rows = await db.execute(
        select(Registration.status, func.count(Registration.id))
        .where(
            Registration.event_id == event_id,
            Registration.status.not_in(["cancelled"]),
        )
        .group_by(Registration.status)
    )
    counts = dict(rows.all())

    total = sum(counts.values())
    checked_in = counts.get("checked_in", 0)
    confirmed = counts.get("confirmed", 0)
    pending = counts.get("pending", 0)

    return {
        "total": total,
        "confirmed": confirmed,
        "checked_in": checked_in,
        "pending": pending,
        "percent_checked_in": round(checked_in / total * 100, 1) if total else 0.0,
    }


async def get_live_pulse(db: AsyncSession, event) -> dict:
    """
    Organizer-facing mid-event glance: check-in rate, capacity fill, and which
    ticket tiers are actually filling the room right now.
    """
    stats = await get_checkin_stats(db, event.id)

    capacity = event.max_capacity
    checked_in = stats["checked_in"]
    stats["capacity"] = capacity
    stats["percent_of_capacity"] = round(checked_in / capacity * 100, 1) if capacity else None

    from app.models.ticketing import TicketType

    rows = await db.execute(
        select(
            TicketType.id,
            TicketType.name,
            TicketType.quantity,
            func.count(Registration.id).filter(Registration.status == "checked_in"),
            func.count(Registration.id).filter(
                Registration.status.in_(["confirmed", "checked_in"])
            ),
        )
        .select_from(TicketType)
        .outerjoin(Registration, Registration.ticket_type_id == TicketType.id)
        .where(TicketType.event_id == event.id)
        .group_by(TicketType.id, TicketType.name, TicketType.quantity)
        .order_by(TicketType.sort_order)
    )
    stats["ticket_tiers"] = [
        {
            "id": str(tid),
            "name": name,
            "quantity": qty,
            "checked_in": checked,
            "sold": sold,
            "percent_of_quantity": round(checked / qty * 100, 1) if qty else None,
        }
        for tid, name, qty, checked, sold in rows.all()
    ]

    return stats


async def get_checked_in_ids(db: AsyncSession, event_id: uuid.UUID) -> list[str]:
    """
    Full set of checked-in registration IDs for an event — cheap payload meant to be
    cached client-side (kiosk) so offline scans can be checked against recent server
    truth before being accepted, instead of only being caught after a background sync.
    """
    result = await db.scalars(
        select(Registration.id).where(
            Registration.event_id == event_id,
            Registration.status == "checked_in",
        )
    )
    return [str(rid) for rid in result.all()]


async def get_recent_check_ins(
    db: AsyncSession,
    event_id: uuid.UUID,
    limit: int = 30,
) -> list[Registration]:
    result = await db.scalars(
        select(Registration)
        .where(
            Registration.event_id == event_id,
            Registration.status == "checked_in",
        )
        .options(selectinload(Registration.ticket_type))
        .order_by(Registration.checked_in_at.desc())
        .limit(limit)
    )
    return list(result.all())


async def search_registrations(
    db: AsyncSession,
    event_id: uuid.UUID,
    query: str,
) -> list[Registration]:
    """Search confirmed/checked-in registrations by name or email."""
    term = f"%{query.strip().lower()}%"
    result = await db.scalars(
        select(Registration)
        .where(
            Registration.event_id == event_id,
            Registration.status.in_(["confirmed", "checked_in"]),
            or_(
                Registration.attendee_name.ilike(term),
                Registration.attendee_email.ilike(term),
                Registration.attendee_phone.ilike(term),
            ),
        )
        .options(selectinload(Registration.ticket_type))
        .limit(20)
    )
    return list(result.all())
