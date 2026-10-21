"""
Centralized subscription-tier limits and feature gates for `Organization.plan`.

Mirrors app/permissions.py's role-matrix pattern, but for the four
subscription tiers (free | growth | pro | enterprise) instead of team roles.
Two kinds of gates:
  - Feature flags (has_feature / require_feature) - a capability is simply on
    or off for a plan.
  - Usage limits (PlanLimits) - either a live COUNT check against an existing
    table (seats, orgs, promo codes, webhooks, API keys, custom domains) or a
    Redis-backed monthly counter (WhatsApp messages, AI generations). Redis
    checks fail OPEN if Redis is unreachable - same graceful-fallback
    convention already used for login rate limiting and reminder dedup
    elsewhere in this codebase, so a Redis outage never blocks a paying
    customer from using the product.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

import structlog
from fastapi import HTTPException

from app.config import settings

logger = structlog.get_logger()

PLAN_ORDER = ["free", "growth", "pro", "enterprise"]
_DEFAULT_PLAN = "free"


class PlanFeature(str, Enum):
    CUSTOM_BRANDING = "custom_branding"
    RECURRING_EVENTS = "recurring_events"
    CRM_IMPORT = "crm_import"
    CUSTOM_FORM_FIELDS = "custom_form_fields"
    SPEAKERS_AGENDA = "speakers_agenda"
    SPONSORS = "sponsors"
    LIVE_ENGAGEMENT = "live_engagement"
    ADVANCED_ANALYTICS = "advanced_analytics"
    POST_EVENT_FEEDBACK = "post_event_feedback"
    CUSTOM_DOMAIN = "custom_domain"
    SSO = "sso"
    FULL_WHITE_LABEL = "full_white_label"


@dataclass(frozen=True)
class PlanLimits:
    max_seats: int | None  # None = unlimited. Counted as team members + the owner.
    max_orgs: int | None  # orgs a single user may own
    max_active_promo_codes: int | None
    max_webhook_subscriptions: int
    max_api_keys: int
    max_custom_domains: int
    whatsapp_messages_per_month: int | None
    ai_generations_per_month: int | None


_LIMITS: dict[str, PlanLimits] = {
    "free": PlanLimits(
        max_seats=1,
        max_orgs=1,
        max_active_promo_codes=1,
        max_webhook_subscriptions=0,
        max_api_keys=0,
        max_custom_domains=0,
        whatsapp_messages_per_month=100,
        ai_generations_per_month=5,
    ),
    "growth": PlanLimits(
        max_seats=3,
        max_orgs=3,
        max_active_promo_codes=None,
        max_webhook_subscriptions=3,
        max_api_keys=1,
        max_custom_domains=0,
        whatsapp_messages_per_month=1000,
        ai_generations_per_month=50,
    ),
    "pro": PlanLimits(
        max_seats=10,
        max_orgs=10,
        max_active_promo_codes=None,
        max_webhook_subscriptions=10,
        max_api_keys=5,
        max_custom_domains=1,
        whatsapp_messages_per_month=5000,
        ai_generations_per_month=250,
    ),
    "enterprise": PlanLimits(
        max_seats=None,
        max_orgs=None,
        max_active_promo_codes=None,
        max_webhook_subscriptions=10_000,
        max_api_keys=10_000,
        max_custom_domains=10,
        whatsapp_messages_per_month=None,
        ai_generations_per_month=None,
    ),
}

_growth_features = {
    PlanFeature.CUSTOM_BRANDING,
    PlanFeature.RECURRING_EVENTS,
    PlanFeature.CRM_IMPORT,
    PlanFeature.CUSTOM_FORM_FIELDS,
    PlanFeature.SPEAKERS_AGENDA,
}
_pro_features = _growth_features | {
    PlanFeature.SPONSORS,
    PlanFeature.LIVE_ENGAGEMENT,
    PlanFeature.ADVANCED_ANALYTICS,
    PlanFeature.POST_EVENT_FEEDBACK,
    PlanFeature.CUSTOM_DOMAIN,
}
_enterprise_features = _pro_features | {PlanFeature.SSO, PlanFeature.FULL_WHITE_LABEL}

_FEATURES: dict[str, set[PlanFeature]] = {
    "free": set(),
    "growth": _growth_features,
    "pro": _pro_features,
    "enterprise": _enterprise_features,
}

_UPGRADE_HINT = {
    "growth": "Upgrade to Growth to unlock this.",
    "pro": "Upgrade to Pro to unlock this.",
    "enterprise": "This is available on Enterprise. Contact sales to unlock it.",
}


def get_limits(plan: str) -> PlanLimits:
    return _LIMITS.get(plan, _LIMITS[_DEFAULT_PLAN])


def has_feature(plan: str, feature: PlanFeature) -> bool:
    return feature in _FEATURES.get(plan, set())


def _plan_that_unlocks(feature: PlanFeature) -> str:
    for plan in PLAN_ORDER:
        if has_feature(plan, feature):
            return plan
    return "enterprise"


def require_feature(plan: str, feature: PlanFeature) -> None:
    if has_feature(plan, feature):
        return
    unlocking_plan = _plan_that_unlocks(feature)
    raise HTTPException(
        402,
        f"This feature isn't available on your current plan. "
        f"{_UPGRADE_HINT.get(unlocking_plan, 'Upgrade to unlock this.')}",
    )


# ── Live COUNT-based limits ─────────────────────────────────────────────────


async def check_seat_limit(db, org) -> None:
    """Call before creating a new active membership or pending invite."""
    from sqlalchemy import func, select

    from app.models.organization import OrganizationMember

    limits = get_limits(org.plan)
    if limits.max_seats is None:
        return
    count = await db.scalar(
        select(func.count()).where(
            OrganizationMember.org_id == org.id,
            OrganizationMember.status.in_(["active", "invite_pending"]),
        )
    )
    # +1 for the owner, who has no membership row of their own.
    if (count or 0) + 1 >= limits.max_seats:
        raise HTTPException(
            402,
            f"Your plan allows up to {limits.max_seats} seat(s) (including the owner). "
            "Remove a team member or upgrade to invite more.",
        )


async def highest_owned_plan(db, user_id: uuid.UUID) -> str:
    """The most-privileged plan among orgs this user already owns - used as a
    proxy for "their plan" when creating a brand-new org, which has no plan
    history of its own yet."""
    from sqlalchemy import select

    from app.models.organization import Organization

    rows = await db.scalars(select(Organization.plan).where(Organization.owner_id == user_id))
    owned_plans = list(rows.all())
    if not owned_plans:
        return _DEFAULT_PLAN
    return max(owned_plans, key=lambda p: PLAN_ORDER.index(p) if p in PLAN_ORDER else 0)


async def check_org_limit(db, user_id: uuid.UUID) -> None:
    """Call before creating a new organization."""
    from sqlalchemy import func, select

    from app.models.organization import Organization

    plan = await highest_owned_plan(db, user_id)
    limits = get_limits(plan)
    if limits.max_orgs is None:
        return
    count = await db.scalar(select(func.count()).where(Organization.owner_id == user_id))
    if (count or 0) >= limits.max_orgs:
        raise HTTPException(
            402,
            f"Your plan allows owning up to {limits.max_orgs} organization(s). "
            "Upgrade to create another.",
        )


async def check_active_promo_code_limit(
    db, org_id: uuid.UUID, event_id: uuid.UUID, plan: str
) -> None:
    from sqlalchemy import func, select

    from app.models.ticketing import PromoCode

    limits = get_limits(plan)
    if limits.max_active_promo_codes is None:
        return
    count = await db.scalar(
        select(func.count()).where(
            PromoCode.event_id == event_id,
            PromoCode.is_active.is_(True),
        )
    )
    if (count or 0) >= limits.max_active_promo_codes:
        raise HTTPException(
            402,
            f"Your plan allows up to {limits.max_active_promo_codes} active promo "
            "code(s) per event. Deactivate one or upgrade to add more.",
        )


def check_webhook_limit(current_count: int, plan: str) -> None:
    limits = get_limits(plan)
    if current_count >= limits.max_webhook_subscriptions:
        if limits.max_webhook_subscriptions == 0:
            raise HTTPException(402, "Webhooks aren't available on your plan. Upgrade to use them.")
        raise HTTPException(
            402,
            f"Your plan allows up to {limits.max_webhook_subscriptions} webhook "
            "subscription(s). Remove one or upgrade to add more.",
        )


def check_api_key_limit(current_count: int, plan: str) -> None:
    limits = get_limits(plan)
    if current_count >= limits.max_api_keys:
        if limits.max_api_keys == 0:
            raise HTTPException(402, "API access isn't available on your plan. Upgrade to use it.")
        raise HTTPException(
            402,
            f"Your plan allows up to {limits.max_api_keys} active API key(s). "
            "Revoke one or upgrade to add more.",
        )


def check_custom_domain_limit(current_count: int, plan: str) -> None:
    limits = get_limits(plan)
    if current_count >= limits.max_custom_domains:
        if limits.max_custom_domains == 0:
            raise HTTPException(
                402, "Custom domains aren't available on your plan. Upgrade to Pro to use one."
            )
        raise HTTPException(
            402,
            f"Your plan allows up to {limits.max_custom_domains} custom domain(s). "
            "Upgrade for more.",
        )


# ── Redis-backed monthly usage quotas ───────────────────────────────────────


def _quota_redis():
    try:
        from redis import Redis as _Redis

        return _Redis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception:
        return None


def _quota_key(metric: str, org_id: uuid.UUID) -> str:
    return f"plan_quota:{metric}:{org_id}:{datetime.now(UTC):%Y-%m}"


def _check_and_consume_quota(
    org_id: uuid.UUID, metric: str, limit: int | None, amount: int, label: str
) -> None:
    """Raises 402 if consuming `amount` units of `metric` this month would put
    the org over `limit`. Fails open (allows it) if Redis is unreachable or
    the plan has no limit for this metric - mirrors the login-rate-limiter
    convention in app/services/auth_service.py."""
    if limit is None:
        return
    redis = _quota_redis()
    if not redis:
        return
    key = _quota_key(metric, org_id)
    try:
        current = int(redis.get(key) or 0)
        if current + amount > limit:
            raise HTTPException(
                402,
                f"Your plan's monthly {label} limit ({limit}/mo) has been reached. "
                "Upgrade to send more this month.",
            )
        redis.incrby(key, amount)
        # ~40 days - comfortably past month-end regardless of when it started
        redis.expire(key, 40 * 24 * 3600)
    except HTTPException:
        raise
    except Exception as err:
        logger.warning(
            "plans.quota_check_failed", metric=metric, org_id=str(org_id), error=str(err)
        )


def check_and_consume_whatsapp_quota(org_id: uuid.UUID, plan: str, count: int = 1) -> None:
    limits = get_limits(plan)
    _check_and_consume_quota(
        org_id, "whatsapp", limits.whatsapp_messages_per_month, count, "WhatsApp message"
    )


def check_and_consume_ai_quota(org_id: uuid.UUID, plan: str, count: int = 1) -> None:
    limits = get_limits(plan)
    _check_and_consume_quota(org_id, "ai", limits.ai_generations_per_month, count, "AI generation")


def get_quota_usage(org_id: uuid.UUID, metric: str) -> int:
    """Read-only - for displaying current usage in the dashboard."""
    redis = _quota_redis()
    if not redis:
        return 0
    try:
        return int(redis.get(_quota_key(metric, org_id)) or 0)
    except Exception:
        return 0
