from __future__ import annotations

import re
import uuid
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from PIL import Image
from pydantic import BaseModel, Field

from app import plans
from app.dependencies import CurrentUser, DBSession, OrgAccess
from app.permissions import Permission, require_permission
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

OrgSettingsAccess = Annotated[tuple, Depends(require_permission(Permission.ORG_SETTINGS_EDIT))]
TeamManageAccess = Annotated[tuple, Depends(require_permission(Permission.TEAM_MANAGE))]


def _success(data) -> dict:
    return {"success": True, "data": data}


# ── Create org ────────────────────────────────────────────────────────────────


@router_api.post("", status_code=status.HTTP_201_CREATED)
async def create_organization(
    body: OrgCreateRequest,
    current_user: CurrentUser,
    db: DBSession,
):
    await plans.check_org_limit(db, current_user.id)
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
    access: OrgSettingsAccess,
    db: DBSession,
):
    org, role, is_owner = access
    updated = await svc.update_organization(db, org, body)
    return _success(OrgOut.model_validate(updated))


# ── Custom domain ────────────────────────────────────────────────────────────


class SetCustomDomainRequest(BaseModel):
    domain: str = Field(..., min_length=3, max_length=255)


@router_api.post("/{slug}/custom-domain")
async def set_custom_domain(
    slug: str,
    body: SetCustomDomainRequest,
    access: OrgSettingsAccess,
    db: DBSession,
):
    org, role, is_owner = access
    plans.require_feature(org.plan, plans.PlanFeature.CUSTOM_DOMAIN)
    existing_count = 1 if org.custom_domain else 0
    plans.check_custom_domain_limit(existing_count, org.plan)

    domain = body.domain.strip().lower()
    if not re.match(
        r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$", domain
    ):
        raise HTTPException(422, "That doesn't look like a valid domain.")

    updated = await svc.set_custom_domain(db, org, domain)
    return _success(
        {
            "domain": updated.custom_domain,
            "verified": updated.custom_domain_verified,
            "verification_record": {
                "type": "TXT",
                "name": f"_heelo-verify.{updated.custom_domain}",
                "value": updated.custom_domain_verification_token,
            },
        }
    )


@router_api.post("/{slug}/custom-domain/verify")
async def verify_custom_domain(slug: str, access: OrgSettingsAccess, db: DBSession):
    org, role, is_owner = access
    plans.require_feature(org.plan, plans.PlanFeature.CUSTOM_DOMAIN)
    updated = await svc.verify_custom_domain(db, org)
    return _success({"domain": updated.custom_domain, "verified": updated.custom_domain_verified})


@router_api.delete("/{slug}/custom-domain", status_code=status.HTTP_204_NO_CONTENT)
async def remove_custom_domain(slug: str, access: OrgSettingsAccess, db: DBSession):
    org, role, is_owner = access
    await svc.remove_custom_domain(db, org)


# ── SSO domain (Enterprise) ──────────────────────────────────────────────────


class SetSSODomainRequest(BaseModel):
    domain: str = Field(..., min_length=3, max_length=255)


class SetSSOEnforcementRequest(BaseModel):
    enforced: bool


@router_api.post("/{slug}/sso")
async def set_sso_domain(
    slug: str,
    body: SetSSODomainRequest,
    access: OrgSettingsAccess,
    db: DBSession,
):
    org, role, is_owner = access
    plans.require_feature(org.plan, plans.PlanFeature.SSO)

    domain = body.domain.strip().lower()
    if not re.match(
        r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$", domain
    ):
        raise HTTPException(422, "That doesn't look like a valid domain.")

    updated = await svc.set_sso_domain(db, org, domain)
    return _success(
        {
            "domain": updated.sso_domain,
            "verified": updated.sso_domain_verified,
            "enforced": updated.sso_enforced,
            "verification_record": {
                "type": "TXT",
                "name": f"_heelo-sso-verify.{updated.sso_domain}",
                "value": updated.sso_verification_token,
            },
        }
    )


@router_api.post("/{slug}/sso/verify")
async def verify_sso_domain(slug: str, access: OrgSettingsAccess, db: DBSession):
    org, role, is_owner = access
    plans.require_feature(org.plan, plans.PlanFeature.SSO)
    updated = await svc.verify_sso_domain(db, org)
    return _success({"domain": updated.sso_domain, "verified": updated.sso_domain_verified})


@router_api.post("/{slug}/sso/enforce")
async def set_sso_enforcement(
    slug: str,
    body: SetSSOEnforcementRequest,
    access: OrgSettingsAccess,
    db: DBSession,
):
    org, role, is_owner = access
    plans.require_feature(org.plan, plans.PlanFeature.SSO)
    updated = await svc.set_sso_enforcement(db, org, body.enforced)
    return _success({"enforced": updated.sso_enforced})


@router_api.delete("/{slug}/sso", status_code=status.HTTP_204_NO_CONTENT)
async def remove_sso_domain(slug: str, access: OrgSettingsAccess, db: DBSession):
    org, role, is_owner = access
    await svc.remove_sso_domain(db, org)


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
    access: TeamManageAccess,
    current_user: CurrentUser,
    db: DBSession,
):
    org, role, is_owner = access
    await plans.check_seat_limit(db, org)
    try:
        member = await svc.invite_member(db, org, current_user, body.email, body.role)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _success(
        {
            "message": f"Invitation sent to {body.email}.",
            "member": OrgMemberOut(
                id=member.id,
                user_id=member.user_id,
                org_id=member.org_id,
                role=member.role,
                status=member.status,
                invited_at=member.invited_at,
                accepted_at=member.accepted_at,
                invited_email=member.invited_email,
                user_name=body.email,
                user_email=body.email,
                user_avatar=None,
            ),
        }
    )


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
        raise HTTPException(400, str(exc)) from exc
    return _success({"redirect_to": f"/org/{org.slug}"})


# ── Update member role ────────────────────────────────────────────────────────


@router_api.patch("/{slug}/members/{user_id}/role")
async def update_member_role(
    slug: str,
    user_id: uuid.UUID,
    body: UpdateMemberRoleRequest,
    access: TeamManageAccess,
    db: DBSession,
):
    org, role, is_owner = access
    try:
        member = await svc.update_member_role(db, org, user_id, body.role)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _success({"role": member.role})


# ── Remove member ─────────────────────────────────────────────────────────────


@router_api.delete("/{slug}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    slug: str,
    member_id: uuid.UUID,
    access: TeamManageAccess,
    current_user: CurrentUser,
    db: DBSession,
):
    org, role, is_owner = access
    try:
        await svc.remove_member(db, org, member_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ── Resend invite ────────────────────────────────────────────────────────────


@router_api.post("/{slug}/members/{member_id}/resend-invite")
async def resend_invite(
    slug: str,
    member_id: uuid.UUID,
    access: TeamManageAccess,
    current_user: CurrentUser,
    db: DBSession,
):
    org, role, is_owner = access
    try:
        member = await svc.resend_invite(db, org, member_id, current_user)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _success({"message": f"Invite resent to {member.invited_email}."})


# ── Logo upload ───────────────────────────────────────────────────────────────

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 MB


@router_api.post("/{slug}/logo")
async def upload_logo(
    slug: str,
    access: OrgSettingsAccess,
    db: DBSession,
    logo: UploadFile = File(...),
):
    org, role, is_owner = access
    if logo.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, "Unsupported file type. Use JPEG, PNG or WebP.")
    image_bytes = await logo.read()
    if len(image_bytes) > _MAX_UPLOAD_SIZE:
        raise HTTPException(413, "Logo must be under 5 MB.")
    try:
        Image.open(BytesIO(image_bytes)).verify()
    except Exception as err:
        raise HTTPException(400, "File does not appear to be a valid image.") from err

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
