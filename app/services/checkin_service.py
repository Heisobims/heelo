from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, datetime

from fastapi import HTTPException
from jose import JWTError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ticketing import Registration, TicketType
from app.utils.auth import decode_ticket_qr_token


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
    except JWTError:
        raise HTTPException(400, "Invalid QR code.")

    if payload.get("type") != "ticket":
        raise HTTPException(400, "Invalid QR code type.")

    try:
        reg_id = uuid.UUID(payload["rid"])
        token_event_id = uuid.UUID(payload["eid"])
    except (KeyError, ValueError):
        raise HTTPException(400, "Malformed QR code.")

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
        from app.services import webhook_service as _wh_svc
        from app.models.event import Event
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
    except Exception:
        pass

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


async def find_by_phone(
    db: AsyncSession,
    phone_last10: str,
    event_id: uuid.UUID | None = None,
) -> list[Registration]:
    """Find registrations by last 10 digits of phone number.

    If event_id is given, scoped to that event. Otherwise searches across all
    published/live events (used by USSD to find a caller's tickets platform-wide).
    """
    from app.models.event import Event

    conditions = [
        Registration.attendee_phone.like(f"%{phone_last10}"),
        Registration.status.in_(["confirmed", "checked_in"]),
    ]

    if event_id is not None:
        conditions.append(Registration.event_id == event_id)
    else:
        active_events_sq = select(Event.id).where(
            Event.status.in_(["published", "live"]),
            Event.deleted_at.is_(None),
        )
        conditions.append(Registration.event_id.in_(active_events_sq))

    result = await db.scalars(
        select(Registration)
        .where(*conditions)
        .options(selectinload(Registration.ticket_type))
        .limit(5)
    )
    return list(result.all())
