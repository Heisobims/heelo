"""
Admin API — all routes under /api/v1/admin/, require user.role == 'admin'.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.services import admin_service as adm_svc

router_admin = APIRouter(prefix="/api/v1/admin", tags=["admin"])

DBSession = Annotated[AsyncSession, Depends(get_db)]


async def require_admin(current_user=Depends(get_current_user)):
    if getattr(current_user, "role", None) != "admin":
        raise HTTPException(403, "Admin access required.")
    return current_user


AdminUser = Annotated[object, Depends(require_admin)]


# ── Orgs ──────────────────────────────────────────────────────────────────────


@router_admin.post("/organizations/{org_id}/suspend")
async def suspend_org(org_id: str, db: DBSession, _: AdminUser):
    try:
        org = await adm_svc.suspend_org(db, uuid.UUID(org_id))
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"success": True, "data": {"id": str(org.id), "is_active": org.is_active}}


@router_admin.post("/organizations/{org_id}/reinstate")
async def reinstate_org(org_id: str, db: DBSession, _: AdminUser):
    try:
        org = await adm_svc.reinstate_org(db, uuid.UUID(org_id))
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"success": True, "data": {"id": str(org.id), "is_active": org.is_active}}


class PlanIn(BaseModel):
    plan: str


@router_admin.patch("/organizations/{org_id}/plan")
async def set_org_plan(org_id: str, body: PlanIn, db: DBSession, _: AdminUser):
    try:
        org = await adm_svc.set_org_plan(db, uuid.UUID(org_id), body.plan)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"success": True, "data": {"id": str(org.id), "plan": org.plan}}


# ── Users ─────────────────────────────────────────────────────────────────────


@router_admin.post("/users/{user_id}/ban")
async def ban_user(user_id: str, db: DBSession, _: AdminUser):
    try:
        user = await adm_svc.ban_user(db, uuid.UUID(user_id))
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"success": True, "data": {"id": str(user.id), "banned": user.deleted_at is not None}}


@router_admin.post("/users/{user_id}/unban")
async def unban_user(user_id: str, db: DBSession, _: AdminUser):
    try:
        user = await adm_svc.unban_user(db, uuid.UUID(user_id))
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"success": True, "data": {"id": str(user.id), "banned": False}}


class RoleIn(BaseModel):
    role: str


@router_admin.patch("/users/{user_id}/role")
async def set_role(user_id: str, body: RoleIn, db: DBSession, _: AdminUser):
    try:
        user = await adm_svc.set_user_role(db, uuid.UUID(user_id), body.role)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"success": True, "data": {"id": str(user.id), "role": user.role}}


# ── Vendors / venues ────────────────────────────────────────────────────────


@router_admin.post("/vendors/{vendor_id}/suspend")
async def suspend_vendor(vendor_id: str, db: DBSession, _: AdminUser):
    try:
        vendor = await adm_svc.suspend_vendor(db, uuid.UUID(vendor_id))
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"success": True, "data": {"id": str(vendor.id), "status": vendor.status}}


@router_admin.post("/vendors/{vendor_id}/reinstate")
async def reinstate_vendor(vendor_id: str, db: DBSession, _: AdminUser):
    try:
        vendor = await adm_svc.reinstate_vendor(db, uuid.UUID(vendor_id))
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"success": True, "data": {"id": str(vendor.id), "status": vendor.status}}


# ── Broadcasts (platform-wide promotional email) ──────────────────────────────

_VALID_AUDIENCES = {"all", "organizer", "attendee", "vendor", "admin"}


class BroadcastIn(BaseModel):
    subject: str
    body: str
    audience_category: str
    channel: str = "email"


def _broadcast_dict(b) -> dict:
    return {
        "id": str(b.id),
        "subject": b.subject,
        "audience_category": b.audience_category,
        "channel": b.channel,
        "recipient_count": b.recipient_count,
        "sent_count": b.sent_count,
        "failed_count": b.failed_count,
        "status": b.status,
        "created_at": b.created_at.isoformat(),
        "sent_at": b.sent_at.isoformat() if b.sent_at else None,
    }


@router_admin.get("/broadcasts/audience-count")
async def broadcast_audience_count(category: str, db: DBSession, _: AdminUser):
    if category not in _VALID_AUDIENCES:
        raise HTTPException(400, f"Unknown audience category '{category}'.")
    counts = await adm_svc.get_user_category_counts(db)
    return {"success": True, "data": {"count": counts[category]}}


@router_admin.post("/broadcasts/test")
async def send_broadcast_test(body: BroadcastIn, db: DBSession, admin_user: AdminUser):
    """Send the composed email to the admin's own address only, no DB record."""
    from app.services import admin_broadcast_service as bc_svc
    from app.services import email_service as em

    html = bc_svc.render_personalized(body.body, admin_user)
    await em.send_async(to=admin_user.email, subject=f"[TEST] {body.subject}", html=html)
    return {"success": True, "data": {"sent_to": admin_user.email}}


@router_admin.post("/broadcasts", status_code=201)
async def create_and_send_broadcast(body: BroadcastIn, db: DBSession, admin_user: AdminUser):
    from app.services import admin_broadcast_service as bc_svc

    if body.audience_category not in _VALID_AUDIENCES:
        raise HTTPException(400, f"Unknown audience category '{body.audience_category}'.")
    if body.channel not in ("email", "notification", "both"):
        raise HTTPException(400, f"Unknown channel '{body.channel}'.")
    if not body.subject.strip() or not body.body.strip():
        raise HTTPException(400, "Subject and body are required.")

    bad_tags = bc_svc.validate_merge_tags(body.body)
    if bad_tags:
        raise HTTPException(400, f"Unsupported merge tag(s): {', '.join(bad_tags)}")

    broadcast = await bc_svc.create_broadcast(
        db,
        created_by=uuid.UUID(str(admin_user.id)),
        subject=body.subject,
        body=body.body,
        audience_category=body.audience_category,
        channel=body.channel,
    )

    from app.tasks.admin_broadcast import send_broadcast

    send_broadcast.delay(str(broadcast.id))

    return {"success": True, "data": _broadcast_dict(broadcast)}


@router_admin.get("/broadcasts")
async def list_broadcasts(db: DBSession, _: AdminUser, page: int = 1):
    from app.services import admin_broadcast_service as bc_svc

    broadcasts, total = await bc_svc.list_broadcasts(db, page=page, per_page=20)
    return {
        "success": True,
        "data": {
            "items": [_broadcast_dict(b) for b in broadcasts],
            "meta": {"total": total, "page": page},
        },
    }
