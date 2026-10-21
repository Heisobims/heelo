from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from app import plans
from app.dependencies import CurrentUser, DBSession, OrgAccess
from app.permissions import Permission, require_permission
from app.plans import PlanFeature
from app.schemas.sponsor import (
    SponsorCreateRequest,
    SponsorOut,
    SponsorPortalUpdateRequest,
    SponsorUpdateRequest,
)
from app.services import sponsor_service as sp_svc

SponsorsManageAccess = Annotated[tuple, Depends(require_permission(Permission.SPONSORS_MANAGE))]

router_event = APIRouter(
    prefix="/api/v1/organizations/{slug}/events/{event_id}/sponsors", tags=["sponsors"]
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


def _sponsor_out(sponsor) -> dict:
    return SponsorOut.model_validate(sponsor).model_dump(mode="json")


@router_event.get("")
async def list_sponsors(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    sponsors = await sp_svc.list_sponsors(db, event.id)
    return {"success": True, "data": [_sponsor_out(s) for s in sponsors]}


@router_event.post("", status_code=201)
async def create_sponsor(
    slug: str,
    event_id: str,
    data: SponsorCreateRequest,
    db: DBSession,
    org_access: SponsorsManageAccess,
):
    org, role, is_owner = org_access
    plans.require_feature(org.plan, PlanFeature.SPONSORS)
    event = await _get_event_for_org(db, event_id, org.id)
    sponsor = await sp_svc.create_sponsor(db, event.id, data)
    return {"success": True, "data": _sponsor_out(sponsor)}


@router_event.patch("/{sponsor_id}")
async def update_sponsor(
    slug: str,
    event_id: str,
    sponsor_id: str,
    data: SponsorUpdateRequest,
    db: DBSession,
    org_access: SponsorsManageAccess,
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    try:
        sid = uuid.UUID(sponsor_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid sponsor ID.") from err
    sponsor = await sp_svc.get_sponsor(db, event.id, sid)
    sponsor = await sp_svc.update_sponsor(db, sponsor, data)
    return {"success": True, "data": _sponsor_out(sponsor)}


@router_event.delete("/{sponsor_id}", status_code=204)
async def delete_sponsor(
    slug: str, event_id: str, sponsor_id: str, db: DBSession, org_access: SponsorsManageAccess
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    try:
        sid = uuid.UUID(sponsor_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid sponsor ID.") from err
    sponsor = await sp_svc.get_sponsor(db, event.id, sid)
    await sp_svc.delete_sponsor(db, sponsor)


class SponsorInviteRequest(BaseModel):
    email: EmailStr


@router_event.post("/{sponsor_id}/invite", status_code=201)
async def invite_sponsor(
    slug: str,
    event_id: str,
    sponsor_id: str,
    data: SponsorInviteRequest,
    db: DBSession,
    org_access: SponsorsManageAccess,
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    try:
        sid = uuid.UUID(sponsor_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid sponsor ID.") from err
    sponsor = await sp_svc.get_sponsor(db, event.id, sid)
    await sp_svc.send_sponsor_invite(db, sponsor, data.email, event.title)
    return {"success": True}


# ── Public ───────────────────────────────────────────────────────────────────

router_public = APIRouter(prefix="/api/v1/events/{slug}/sponsors", tags=["sponsors-public"])


@router_public.get("")
async def list_public_sponsors(slug: str, db: DBSession):
    from app.models.event import Event

    event = await db.scalar(select(Event).where(Event.slug == slug))
    if not event:
        raise HTTPException(404, "Event not found.")
    sponsors = await sp_svc.list_sponsors(db, event.id)
    return {"success": True, "data": [_sponsor_out(s) for s in sponsors]}


# ── Sponsor portal (self-service, real user account) ───────────────────────

router_portal = APIRouter(prefix="/api/v1/sponsor-portal", tags=["sponsor-portal"])


@router_portal.get("/invite/{token}")
async def preview_sponsor_invite(token: str, db: DBSession):
    """Public - lets the claim page show what's being claimed before the
    visitor signs in or registers."""
    from app.models.event import Event

    payload = sp_svc.decode_sponsor_invite_token(token)
    sponsor = await sp_svc.get_sponsor_by_id(db, uuid.UUID(payload["sponsor_id"]))
    if not sponsor:
        raise HTTPException(404, "Sponsor not found.")
    event = await db.get(Event, sponsor.event_id)
    return {
        "success": True,
        "data": {
            "sponsor_name": sponsor.name,
            "event_title": event.title if event else None,
            "already_claimed": sponsor.invite_accepted,
        },
    }


@router_portal.post("/invite/{token}/claim")
async def claim_sponsor_invite(token: str, db: DBSession, current_user: CurrentUser):
    payload = sp_svc.decode_sponsor_invite_token(token)
    sponsor = await sp_svc.get_sponsor_by_id(db, uuid.UUID(payload["sponsor_id"]))
    if not sponsor:
        raise HTTPException(404, "Sponsor not found.")
    sponsor = await sp_svc.claim_sponsor(db, sponsor, current_user.id)
    return {"success": True, "data": _sponsor_out(sponsor)}


@router_portal.get("/me")
async def list_my_sponsorships(db: DBSession, current_user: CurrentUser):
    sponsors = await sp_svc.list_my_sponsorships(db, current_user.id)
    return {"success": True, "data": [_sponsor_out(s) for s in sponsors]}


@router_portal.patch("/me/{sponsor_id}")
async def update_my_sponsor(
    sponsor_id: str, data: SponsorPortalUpdateRequest, db: DBSession, current_user: CurrentUser
):
    try:
        sid = uuid.UUID(sponsor_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid sponsor ID.") from err
    sponsor = await sp_svc.get_my_sponsor(db, current_user.id, sid)
    sponsor = await sp_svc.update_my_sponsor_profile(db, sponsor, data)
    return {"success": True, "data": _sponsor_out(sponsor)}
