from __future__ import annotations

import uuid

import httpx
import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.ticketing import Registration
from app.utils.badge_pdf import BadgeData, generate_badge_pdf
from app.utils.qr_code import generate_qr_png

logger = structlog.get_logger()

_LOGO_FETCH_TIMEOUT = 5.0


async def _fetch_logo_bytes(logo_url: str | None) -> bytes | None:
    """Best-effort - a badge with a missing/unreachable logo still renders
    fine without one, so failures here are logged and swallowed, not raised."""
    if not logo_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=_LOGO_FETCH_TIMEOUT) as client:
            resp = await client.get(logo_url)
            resp.raise_for_status()
            return resp.content
    except Exception as err:
        logger.warning("badge.logo_fetch_failed", logo_url=logo_url, error=str(err))
        return None


async def _badge_data_for_registration(
    reg: Registration, org: Organization, logo_bytes: bytes | None
) -> BadgeData:
    return BadgeData(
        attendee_name=reg.attendee_name,
        ticket_type_name=reg.ticket_type.name if reg.ticket_type else "General",
        event_title=reg.event.title if reg.event else "",
        org_name=org.name,
        brand_color=org.display_brand_color,
        logo_bytes=logo_bytes,
        qr_bytes=generate_qr_png(reg.qr_code),
        show_powered_by=org.show_powered_by,
        attendee_email=reg.attendee_email,
    )


async def get_badge_pdf_for_registration(db: AsyncSession, reg: Registration) -> bytes:
    if not reg.event:
        raise HTTPException(404, "Event not found.")
    org = await db.scalar(select(Organization).where(Organization.id == reg.event.org_id))
    if not org:
        raise HTTPException(404, "Organization not found.")

    logo_bytes = await _fetch_logo_bytes(org.display_logo_url)
    data = await _badge_data_for_registration(reg, org, logo_bytes)
    return generate_badge_pdf([data])


async def get_badges_pdf_for_event(
    db: AsyncSession, event_id: uuid.UUID, org: Organization, *, statuses: list[str]
) -> bytes:
    from sqlalchemy.orm import selectinload

    regs = await db.scalars(
        select(Registration)
        .where(Registration.event_id == event_id, Registration.status.in_(statuses))
        .options(selectinload(Registration.ticket_type), selectinload(Registration.event))
        .order_by(Registration.attendee_name)
    )
    registrations = list(regs.all())
    if not registrations:
        raise HTTPException(404, "No matching registrations to print badges for.")

    logo_bytes = await _fetch_logo_bytes(org.display_logo_url)
    badges = [await _badge_data_for_registration(r, org, logo_bytes) for r in registrations]
    return generate_badge_pdf(badges)
