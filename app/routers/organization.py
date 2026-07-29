from __future__ import annotations

import uuid

from io import BytesIO

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from PIL import Image
from sqlalchemy import select

from app.database import get_db
from app.dependencies import CurrentUser, CurrentUserID, DBSession, OrgAccess
from app.models.organization import Organization, OrganizationMember
from app.schemas.organization import (
    InviteMemberRequest,
    OrgCreateRequest,
    OrgListItem,
    OrgMemberOut,
    OrgOut,
    OrgUpdateRequest,
    UpdateMemberRoleRequest,
)
from app.services import organization_service as svc

router_api = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])


def _success(data) -> dict:
    return {"success": True, "data": data}


# ── Create org ────────────────────────────────────────────────────────────────

@router_api.post("", status_code=status.HTTP_201_CREATED)
async def create_organization(
    body: OrgCreateRequest,
    current_user: CurrentUser,
    db: DBSession,
):
    org = await svc.create_organization(db, current_user.id, body)
    return _success(OrgOut.model_validate(org))


# ── List user's orgs ──────────────────────────────────────────────────────────

@router_api.get("")
async def list_my_organizations(current_user: CurrentUser, db: DBSession):
    orgs_with_role = await svc.get_user_organizations(db, current_user.id)
    items = [
        OrgListItem(
            id=entry["org"].id,
            name=entry["org"].name,
            slug=entry["org"].slug,
            logo_url=entry["org"].logo_url,
            country=entry["org"].country,
            currency=entry["org"].currency,
            plan=entry["org"].plan,
            role=entry["role"],
            is_owner=entry["is_owner"],
        )
        for entry in orgs_with_role
    ]
    return _success(items)


# ── Get single org ────────────────────────────────────────────────────────────

@router_api.get("/{slug}")
async def get_organization(slug: str, access: OrgAccess, db: DBSession):
    org, role, is_owner = access
    return _success({**OrgOut.model_validate(org).model_dump(), "role": role, "is_owner": is_owner})


# ── Update org ────────────────────────────────────────────────────────────────

@router_api.patch("/{slug}")
async def update_organization(
    slug: str,
    body: OrgUpdateRequest,
    access: OrgAccess,
    db: DBSession,
):
    org, role, is_owner = access
    if role not in ("admin",) and not is_owner:
        raise HTTPException(403, "Only org admins can update organization details.")
    updated = await svc.update_organization(db, org, body)
    return _success(OrgOut.model_validate(updated))


# ── Member list ───────────────────────────────────────────────────────────────

@router_api.get("/{slug}/members")
async def list_members(slug: str, access: OrgAccess, db: DBSession):
    org, role, _ = access
    members = await svc.get_org_members(db, org.id)
    result = []
    for entry in members:
        m = entry["member"]
        out = OrgMemberOut(
            id=m.id,
            user_id=m.user_id,
            org_id=m.org_id,
            role=m.role,
            status=m.status,
            invited_at=m.invited_at,
            accepted_at=m.accepted_at,
            invited_email=m.invited_email,
            user_name=entry["display_name"],
            user_email=entry["display_email"],
            user_avatar=entry["display_avatar"],
        )
        result.append(out)
    return _success(result)


# ── Invite member ─────────────────────────────────────────────────────────────

@router_api.post("/{slug}/members/invite", status_code=status.HTTP_201_CREATED)
async def invite_member(
    slug: str,
    body: InviteMemberRequest,
    access: OrgAccess,
    current_user: CurrentUser,
    db: DBSession,
):
    org, role, is_owner = access
    if role not in ("admin",) and not is_owner:
        raise HTTPException(403, "Only org admins can invite members.")
    try:
        await svc.invite_member(db, org, current_user, body.email, body.role)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return _success({"message": f"Invitation sent to {body.email}."})


# ── Accept invite ─────────────────────────────────────────────────────────────

@router_api.post("/accept-invite/{token}")
async def accept_invite(
    token: str,
    current_user: CurrentUser,
    db: DBSession,
):
    try:
        org = await svc.accept_invite(db, token, current_user)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _success({"redirect_to": f"/org/{org.slug}"})


# ── Update member role ────────────────────────────────────────────────────────

@router_api.patch("/{slug}/members/{user_id}/role")
async def update_member_role(
    slug: str,
    user_id: uuid.UUID,
    body: UpdateMemberRoleRequest,
    access: OrgAccess,
    db: DBSession,
):
    org, role, is_owner = access
    if role not in ("admin",) and not is_owner:
        raise HTTPException(403, "Only org admins can change roles.")
    try:
        member = await svc.update_member_role(db, org, user_id, body.role)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _success({"role": member.role})


# ── Remove member ─────────────────────────────────────────────────────────────

@router_api.delete("/{slug}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    slug: str,
    user_id: uuid.UUID,
    access: OrgAccess,
    current_user: CurrentUser,
    db: DBSession,
):
    org, role, is_owner = access
    if role not in ("admin",) and not is_owner:
        raise HTTPException(403, "Only org admins can remove members.")
    try:
        await svc.remove_member(db, org, user_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# ── Logo upload ───────────────────────────────────────────────────────────────

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 MB


@router_api.post("/{slug}/logo")
async def upload_logo(
    slug: str,
    access: OrgAccess,
    db: DBSession,
    logo: UploadFile = File(...),
):
    org, role, is_owner = access
    if role not in ("admin",) and not is_owner:
        raise HTTPException(403, "Only org admins can change the logo.")
    if logo.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, "Unsupported file type. Use JPEG, PNG or WebP.")
    image_bytes = await logo.read()
    if len(image_bytes) > _MAX_UPLOAD_SIZE:
        raise HTTPException(413, "Logo must be under 5 MB.")
    try:
        Image.open(BytesIO(image_bytes)).verify()
    except Exception:
        raise HTTPException(400, "File does not appear to be a valid image.")

    from app.utils import storage
    url = await storage.upload_image(
        image_bytes,
        folder=f"organizations/{org.id}/logo",
        filename="logo.jpg",
        max_width=512,
    )
    org.logo_url = url
    return _success({"logo_url": url})


# ── Onboarding state ──────────────────────────────────────────────────────────

@router_api.get("/{slug}/onboarding")
async def get_onboarding(slug: str, access: OrgAccess, db: DBSession):
    org, _, _ = access
    state = await svc.get_onboarding_state(db, org.id)
    return _success(state.model_dump())
