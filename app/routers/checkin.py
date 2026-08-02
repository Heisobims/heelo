from __future__ import annotations

import asyncio
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.dependencies import DBSession, OrgAccess
from app.models.ticketing import Registration
from app.permissions import Permission, require_permission
from app.services import checkin_service as ci_svc

router_checkin = APIRouter(
    prefix="/api/v1/organizations/{slug}/events/{event_id}",
    tags=["checkin"],
)

CheckinScanAccess = Annotated[tuple, Depends(require_permission(Permission.CHECKIN_SCAN))]
CheckinUndoAccess = Annotated[tuple, Depends(require_permission(Permission.CHECKIN_UNDO))]


class CheckInRequest(BaseModel):
    qr_token: str | None = None
    registration_id: str | None = None


def _reg_dict(reg: Registration) -> dict:
    return {
        "registration_id": str(reg.id),
        "attendee_name": reg.attendee_name,
        "attendee_email": reg.attendee_email,
        "ticket_type": reg.ticket_type.name if reg.ticket_type else None,
        "status": reg.status,
        "checked_in_at": reg.checked_in_at.isoformat() if reg.checked_in_at else None,
    }


async def _get_event_for_org(db, event_id_str: str, org_id: uuid.UUID):
    from app.models.event import Event

    try:
        eid = uuid.UUID(event_id_str)
    except ValueError as err:
        raise HTTPException(422, "Invalid event ID.") from err
    event = await db.scalar(select(Event).where(Event.id == eid, Event.org_id == org_id))
    if not event:
        raise HTTPException(404, "Event not found.")
    return event


@router_checkin.post("/check-in")
async def check_in(
    slug: str,
    event_id: str,
    data: CheckInRequest,
    db: DBSession,
    org_access: CheckinScanAccess,
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)

    if not data.qr_token and not data.registration_id:
        raise HTTPException(400, "Provide qr_token or registration_id.")

    try:
        if data.qr_token:
            reg = await ci_svc.check_in_by_qr_token(db, data.qr_token, event.id)
        else:
            try:
                rid = uuid.UUID(data.registration_id)
            except (ValueError, TypeError) as err:
                raise HTTPException(422, "Invalid registration_id.") from err
            reg = await ci_svc.check_in_by_id(db, rid)

    except ci_svc.AlreadyCheckedInError as e:
        return JSONResponse(
            status_code=409,
            content={
                "success": False,
                "error": {
                    "code": "ALREADY_CHECKED_IN",
                    "message": "Already checked in.",
                    "details": _reg_dict(e.reg),
                },
            },
        )

    return {"success": True, "data": _reg_dict(reg)}


@router_checkin.post("/check-in/{reg_id}/undo")
async def undo_check_in(
    slug: str,
    event_id: str,
    reg_id: str,
    db: DBSession,
    org_access: CheckinUndoAccess,
):
    org, role, is_owner = org_access

    event = await _get_event_for_org(db, event_id, org.id)
    try:
        rid = uuid.UUID(reg_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid registration ID.") from err

    reg = await db.scalar(
        select(Registration).where(
            Registration.id == rid,
            Registration.event_id == event.id,
        )
    )
    if not reg:
        raise HTTPException(404, "Registration not found.")

    reg = await ci_svc.undo_check_in(db, rid)
    return {"success": True, "data": _reg_dict(reg)}


@router_checkin.get("/check-in/checked-in-ids")
async def checkin_checked_in_ids(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    """
    Lightweight list of already-checked-in registration IDs, polled by the kiosk to
    keep a local dedup cache fresh — lets it reject an obvious duplicate scan before
    even attempting the network call (or while offline), instead of only catching it
    on a later background sync.
    """
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    ids = await ci_svc.get_checked_in_ids(db, event.id)
    return {"success": True, "data": ids}


@router_checkin.get("/check-in/stats")
async def checkin_stats(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    stats = await ci_svc.get_checkin_stats(db, event.id)
    return {"success": True, "data": stats}


@router_checkin.get("/check-in/pulse")
async def checkin_pulse(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    """Live-pulse snapshot — capacity fill + per-ticket-tier check-in rate."""
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    stats = await ci_svc.get_live_pulse(db, event)
    return {"success": True, "data": stats}


@router_checkin.get("/check-in/stream")
async def checkin_stream(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    """SSE endpoint — pushes live pulse stats every 5 s. Nginx must have proxy_buffering off."""
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)

    async def _generate():
        try:
            while True:
                async with AsyncSessionLocal() as session:
                    stats = await ci_svc.get_live_pulse(session, event)
                yield f"data: {json.dumps(stats)}\n\n"
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router_checkin.get("/check-in/recent")
async def checkin_recent(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    regs = await ci_svc.get_recent_check_ins(db, event.id)
    return {"success": True, "data": [_reg_dict(r) for r in regs]}


@router_checkin.get("/check-in/search")
async def checkin_search(
    slug: str,
    event_id: str,
    q: str,
    db: DBSession,
    org_access: OrgAccess,
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    if len(q.strip()) < 2:
        return {"success": True, "data": []}
    regs = await ci_svc.search_registrations(db, event.id, q)
    return {"success": True, "data": [_reg_dict(r) for r in regs]}
