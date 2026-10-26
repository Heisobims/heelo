"""
Centralized per-org team-role permission matrix.

Two separate role systems exist in this codebase - don't confuse them:
  - `User.role`      - platform-level account type: attendee | organizer | admin
                        (checked directly in app/routers/admin.py / admin_pages.py
                        for platform-staff-only routes; out of scope here.)
  - `OrganizationMember.role` - per-org team role: admin | organizer | finance |
                        checkin_staff. THIS is what this module governs: what a
                        given team role is allowed to do within one organization.

Before this module, every router did its own inline
`if role not in ("admin", "organizer"): raise HTTPException(403, ...)` check -
duplicated ~45 times across a dozen files, inconsistent, and two of the four
roles ("finance", "checkin_staff") were either checked in exactly one place or
never checked at all despite existing in the schema and the team-management UI.
"""

from __future__ import annotations

from enum import Enum

from fastapi import HTTPException

from app.dependencies import OrgAccess


class Permission(str, Enum):
    # ── Admin-only (owner or "admin" team role) ─────────────────────────────
    ORG_SETTINGS_EDIT = "org.settings_edit"  # update org, upload logo
    TEAM_MANAGE = "team.manage"  # invite/remove members, change roles
    PAYMENT_ACCOUNTS_MANAGE = "payment_accounts.manage"  # connect/remove payout accounts
    API_KEYS_MANAGE = "api_keys.manage"
    WEBHOOKS_MANAGE = "webhooks.manage"
    EVENTS_DELETE = "events.delete"

    # ── Operational (admin + organizer) ─────────────────────────────────────
    EVENTS_MANAGE = "events.manage"  # create/edit/publish/cancel/duplicate/etc
    TICKETING_MANAGE = "ticketing.manage"  # ticket types, form fields, promo codes
    REGISTRATIONS_MANAGE = "registrations.manage"  # cancel/refund a registration
    CAMPAIGNS_MANAGE = "campaigns.manage"
    INBOX_REPLY = "inbox.reply"
    CRM_MANAGE = "crm.manage"
    AI_USE = "ai.use"
    SPEAKERS_MANAGE = "speakers.manage"
    SPONSORS_MANAGE = "sponsors.manage"
    AGENDA_MANAGE = "agenda.manage"
    OPEN_CALLS_MANAGE = "open_calls.manage"
    LIVE_ENGAGEMENT_MANAGE = "live_engagement.manage"  # polls + Q&A moderation

    # ── Finance (admin + organizer + finance) ───────────────────────────────
    FINANCE_VIEW = "finance.view"

    # ── Check-in (admin + organizer + checkin_staff) ────────────────────────
    CHECKIN_SCAN = "checkin.scan"
    CHECKIN_UNDO = "checkin.undo"


ROLE_PERMISSIONS: dict[str, set[Permission]] = {
    "admin": set(Permission),
    "organizer": {
        Permission.EVENTS_MANAGE,
        Permission.TICKETING_MANAGE,
        Permission.REGISTRATIONS_MANAGE,
        Permission.CAMPAIGNS_MANAGE,
        Permission.INBOX_REPLY,
        Permission.CRM_MANAGE,
        Permission.AI_USE,
        Permission.SPEAKERS_MANAGE,
        Permission.SPONSORS_MANAGE,
        Permission.AGENDA_MANAGE,
        Permission.OPEN_CALLS_MANAGE,
        Permission.LIVE_ENGAGEMENT_MANAGE,
        Permission.FINANCE_VIEW,
        Permission.CHECKIN_SCAN,
        Permission.CHECKIN_UNDO,
    },
    "finance": {
        Permission.FINANCE_VIEW,
    },
    "checkin_staff": {
        Permission.CHECKIN_SCAN,
        Permission.CHECKIN_UNDO,
    },
}


def has_permission(role: str, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())


def require_permission(permission: Permission):
    """
    FastAPI dependency factory for JSON API routers. Wraps OrgAccess and enforces
    a specific permission, returning the same (org, role, is_owner) tuple so
    route bodies don't need to change beyond the Annotated type:

        access: Annotated[tuple, Depends(require_permission(Permission.EVENTS_MANAGE))]
    """

    async def _check(org_access: OrgAccess) -> tuple:
        org, role, is_owner = org_access
        if not has_permission(role, permission):
            raise HTTPException(403, "Insufficient permissions.")
        return org, role, is_owner

    return _check


def require_page_permission(permission: Permission, role: str, org) -> None:
    """
    For HTML page routes (app/routers/pages.py), which resolve auth via
    `_org_page_ctx` - a plain function call, not a FastAPI dependency - rather
    than OrgAccess. Raises 403 the same way the API dependency does.
    """
    if not org or not has_permission(role, permission):
        raise HTTPException(403, "Access denied.")


__all__ = [
    "Permission",
    "ROLE_PERMISSIONS",
    "has_permission",
    "require_permission",
    "require_page_permission",
]
