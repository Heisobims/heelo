from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.dependencies import DBSession, OrgAccess
from app.permissions import Permission, require_permission
from app.schemas.speaker import (
    EventSpeakerLinkRequest,
    EventSpeakerUpdateRequest,
    SpeakerCreateRequest,
    SpeakerOut,
    SpeakerUpdateRequest,
)
from app.services import speaker_service as sp_svc

SpeakersManageAccess = Annotated[tuple, Depends(require_permission(Permission.SPEAKERS_MANAGE))]

# ── Org-level speaker roster ────────────────────────────────────────────────

router_org = APIRouter(prefix="/api/v1/organizations/{slug}/speakers", tags=["speakers"])


def _speaker_out(speaker) -> dict:
    return SpeakerOut.model_validate(speaker).model_dump(mode="json")


@router_org.get("")
async def list_speakers(slug: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    speakers = await sp_svc.list_org_speakers(db, org.id)
    return {"success": True, "data": [_speaker_out(s) for s in speakers]}


@router_org.post("", status_code=201)
async def create_speaker(
    slug: str, data: SpeakerCreateRequest, db: DBSession, org_access: SpeakersManageAccess
):
    org, role, is_owner = org_access
    speaker = await sp_svc.create_speaker(db, org.id, data)
    return {"success": True, "data": _speaker_out(speaker)}


@router_org.patch("/{speaker_id}")
async def update_speaker(
    slug: str,
    speaker_id: str,
    data: SpeakerUpdateRequest,
    db: DBSession,
    org_access: SpeakersManageAccess,
):
    org, role, is_owner = org_access
    try:
        sid = uuid.UUID(speaker_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid speaker ID.") from err
    speaker = await sp_svc.get_org_speaker(db, org.id, sid)
    speaker = await sp_svc.update_speaker(db, speaker, data)
    return {"success": True, "data": _speaker_out(speaker)}


@router_org.delete("/{speaker_id}", status_code=204)
async def delete_speaker(
    slug: str, speaker_id: str, db: DBSession, org_access: SpeakersManageAccess
):
    org, role, is_owner = org_access
    try:
        sid = uuid.UUID(speaker_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid speaker ID.") from err
    speaker = await sp_svc.get_org_speaker(db, org.id, sid)
    await sp_svc.delete_speaker(db, speaker)


# ── Event People roster ─────────────────────────────────────────────────────

router_event = APIRouter(
    prefix="/api/v1/organizations/{slug}/events/{event_id}/speakers", tags=["event-speakers"]
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


_link_out = sp_svc.event_speaker_to_dict


@router_event.get("")
async def list_event_speakers(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    links = await sp_svc.list_event_speakers(db, event.id)
    return {"success": True, "data": [_link_out(link) for link in links]}


@router_event.post("", status_code=201)
async def add_event_speaker(
    slug: str,
    event_id: str,
    data: EventSpeakerLinkRequest,
    db: DBSession,
    org_access: SpeakersManageAccess,
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    link = await sp_svc.add_event_speaker(db, org.id, event.id, data)
    return {"success": True, "data": _link_out(link)}


@router_event.patch("/{link_id}")
async def update_event_speaker(
    slug: str,
    event_id: str,
    link_id: str,
    data: EventSpeakerUpdateRequest,
    db: DBSession,
    org_access: SpeakersManageAccess,
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    try:
        lid = uuid.UUID(link_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid speaker link ID.") from err
    link = await sp_svc.get_event_speaker_link(db, event.id, lid)
    link = await sp_svc.update_event_speaker(db, link, data)
    return {"success": True, "data": _link_out(link)}


@router_event.delete("/{link_id}", status_code=204)
async def remove_event_speaker(
    slug: str, event_id: str, link_id: str, db: DBSession, org_access: SpeakersManageAccess
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    try:
        lid = uuid.UUID(link_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid speaker link ID.") from err
    link = await sp_svc.get_event_speaker_link(db, event.id, lid)
    await sp_svc.remove_event_speaker(db, link)


# ── Public ───────────────────────────────────────────────────────────────────

router_public = APIRouter(prefix="/api/v1/events/{slug}/speakers", tags=["event-speakers-public"])


@router_public.get("")
async def list_public_event_speakers(slug: str, db: DBSession):
    from app.models.event import Event

    event = await db.scalar(select(Event).where(Event.slug == slug))
    if not event:
        raise HTTPException(404, "Event not found.")
    links = await sp_svc.list_event_speakers(db, event.id)
    return {"success": True, "data": [_link_out(link) for link in links]}
