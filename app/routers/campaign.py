from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import CurrentUser, DBSession, OrgAccess
from app.models.campaign import Campaign
from app.permissions import Permission, require_permission
from app.schemas.campaign import CampaignCreateRequest, CampaignSendRequest, CampaignUpdateRequest
from app.services import campaign_service as camp_svc

router_campaigns = APIRouter(
    prefix="/api/v1/organizations/{slug}/campaigns",
    tags=["campaigns"],
)

CampaignsManageAccess = Annotated[tuple, Depends(require_permission(Permission.CAMPAIGNS_MANAGE))]


async def _get_campaign_for_org(db, campaign_id_str: str, org_id: uuid.UUID) -> Campaign:
    try:
        cid = uuid.UUID(campaign_id_str)
    except ValueError as err:
        raise HTTPException(422, "Invalid campaign ID.") from err
    c = await camp_svc.get_campaign(db, cid)
    if not c or c.org_id != org_id:
        raise HTTPException(404, "Campaign not found.")
    return c


# ── List ──────────────────────────────────────────────────────────────────────


@router_campaigns.get("")
async def list_campaigns(
    slug: str,
    db: DBSession,
    org_access: OrgAccess,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    org, role, is_owner = org_access
    items, total = await camp_svc.list_campaigns(db, org.id, page=page, per_page=per_page)
    return {
        "success": True,
        "data": [_campaign_dict(c) for c in items],
        "meta": {"total": total, "page": page, "per_page": per_page},
    }


# ── Create ────────────────────────────────────────────────────────────────────


@router_campaigns.post("", status_code=201)
async def create_campaign(
    slug: str,
    data: CampaignCreateRequest,
    db: DBSession,
    org_access: CampaignsManageAccess,
    current_user: CurrentUser,
):
    org, role, is_owner = org_access
    campaign = await camp_svc.create_campaign(db, org.id, current_user.id, data)
    return {"success": True, "data": _campaign_dict(campaign)}


# ── Audience count preview ────────────────────────────────────────────────────
#
# Must be registered before GET /{campaign_id} — FastAPI matches routes in
# registration order, and "/_audience-count" would otherwise be captured by
# the {campaign_id} path parameter, fail UUID parsing, and 422.


@router_campaigns.get("/_audience-count")
async def audience_count(
    slug: str,
    db: DBSession,
    org_access: OrgAccess,
    event_id: str | None = Query(None),
    statuses: list[str] = Query(["confirmed", "checked_in"]),
):
    org, role, is_owner = org_access
    eid: uuid.UUID | None = None
    if event_id:
        try:
            eid = uuid.UUID(event_id)
        except ValueError as err:
            raise HTTPException(422, "Invalid event_id.") from err

    count = await camp_svc.preview_audience_count(db, org.id, eid, statuses)
    return {"success": True, "data": {"count": count}}


# ── Detail ────────────────────────────────────────────────────────────────────


@router_campaigns.get("/{campaign_id}")
async def get_campaign(slug: str, campaign_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    c = await _get_campaign_for_org(db, campaign_id, org.id)
    stats = await camp_svc.get_recipient_stats(db, c.id)
    return {"success": True, "data": {**_campaign_dict(c), "recipient_stats": stats}}


# ── Update (draft only) ───────────────────────────────────────────────────────


@router_campaigns.patch("/{campaign_id}")
async def update_campaign(
    slug: str,
    campaign_id: str,
    data: CampaignUpdateRequest,
    db: DBSession,
    org_access: CampaignsManageAccess,
):
    org, role, is_owner = org_access
    c = await _get_campaign_for_org(db, campaign_id, org.id)
    c = await camp_svc.update_campaign(db, c, data)
    return {"success": True, "data": _campaign_dict(c)}


# ── Delete ────────────────────────────────────────────────────────────────────


@router_campaigns.delete("/{campaign_id}", status_code=204)
async def delete_campaign(
    slug: str, campaign_id: str, db: DBSession, org_access: CampaignsManageAccess
):
    org, role, is_owner = org_access
    c = await _get_campaign_for_org(db, campaign_id, org.id)
    await camp_svc.delete_campaign(db, c)


# ── Send / schedule ───────────────────────────────────────────────────────────


@router_campaigns.post("/{campaign_id}/send")
async def send_or_schedule(
    slug: str,
    campaign_id: str,
    data: CampaignSendRequest,
    db: DBSession,
    org_access: CampaignsManageAccess,
):
    org, role, is_owner = org_access
    c = await _get_campaign_for_org(db, campaign_id, org.id)

    if data.scheduled_at:
        c = await camp_svc.schedule_campaign(db, c, data.scheduled_at)
        return {"success": True, "data": _campaign_dict(c), "message": "Campaign scheduled."}
    else:
        c = await camp_svc.send_now(db, c)
        return {"success": True, "data": _campaign_dict(c), "message": "Campaign is sending."}


# ── Cancel scheduled campaign ─────────────────────────────────────────────────


@router_campaigns.post("/{campaign_id}/cancel")
async def cancel_campaign(
    slug: str, campaign_id: str, db: DBSession, org_access: CampaignsManageAccess
):
    org, role, is_owner = org_access
    c = await _get_campaign_for_org(db, campaign_id, org.id)
    c = await camp_svc.cancel_campaign(db, c)
    return {"success": True, "data": _campaign_dict(c), "message": "Campaign returned to draft."}


# ── Recipients ────────────────────────────────────────────────────────────────


@router_campaigns.get("/{campaign_id}/recipients")
async def list_recipients(slug: str, campaign_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    c = await _get_campaign_for_org(db, campaign_id, org.id)
    recs = await camp_svc.get_recent_recipients(db, c.id)
    return {
        "success": True,
        "data": [
            {
                "id": str(r.id),
                "name": r.name,
                "email": r.email,
                "whatsapp_number": r.whatsapp_number,
                "status": r.status,
                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
                "error_message": r.error_message,
            }
            for r in recs
        ],
    }


# ── Helper ────────────────────────────────────────────────────────────────────


def _campaign_dict(c: Campaign) -> dict:
    return {
        "id": str(c.id),
        "org_id": str(c.org_id),
        "event_id": str(c.event_id) if c.event_id else None,
        "type": c.type,
        "name": c.name,
        "subject": c.subject,
        "body": c.body,
        "status": c.status,
        "audience_filter": c.audience_filter,
        "scheduled_at": c.scheduled_at.isoformat() if c.scheduled_at else None,
        "sent_at": c.sent_at.isoformat() if c.sent_at else None,
        "recipient_count": c.recipient_count,
        "sent_count": c.sent_count,
        "delivered_count": c.delivered_count,
        "open_count": c.open_count,
        "click_count": c.click_count,
        "failed_count": c.failed_count,
        "created_at": c.created_at.isoformat(),
    }
