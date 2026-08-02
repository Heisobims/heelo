from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.dependencies import DBSession, OrgAccess
from app.services import badge_service as badge_svc
from app.services import ticketing_service as tk_svc

# ── Attendee-facing: capability URL, same pattern as /registrations/{id}/qr.png ──

router_registrations = APIRouter(prefix="/api/v1/registrations", tags=["badges"])


@router_registrations.get("/{registration_id}/badge.pdf")
async def registration_badge_pdf(registration_id: str, db: DBSession):
    try:
        reg_id = uuid.UUID(registration_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid registration ID.") from err

    reg = await tk_svc.get_registration_by_id(db, reg_id)
    if not reg:
        raise HTTPException(404, "Registration not found.")
    if reg.status not in ("confirmed", "checked_in"):
        raise HTTPException(403, "Ticket is not confirmed.")

    pdf_bytes = await badge_svc.get_badge_pdf_for_registration(db, reg)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="badge.pdf"'},
    )


# ── Organizer-facing: bulk print run for an event ────────────────────────────

router_org = APIRouter(
    prefix="/api/v1/organizations/{slug}/events/{event_id}", tags=["badges-organizer"]
)


@router_org.get("/badges.pdf")
async def event_badges_pdf(
    slug: str,
    event_id: str,
    db: DBSession,
    org_access: OrgAccess,
    status: str = "confirmed,checked_in",
):
    from sqlalchemy import select

    from app.models.event import Event

    org, role, is_owner = org_access
    try:
        eid = uuid.UUID(event_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid event ID.") from err
    event = await db.scalar(select(Event).where(Event.id == eid, Event.org_id == org.id))
    if not event:
        raise HTTPException(404, "Event not found.")

    statuses = [s.strip() for s in status.split(",") if s.strip()]
    pdf_bytes = await badge_svc.get_badges_pdf_for_event(db, event.id, org, statuses=statuses)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{event.slug}-badges.pdf"'},
    )
