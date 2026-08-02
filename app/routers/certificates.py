from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.dependencies import DBSession, OrgAccess
from app.permissions import Permission, require_permission
from app.services import certificate_service as cert_svc
from app.services import ticketing_service as tk_svc

RegistrationsManageAccess = Annotated[
    tuple, Depends(require_permission(Permission.REGISTRATIONS_MANAGE))
]

# ── Attendee-facing: capability URL, same pattern as badge.pdf / qr.png ──────

router_registrations = APIRouter(prefix="/api/v1/registrations", tags=["certificates"])


@router_registrations.get("/{registration_id}/certificate.pdf")
async def registration_certificate_pdf(registration_id: str, db: DBSession):
    try:
        reg_id = uuid.UUID(registration_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid registration ID.") from err

    reg = await tk_svc.get_registration_by_id(db, reg_id)
    if not reg:
        raise HTTPException(404, "Registration not found.")

    pdf_bytes = await cert_svc.get_certificate_pdf_for_registration(db, reg)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="certificate.pdf"'},
    )


# ── Organizer-facing: generate (gate) + bulk download ────────────────────────

router_org = APIRouter(
    prefix="/api/v1/organizations/{slug}/events/{event_id}", tags=["certificates-organizer"]
)


async def _get_event_for_org(db, event_id_str: str, org_id: uuid.UUID):
    from sqlalchemy import select

    from app.models.event import Event

    try:
        eid = uuid.UUID(event_id_str)
    except ValueError as err:
        raise HTTPException(422, "Invalid event ID.") from err
    event = await db.scalar(select(Event).where(Event.id == eid, Event.org_id == org_id))
    if not event:
        raise HTTPException(404, "Event not found.")
    return event


@router_org.post("/certificates/generate")
async def generate_event_certificates(
    slug: str, event_id: str, db: DBSession, org_access: RegistrationsManageAccess
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    event = await cert_svc.generate_certificates(db, event)
    return {
        "success": True,
        "data": {"certificates_generated_at": event.certificates_generated_at.isoformat()},
    }


@router_org.get("/certificates.pdf")
async def event_certificates_pdf(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    pdf_bytes = await cert_svc.get_certificates_pdf_for_event(db, event, org)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{event.slug}-certificates.pdf"'},
    )
