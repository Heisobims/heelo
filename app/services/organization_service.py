from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from jose import JWTError, jwt
from slugify import slugify
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.event import Event
from app.models.organization import Organization, OrganizationMember
from app.models.payment import PaymentAccount
from app.models.user import User
from app.schemas.organization import OnboardingState, OrgCreateRequest, OrgUpdateRequest
from app.utils.email import send_team_invite_email

logger = structlog.get_logger()

_INVITE_TOKEN_TYPE = "org_invite"
_INVITE_EXPIRE_HOURS = 24


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_invite_token(org_id: uuid.UUID, invited_email: str, role: str) -> str:
    payload = {
        "type": _INVITE_TOKEN_TYPE,
        "org_id": str(org_id),
        "invited_email": invited_email.lower(),
        "role": role,
        "exp": datetime.now(UTC) + timedelta(hours=_INVITE_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_invite_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    if payload.get("type") != _INVITE_TOKEN_TYPE:
        raise ValueError("Invalid invite token type.")
    return payload


async def _unique_slug(db: AsyncSession, base: str) -> str:
    slug = base
    counter = 2
    while await db.scalar(select(Organization.id).where(Organization.slug == slug)):
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def _org_initials(name: str) -> str:
    words = name.strip().split()
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    return name[:2].upper()


# ── Organization CRUD ─────────────────────────────────────────────────────────


async def create_organization(
    db: AsyncSession,
    owner_id: uuid.UUID,
    data: OrgCreateRequest,
) -> Organization:
    base_slug = slugify(data.name, max_length=80, word_boundary=True, separator="-")
    slug = await _unique_slug(db, base_slug)
    now = datetime.now(UTC)

    org = Organization(
        owner_id=owner_id,
        name=data.name,
        slug=slug,
        country=data.country,
        currency=data.currency,
        plan="free",
        is_active=True,
    )
    db.add(org)
    await db.flush()  # get org.id without committing

    # Owner is auto-added as admin member
    member = OrganizationMember(
        org_id=org.id,
        user_id=owner_id,
        invited_email=None,
        role="admin",
        invited_by=None,
        invited_at=now,
        accepted_at=now,
        status="active",
    )
    db.add(member)

    logger.info("org.created", org_id=str(org.id), slug=slug, owner_id=str(owner_id))
    return org


async def get_organization_by_slug(db: AsyncSession, slug: str) -> Organization | None:
    return await db.scalar(
        select(Organization).where(Organization.slug == slug, Organization.is_active == True)
    )


async def get_organization_by_id(db: AsyncSession, org_id: uuid.UUID) -> Organization | None:
    return await db.scalar(
        select(Organization).where(Organization.id == org_id, Organization.is_active == True)
    )


async def update_organization(
    db: AsyncSession,
    org: Organization,
    data: OrgUpdateRequest,
) -> Organization:
    # exclude_unset (not exclude_none): the settings page always submits the
    # whole form, including explicit nulls for fields the organizer cleared -
    # exclude_none would silently ignore those clears and leave stale values.
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(org, field, value)
    logger.info("org.updated", org_id=str(org.id))
    return org


# ── Custom domain ─────────────────────────────────────────────────────────────
#
# Ownership is proven with a DNS TXT record (the same pattern Vercel/Netlify
# use) rather than by routing traffic to it - that keeps verification
# possible before DNS is even fully configured. Verifying ownership here is
# the whole of what *this application* can do: making the domain actually
# resolve to Tixdoo (CNAME/A record) and terminate TLS for it is real DNS/CDN
# infrastructure work outside this codebase - see the org settings page copy
# for the instructions an organizer needs to complete that part themselves.


async def set_custom_domain(db: AsyncSession, org: Organization, domain: str) -> Organization:
    domain = domain.strip().lower()
    existing = await db.scalar(
        select(Organization).where(Organization.custom_domain == domain, Organization.id != org.id)
    )
    if existing:
        from fastapi import HTTPException

        raise HTTPException(409, "That domain is already in use by another organization.")

    org.custom_domain = domain
    org.custom_domain_verified = False
    org.custom_domain_verification_token = secrets.token_hex(16)
    await db.commit()
    await db.refresh(org)
    logger.info("org.custom_domain_set", org_id=str(org.id), domain=domain)
    return org


async def remove_custom_domain(db: AsyncSession, org: Organization) -> Organization:
    org.custom_domain = None
    org.custom_domain_verified = False
    org.custom_domain_verification_token = None
    await db.commit()
    await db.refresh(org)
    return org


def check_custom_domain_txt_record(domain: str, expected_token: str) -> bool:
    """Best-effort synchronous DNS lookup - returns False (not "unverified
    forever") on any resolution failure, so a transient DNS hiccup just means
    "try again," not a stuck state."""
    import dns.resolver

    try:
        answers = dns.resolver.resolve(f"_tixdoo-verify.{domain}", "TXT", lifetime=5.0)
        for rdata in answers:
            value = b"".join(rdata.strings).decode("utf-8", errors="ignore")
            if value == expected_token:
                return True
        return False
    except Exception as err:
        logger.warning("org.custom_domain_dns_check_failed", domain=domain, error=str(err))
        return False


async def verify_custom_domain(db: AsyncSession, org: Organization) -> Organization:
    from fastapi import HTTPException

    if not org.custom_domain or not org.custom_domain_verification_token:
        raise HTTPException(400, "No custom domain is set for this organization.")

    ok = check_custom_domain_txt_record(org.custom_domain, org.custom_domain_verification_token)
    if not ok:
        raise HTTPException(
            400,
            f"Couldn't find the verification TXT record at "
            f"_tixdoo-verify.{org.custom_domain}. DNS changes can take a few "
            "minutes to propagate - try again shortly.",
        )

    org.custom_domain_verified = True
    await db.commit()
    await db.refresh(org)
    logger.info("org.custom_domain_verified", org_id=str(org.id), domain=org.custom_domain)
    return org


# ── SSO domain (Enterprise) ─────────────────────────────────────────────────────
#
# Domain ownership is proven the same way as custom_domain (a DNS TXT
# record), at a distinct record name so an org can independently prove
# control of a custom event domain and its corporate email domain. Once
# verified, enforcement is a separate, explicit toggle - proving ownership
# does not by itself lock out password logins for that domain.


async def set_sso_domain(db: AsyncSession, org: Organization, domain: str) -> Organization:
    domain = domain.strip().lower()
    existing = await db.scalar(
        select(Organization).where(Organization.sso_domain == domain, Organization.id != org.id)
    )
    if existing:
        from fastapi import HTTPException

        raise HTTPException(
            409, "That domain is already registered for SSO by another organization."
        )

    org.sso_domain = domain
    org.sso_domain_verified = False
    org.sso_enforced = False
    org.sso_verification_token = secrets.token_hex(16)
    await db.commit()
    await db.refresh(org)
    logger.info("org.sso_domain_set", org_id=str(org.id), domain=domain)
    return org


async def remove_sso_domain(db: AsyncSession, org: Organization) -> Organization:
    org.sso_domain = None
    org.sso_domain_verified = False
    org.sso_verification_token = None
    org.sso_enforced = False
    await db.commit()
    await db.refresh(org)
    return org


def check_sso_domain_txt_record(domain: str, expected_token: str) -> bool:
    """Same best-effort DNS lookup as check_custom_domain_txt_record, at a
    distinct record name so the two features don't collide on one domain."""
    import dns.resolver

    try:
        answers = dns.resolver.resolve(f"_tixdoo-sso-verify.{domain}", "TXT", lifetime=5.0)
        for rdata in answers:
            value = b"".join(rdata.strings).decode("utf-8", errors="ignore")
            if value == expected_token:
                return True
        return False
    except Exception as err:
        logger.warning("org.sso_domain_dns_check_failed", domain=domain, error=str(err))
        return False


async def verify_sso_domain(db: AsyncSession, org: Organization) -> Organization:
    from fastapi import HTTPException

    if not org.sso_domain or not org.sso_verification_token:
        raise HTTPException(400, "No SSO domain is set for this organization.")

    ok = check_sso_domain_txt_record(org.sso_domain, org.sso_verification_token)
    if not ok:
        raise HTTPException(
            400,
            f"Couldn't find the verification TXT record at "
            f"_tixdoo-sso-verify.{org.sso_domain}. DNS changes can take a few "
            "minutes to propagate - try again shortly.",
        )

    org.sso_domain_verified = True
    await db.commit()
    await db.refresh(org)
    logger.info("org.sso_domain_verified", org_id=str(org.id), domain=org.sso_domain)
    return org


async def set_sso_enforcement(db: AsyncSession, org: Organization, enforced: bool) -> Organization:
    from fastapi import HTTPException

    if enforced and not org.sso_domain_verified:
        raise HTTPException(400, "Verify your SSO domain before enforcing single sign-on for it.")

    org.sso_enforced = enforced
    await db.commit()
    await db.refresh(org)
    logger.info("org.sso_enforcement_set", org_id=str(org.id), enforced=enforced)
    return org


# ── User's org list ───────────────────────────────────────────────────────────


async def get_user_organizations(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[dict]:
    """Return all orgs the user owns or is an active member of, with role info."""
    # Owned orgs
    owned_result = await db.scalars(
        select(Organization).where(
            Organization.owner_id == user_id,
            Organization.is_active == True,
        )
    )
    owned = {org.id: org for org in owned_result.all()}

    # Membership orgs (active, non-owner)
    memberships_result = await db.execute(
        select(OrganizationMember, Organization)
        .join(Organization, Organization.id == OrganizationMember.org_id)
        .where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.status == "active",
            Organization.is_active == True,
        )
    )

    result: list[dict] = []
    # Owned orgs first (admin role)
    for org in owned.values():
        result.append({"org": org, "role": "admin", "is_owner": True})

    for member, org in memberships_result.all():
        if org.id not in owned:
            result.append({"org": org, "role": member.role, "is_owner": False})

    return result


# ── Membership ────────────────────────────────────────────────────────────────


async def get_org_membership(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
) -> OrganizationMember | None:
    return await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.org_id == org_id,
            OrganizationMember.user_id == user_id,
            OrganizationMember.status == "active",
        )
    )


async def get_org_members(
    db: AsyncSession,
    org_id: uuid.UUID,
) -> list[dict]:
    """Return active + pending members with user info."""
    rows = await db.execute(
        select(OrganizationMember, User)
        .outerjoin(User, User.id == OrganizationMember.user_id)
        .where(
            OrganizationMember.org_id == org_id,
            OrganizationMember.status.in_(["active", "invite_pending"]),
        )
        .order_by(OrganizationMember.created_at)
    )
    result = []
    for member, user in rows.all():
        result.append(
            {
                "member": member,
                "user": user,
                "display_name": user.full_name if user else member.invited_email,
                "display_email": user.email if user else member.invited_email,
                "display_avatar": user.avatar_url if user else None,
            }
        )
    return result


async def invite_member(
    db: AsyncSession,
    org: Organization,
    inviter: User,
    email: str,
    role: str,
) -> OrganizationMember:
    """Create pending membership + send invite email. Returns the new membership row."""
    email = email.lower().strip()

    # Check if already a member
    existing_user = await db.scalar(select(User).where(User.email == email))
    if existing_user:
        existing_member = await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.org_id == org.id,
                OrganizationMember.user_id == existing_user.id,
                OrganizationMember.status.in_(["active", "invite_pending"]),
            )
        )
        if existing_member:
            raise ValueError(
                f"{'Already a member' if existing_member.status == 'active' else 'Invite already sent'}."
            )

    # Check pending invite by email
    existing_invite = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.org_id == org.id,
            OrganizationMember.invited_email == email,
            OrganizationMember.status == "invite_pending",
        )
    )
    if existing_invite:
        raise ValueError("An invite has already been sent to that email.")

    now = datetime.now(UTC)
    member = OrganizationMember(
        org_id=org.id,
        user_id=existing_user.id if existing_user else None,
        invited_email=email,
        role=role,
        invited_by=inviter.id,
        invited_at=now,
        accepted_at=None,
        status="invite_pending",
    )
    db.add(member)
    await db.flush()

    token = _make_invite_token(org.id, email, role)
    invite_url = f"{settings.FRONTEND_URL}/accept-invite/{token}"

    try:
        await send_team_invite_email(
            email, inviter.full_name, org.name, invite_url, org.brand_color
        )
    except Exception as exc:
        logger.error("org.invite_email_failed", exc=str(exc), email=email)

    logger.info("org.member_invited", org_id=str(org.id), email=email, role=role)
    return member


async def resend_invite(
    db: AsyncSession,
    org: Organization,
    member_id: uuid.UUID,
    resender: User,
) -> OrganizationMember:
    """Re-issue a fresh invite token (new expiry window) and re-send the
    email for a still-pending invite. Raises ValueError if the membership
    row isn't a pending invite for this org."""
    member = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.id == member_id,
            OrganizationMember.org_id == org.id,
        )
    )
    if not member or member.status != "invite_pending":
        raise ValueError("No pending invite found for that member.")

    member.invited_at = datetime.now(UTC)
    member.invited_by = resender.id
    await db.flush()

    token = _make_invite_token(org.id, member.invited_email, member.role)
    invite_url = f"{settings.FRONTEND_URL}/accept-invite/{token}"

    try:
        await send_team_invite_email(
            member.invited_email, resender.full_name, org.name, invite_url, org.brand_color
        )
    except Exception as exc:
        logger.error("org.invite_resend_email_failed", exc=str(exc), email=member.invited_email)

    logger.info("org.member_invite_resent", org_id=str(org.id), email=member.invited_email)
    return member


async def accept_invite(
    db: AsyncSession,
    token: str,
    current_user: User,
) -> Organization:
    """Validate invite token and activate the membership for the current user."""
    try:
        payload = decode_invite_token(token)
    except JWTError as err:
        raise ValueError("This invite link is invalid or has expired.") from err

    org_id = uuid.UUID(payload["org_id"])
    invited_email = payload["invited_email"]
    role = payload["role"]

    if current_user.email.lower() != invited_email:
        raise ValueError(
            f"This invite was sent to {invited_email}. "
            f"You are signed in as {current_user.email}."
        )

    org = await get_organization_by_id(db, org_id)
    if not org:
        raise ValueError("Organization not found.")

    # Find the pending membership (by email or by user_id)
    member = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.org_id == org_id,
            or_(
                OrganizationMember.invited_email == invited_email,
                OrganizationMember.user_id == current_user.id,
            ),
            OrganizationMember.status == "invite_pending",
        )
    )

    if not member:
        # Might have been accepted already
        existing = await get_org_membership(db, org_id, current_user.id)
        if existing:
            return org
        raise ValueError("Invite not found. It may have already been accepted or revoked.")

    now = datetime.now(UTC)
    member.user_id = current_user.id
    member.role = role
    member.accepted_at = now
    member.status = "active"

    logger.info("org.invite_accepted", org_id=str(org_id), user_id=str(current_user.id))
    return org


async def remove_member(
    db: AsyncSession,
    org: Organization,
    member_id: uuid.UUID,
    requesting_user_id: uuid.UUID,
) -> None:
    """Remove a member (or cancel a pending invite) by its membership row id -
    not user_id, since pending invites have no user_id yet."""
    member = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.id == member_id,
            OrganizationMember.org_id == org.id,
        )
    )
    if not member:
        raise ValueError("Member not found.")
    if member.user_id and member.user_id == org.owner_id:
        raise ValueError("Cannot remove the organization owner.")

    await db.delete(member)
    await db.flush()
    logger.info("org.member_removed", org_id=str(org.id), removed=str(member_id))


async def update_member_role(
    db: AsyncSession,
    org: Organization,
    user_id: uuid.UUID,
    new_role: str,
) -> OrganizationMember:
    if user_id == org.owner_id:
        raise ValueError("Cannot change the owner's role.")

    member = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.org_id == org.id,
            OrganizationMember.user_id == user_id,
            OrganizationMember.status == "active",
        )
    )
    if not member:
        raise ValueError("Active member not found.")

    member.role = new_role
    return member


# ── Onboarding & metrics ──────────────────────────────────────────────────────


async def get_onboarding_state(db: AsyncSession, org_id: uuid.UUID) -> OnboardingState:
    event_count = (
        await db.scalar(
            select(func.count(Event.id)).where(Event.org_id == org_id, Event.deleted_at.is_(None))
        )
        or 0
    )

    payment_count = (
        await db.scalar(
            select(func.count(PaymentAccount.id)).where(PaymentAccount.org_id == org_id)
        )
        or 0
    )

    active_member_count = (
        await db.scalar(
            select(func.count(OrganizationMember.id)).where(
                OrganizationMember.org_id == org_id,
                OrganizationMember.status == "active",
            )
        )
        or 0
    )

    return OnboardingState(
        has_event=event_count > 0,
        has_payment_account=payment_count > 0,
        has_team_member=active_member_count > 1,  # owner + ≥1 more
        has_whatsapp=bool(settings.WHATSAPP_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID),
    )


async def get_org_metrics(db: AsyncSession, org_id: uuid.UUID) -> dict:
    from app.models.ticketing import REVENUE_STATUSES, Order, Registration

    total_events = (
        await db.scalar(
            select(func.count(Event.id)).where(Event.org_id == org_id, Event.deleted_at.is_(None))
        )
        or 0
    )

    total_registrations = (
        await db.scalar(
            select(func.count(Registration.id))
            .join(Event, Event.id == Registration.event_id)
            .where(
                Event.org_id == org_id,
                Registration.status.in_(["confirmed", "checked_in"]),
            )
        )
        or 0
    )

    total_revenue_row = (
        await db.scalar(
            select(func.coalesce(func.sum(Order.net_amount - Order.refunded_amount), 0))
            .join(Event, Event.id == Order.event_id)
            .where(
                Event.org_id == org_id,
                Order.payment_status.in_(REVENUE_STATUSES),
            )
        )
        or 0
    )

    return {
        "total_events": total_events,
        "total_registrations": total_registrations,
        "total_revenue": float(total_revenue_row),
    }


async def get_org_finance_summary(db: AsyncSession, org_id: uuid.UUID) -> dict:
    """Revenue totals, per-event breakdown, and recent paid orders for the Finance page."""
    from app.models.ticketing import REVENUE_STATUSES, Order

    totals_row = (
        await db.execute(
            select(
                func.coalesce(func.sum(Order.total_amount - Order.refunded_amount), 0),
                func.coalesce(func.sum(Order.net_amount - Order.refunded_amount), 0),
                func.coalesce(func.sum(Order.platform_fee), 0),
                func.count(Order.id),
            )
            .join(Event, Event.id == Order.event_id)
            .where(Event.org_id == org_id, Order.payment_status.in_(REVENUE_STATUSES))
        )
    ).one()
    gross, net, fees, paid_order_count = totals_row

    per_event_rows = (
        await db.execute(
            select(
                Event.id,
                Event.title,
                Event.slug,
                func.coalesce(func.sum(Order.net_amount - Order.refunded_amount), 0),
                func.count(Order.id),
            )
            .join(Order, Order.event_id == Event.id)
            .where(Event.org_id == org_id, Order.payment_status.in_(REVENUE_STATUSES))
            .group_by(Event.id, Event.title, Event.slug)
            .order_by(func.sum(Order.net_amount - Order.refunded_amount).desc())
        )
    ).all()
    by_event = [
        {
            "event_id": eid,
            "title": title,
            "slug": slug,
            "net_revenue": float(net_rev),
            "orders": cnt,
        }
        for eid, title, slug, net_rev, cnt in per_event_rows
    ]

    from sqlalchemy.orm import selectinload

    recent_orders_rows = (
        await db.scalars(
            select(Order)
            .join(Event, Event.id == Order.event_id)
            .where(Event.org_id == org_id, Order.payment_status.in_(REVENUE_STATUSES))
            .order_by(Order.created_at.desc())
            .limit(20)
            .options(selectinload(Order.event))
        )
    ).all()

    return {
        "gross_amount": float(gross),
        "net_amount": float(net),
        "platform_fees": float(fees),
        "paid_order_count": paid_order_count or 0,
        "by_event": by_event,
        "recent_orders": list(recent_orders_rows),
    }


async def get_recent_events(db: AsyncSession, org_id: uuid.UUID, limit: int = 5) -> list[Event]:
    result = await db.scalars(
        select(Event)
        .where(Event.org_id == org_id, Event.deleted_at.is_(None))
        .order_by(Event.created_at.desc())
        .limit(limit)
    )
    return list(result.all())
