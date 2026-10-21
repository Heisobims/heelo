from __future__ import annotations

import math
import uuid
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db

# ── DB session shorthand ──────────────────────────────────────────────────────
DBSession = Annotated[AsyncSession, Depends(get_db)]


# ── JWT token extraction - header OR httpOnly cookie ─────────────────────────
async def _resolve_token(
    authorization: str | None = Header(default=None),
    heelo_access: str | None = Cookie(default=None),
) -> str:
    """
    Accepts JWT from:
      1. `Authorization: Bearer <token>` header  (API clients)
      2. `heelo_access` httpOnly cookie          (browser / HTMX clients)
    """
    if authorization and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ").strip()
    if heelo_access:
        return heelo_access
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated.")


async def get_current_user_id(token: str = Depends(_resolve_token)) -> str:
    """Decode JWT and return the user's UUID string."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
        return user_id
    except JWTError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token."
        ) from err


CurrentUserID = Annotated[str, Depends(get_current_user_id)]


# ── Full user object ───────────────────────────────────────────────────────────
async def get_current_user(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    from app.models.user import User

    user = await db.scalar(select(User).where(User.id == uuid.UUID(user_id)))
    if not user or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")
    return user


CurrentUser = Annotated[object, Depends(get_current_user)]


# ── Org membership check ──────────────────────────────────────────────────────
async def _get_org_and_member(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Reads the `slug` path param, loads the org, and verifies membership.
    Returns (org, membership_role, is_owner).
    """
    from app.models.organization import Organization, OrganizationMember

    slug = request.path_params.get("slug")
    org = await db.scalar(
        select(Organization).where(
            Organization.slug == slug,
            Organization.is_active == True,
        )
    )
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found.")

    is_owner = str(org.owner_id) == str(current_user.id)
    if is_owner:
        return org, "admin", True

    member = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.org_id == org.id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
    )
    if not member:
        raise HTTPException(status_code=403, detail="Access denied.")

    return org, member.role, False


OrgAccess = Annotated[tuple, Depends(_get_org_and_member)]


# ── API key auth (for public API) ────────────────────────────────────────────
async def require_api_key(
    x_api_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Validates X-API-Key header, returns the authenticated ApiKey record."""
    from app.services import api_key_service as ak_svc

    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header.")
    key = await ak_svc.authenticate_api_key(db, x_api_key)
    if not key:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key.")
    return key


APIKeyAuth = Annotated[object, Depends(require_api_key)]


# ── Pagination ────────────────────────────────────────────────────────────────
class PaginationParams:
    def __init__(self, page: int = 1, per_page: int = 20) -> None:
        if page < 1:
            raise HTTPException(status_code=400, detail="page must be >= 1")
        if per_page < 1 or per_page > 100:
            raise HTTPException(status_code=400, detail="per_page must be between 1 and 100")
        self.page = page
        self.per_page = per_page

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page

    def meta(self, total: int) -> dict:
        return {
            "total": total,
            "page": self.page,
            "per_page": self.per_page,
            "total_pages": math.ceil(total / self.per_page) if total else 0,
        }


Pagination = Annotated[PaginationParams, Depends(PaginationParams)]
