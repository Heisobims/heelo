from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import DBSession, OrgAccess
from app.services import api_key_service as ak_svc

router_api_keys = APIRouter(
    prefix="/api/v1/organizations/{slug}/api-keys",
    tags=["api-keys"],
)


class CreateKeyIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


@router_api_keys.get("")
async def list_keys(slug: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    keys = await ak_svc.list_api_keys(db, org.id)
    return {
        "success": True,
        "data": [
            {
                "id": str(k.id),
                "name": k.name,
                "key_prefix": k.key_prefix,
                "is_active": k.is_active,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "expires_at": k.expires_at.isoformat() if k.expires_at else None,
                "created_at": k.created_at.isoformat(),
            }
            for k in keys
        ],
    }


@router_api_keys.post("", status_code=201)
async def create_key(slug: str, body: CreateKeyIn, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    if not is_owner and role not in ("admin",):
        raise HTTPException(403, "Only org admins can create API keys.")

    from app.models.organization import OrganizationMember
    from sqlalchemy import select

    # get the acting user id from the first member query (via org_access resolves current user)
    # We pass None for created_by since we don't have it in this dep; enhance if needed
    raw, key = await ak_svc.create_api_key(
        db, org_id=org.id, created_by=org.owner_id, name=body.name
    )
    return {
        "success": True,
        "data": {
            "id": str(key.id),
            "name": key.name,
            "key": raw,  # shown once only
            "key_prefix": key.key_prefix,
            "is_active": key.is_active,
            "created_at": key.created_at.isoformat(),
        },
        "warning": "Copy this key now. It will not be shown again.",
    }


@router_api_keys.delete("/{key_id}", status_code=200)
async def revoke_key(slug: str, key_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    if not is_owner and role not in ("admin",):
        raise HTTPException(403, "Only org admins can revoke API keys.")

    from sqlalchemy import select
    from app.models.api import ApiKey

    key = await db.scalar(
        select(ApiKey).where(
            ApiKey.id == uuid.UUID(key_id),
            ApiKey.org_id == org.id,
        )
    )
    if not key:
        raise HTTPException(404, "API key not found.")

    await ak_svc.revoke_api_key(db, key)
    return {"success": True, "message": "API key revoked."}
