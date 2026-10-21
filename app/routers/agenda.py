from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy import select

from app import plans
from app.config import settings
from app.dependencies import CurrentUser, DBSession, OrgAccess
from app.permissions import Permission, require_permission
from app.plans import PlanFeature
from app.schemas.agenda import (
    SessionCreateRequest,
    SessionOut,
    SessionReorderRequest,
    SessionUpdateRequest,
)
from app.services import agenda_service as ag_svc

AgendaManageAccess = Annotated[tuple, Depends(require_permission(Permission.AGENDA_MANAGE))]

router_event = APIRouter(
    prefix="/api/v1/organizations/{slug}/events/{event_id}/sessions", tags=["agenda"]
)


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


def _session_out(session) -> dict:
    return SessionOut.model_validate(session).model_dump(mode="json")


@router_event.get("")
async def list_sessions(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    sessions = await ag_svc.list_sessions(db, event.id)
    return {"success": True, "data": [_session_out(s) for s in sessions]}


@router_event.post("", status_code=201)
async def create_session(
    slug: str,
    event_id: str,
    data: SessionCreateRequest,
    db: DBSession,
    org_access: AgendaManageAccess,
):
    org, role, is_owner = org_access
    plans.require_feature(org.plan, PlanFeature.SPEAKERS_AGENDA)
    event = await _get_event_for_org(db, event_id, org.id)
    session = await ag_svc.create_session(db, event.id, data)
    return {"success": True, "data": _session_out(session)}


@router_event.patch("/{session_id}")
async def update_session(
    slug: str,
    event_id: str,
    session_id: str,
    data: SessionUpdateRequest,
    db: DBSession,
    org_access: AgendaManageAccess,
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    try:
        sid = uuid.UUID(session_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid session ID.") from err
    session = await ag_svc.get_session(db, event.id, sid)
    session = await ag_svc.update_session(db, session, data)
    return {"success": True, "data": _session_out(session)}


@router_event.delete("/{session_id}", status_code=204)
async def delete_session(
    slug: str, event_id: str, session_id: str, db: DBSession, org_access: AgendaManageAccess
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    try:
        sid = uuid.UUID(session_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid session ID.") from err
    session = await ag_svc.get_session(db, event.id, sid)
    await ag_svc.delete_session(db, session)


@router_event.post("/reorder")
async def reorder_sessions(
    slug: str,
    event_id: str,
    data: SessionReorderRequest,
    db: DBSession,
    org_access: AgendaManageAccess,
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    sessions = await ag_svc.reorder_sessions(db, event.id, data.session_ids)
    return {"success": True, "data": [_session_out(s) for s in sessions]}


# ── Public ───────────────────────────────────────────────────────────────────

router_public = APIRouter(prefix="/api/v1/events/{slug}/sessions", tags=["agenda-public"])


@router_public.get("")
async def list_public_sessions(slug: str, request: Request, db: DBSession):
    from app.models.event import Event

    event = await db.scalar(select(Event).where(Event.slug == slug))
    if not event:
        raise HTTPException(404, "Event not found.")
    sessions = await ag_svc.list_sessions(db, event.id)

    user = None
    try:
        from app.routers.pages import _get_auth_context

        user, _ = await _get_auth_context(request, db)
    except Exception:
        pass

    bookmarked_ids = set()
    if user:
        bookmarked_ids = await ag_svc.get_user_bookmarked_session_ids(
            db, event_id=event.id, user_id=user.id
        )

    out = []
    for s in sessions:
        d = _session_out(s)
        d["is_bookmarked"] = s.id in bookmarked_ids
        out.append(d)

    return {"success": True, "data": out}


@router_public.post("/{session_id}/bookmark")
async def toggle_session_bookmark_endpoint(
    slug: str,
    session_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
):
    from app.models.event import Event

    event = await db.scalar(select(Event).where(Event.slug == slug))
    if not event:
        raise HTTPException(404, "Event not found.")

    is_bookmarked = await ag_svc.toggle_session_bookmark(
        db, session_id=session_id, user_id=current_user.id
    )
    return {
        "success": True,
        "is_bookmarked": is_bookmarked,
        "bookmarked": is_bookmarked,
        "message": "Session added to your itinerary." if is_bookmarked else "Session removed from itinerary.",
    }


@router_public.get("/bookmarks")
async def get_my_bookmarked_sessions(
    slug: str,
    db: DBSession,
    authorization: str | None = Header(default=None),
    heelo_access: str | None = Cookie(default=None),
):
    from app.models.event import Event

    event = await db.scalar(select(Event).where(Event.slug == slug))
    if not event:
        raise HTTPException(404, "Event not found.")

    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    elif heelo_access:
        token = heelo_access

    if not token:
        return {"success": True, "bookmarks": [], "bookmarked_session_ids": []}

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            return {"success": True, "bookmarks": [], "bookmarked_session_ids": []}
    except JWTError:
        return {"success": True, "bookmarks": [], "bookmarked_session_ids": []}

    bookmarked_ids = await ag_svc.get_user_bookmarked_session_ids(
        db, event_id=event.id, user_id=uuid.UUID(user_id)
    )
    ids_str = [str(sid) for sid in bookmarked_ids]
    return {
        "success": True,
        "bookmarks": ids_str,
        "bookmarked_session_ids": ids_str,
    }


