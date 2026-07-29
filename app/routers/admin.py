"""
Admin API — all routes under /api/v1/admin/, require user.role == 'admin'.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
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
        raise HTTPException(404, str(e))
    return {"success": True, "data": {"id": str(org.id), "is_active": org.is_active}}


@router_admin.post("/organizations/{org_id}/reinstate")
async def reinstate_org(org_id: str, db: DBSession, _: AdminUser):
    try:
        org = await adm_svc.reinstate_org(db, uuid.UUID(org_id))
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"success": True, "data": {"id": str(org.id), "is_active": org.is_active}}


class PlanIn(BaseModel):
    plan: str


@router_admin.patch("/organizations/{org_id}/plan")
async def set_org_plan(org_id: str, body: PlanIn, db: DBSession, _: AdminUser):
    try:
        org = await adm_svc.set_org_plan(db, uuid.UUID(org_id), body.plan)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "data": {"id": str(org.id), "plan": org.plan}}


# ── Users ─────────────────────────────────────────────────────────────────────

@router_admin.post("/users/{user_id}/ban")
async def ban_user(user_id: str, db: DBSession, _: AdminUser):
    try:
        user = await adm_svc.ban_user(db, uuid.UUID(user_id))
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"success": True, "data": {"id": str(user.id), "banned": user.deleted_at is not None}}


@router_admin.post("/users/{user_id}/unban")
async def unban_user(user_id: str, db: DBSession, _: AdminUser):
    try:
        user = await adm_svc.unban_user(db, uuid.UUID(user_id))
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"success": True, "data": {"id": str(user.id), "banned": False}}


class RoleIn(BaseModel):
    role: str


@router_admin.patch("/users/{user_id}/role")
async def set_role(user_id: str, body: RoleIn, db: DBSession, _: AdminUser):
    try:
        user = await adm_svc.set_user_role(db, uuid.UUID(user_id), body.role)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "data": {"id": str(user.id), "role": user.role}}
