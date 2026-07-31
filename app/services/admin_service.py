from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.event import Event
from app.models.organization import Organization
from app.models.ticketing import Order
from app.models.user import User

# Display names for the country codes users/orgs can pick — mirrors the
# select options offered in org_create.html / profile.html.
COUNTRY_NAMES = {
    "NG": "Nigeria",
    "GH": "Ghana",
    "KE": "Kenya",
    "ZA": "South Africa",
    "TZ": "Tanzania",
    "UG": "Uganda",
    "RW": "Rwanda",
    "ET": "Ethiopia",
    "CM": "Cameroon",
    "CI": "Côte d'Ivoire",
    "SN": "Senegal",
    "GB": "United Kingdom",
    "US": "United States",
    "CA": "Canada",
    "DE": "Germany",
    "FR": "France",
}

# (label, min_age, max_age) — max_age is inclusive, None means no upper bound.
AGE_BRACKETS = [
    ("Under 18", 0, 17),
    ("18-24", 18, 24),
    ("25-34", 25, 34),
    ("35-44", 35, 44),
    ("45-54", 45, 54),
    ("55+", 55, None),
]


async def platform_stats(db: AsyncSession) -> dict:
    total_users = await db.scalar(select(func.count()).where(User.deleted_at.is_(None)))
    total_orgs = await db.scalar(select(func.count()).select_from(Organization))
    total_events = await db.scalar(select(func.count()).select_from(Event))
    total_revenue = await db.scalar(
        select(func.coalesce(func.sum(Order.net_amount), 0)).where(Order.payment_status == "paid")
    )
    return {
        "total_users": total_users or 0,
        "total_orgs": total_orgs or 0,
        "total_events": total_events or 0,
        "total_net_revenue": float(total_revenue or 0),
    }


async def list_orgs(
    db: AsyncSession,
    *,
    search: str | None = None,
    is_active: bool | None = None,
    plan: str | None = None,
    page: int = 1,
    per_page: int = 30,
) -> tuple[list[dict], int]:
    q = select(Organization).options(selectinload(Organization.owner))
    if search:
        q = q.where(
            or_(
                Organization.name.ilike(f"%{search}%"),
                Organization.slug.ilike(f"%{search}%"),
            )
        )
    if is_active is not None:
        q = q.where(Organization.is_active == is_active)
    if plan:
        q = q.where(Organization.plan == plan)

    total = await db.scalar(select(func.count()).select_from(q.subquery()))
    rows = await db.scalars(
        q.order_by(Organization.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    orgs = list(rows.all())

    result = []
    for org in orgs:
        event_count = await db.scalar(select(func.count()).where(Event.org_id == org.id))
        revenue = await db.scalar(
            select(func.coalesce(func.sum(Order.net_amount), 0))
            .join(Event, Event.id == Order.event_id)
            .where(Event.org_id == org.id, Order.payment_status == "paid")
        )
        result.append(
            {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
                "plan": org.plan,
                "country": org.country or "",
                "is_active": org.is_active,
                "owner_email": org.owner.email if org.owner else "",
                "event_count": event_count or 0,
                "net_revenue": float(revenue or 0),
                "created_at": org.created_at.isoformat(),
            }
        )
    return result, total or 0


async def get_org_detail(db: AsyncSession, org_id: uuid.UUID) -> dict | None:
    org = await db.scalar(
        select(Organization)
        .where(Organization.id == org_id)
        .options(selectinload(Organization.owner))
    )
    if not org:
        return None

    events = list(
        (
            await db.scalars(
                select(Event)
                .where(Event.org_id == org.id)
                .order_by(Event.created_at.desc())
                .limit(20)
            )
        ).all()
    )
    revenue = await db.scalar(
        select(func.coalesce(func.sum(Order.net_amount), 0))
        .join(Event, Event.id == Order.event_id)
        .where(Event.org_id == org.id, Order.payment_status == "paid")
    )
    reg_count = await db.scalar(
        select(func.count())
        .select_from(Order)
        .join(Event, Event.id == Order.event_id)
        .where(Event.org_id == org.id, Order.payment_status == "paid")
    )
    from app.models.organization import OrganizationMember

    members = list(
        (
            await db.scalars(
                select(OrganizationMember)
                .where(OrganizationMember.org_id == org.id, OrganizationMember.status == "active")
                .options(selectinload(OrganizationMember.user))
            )
        ).all()
    )

    return {
        "org": org,
        "events": events,
        "members": members,
        "net_revenue": float(revenue or 0),
        "total_orders": reg_count or 0,
    }


async def suspend_org(db: AsyncSession, org_id: uuid.UUID) -> Organization:
    org = await db.scalar(select(Organization).where(Organization.id == org_id))
    if not org:
        raise ValueError("Org not found")
    org.is_active = False
    await db.commit()
    await db.refresh(org)
    return org


async def reinstate_org(db: AsyncSession, org_id: uuid.UUID) -> Organization:
    org = await db.scalar(select(Organization).where(Organization.id == org_id))
    if not org:
        raise ValueError("Org not found")
    org.is_active = True
    await db.commit()
    await db.refresh(org)
    return org


def _birth_year_range_for_bracket(bracket: str) -> tuple[int | None, int | None]:
    """Age bracket label -> (min_birth_year, max_birth_year), either end optional."""
    current_year = datetime.now(UTC).year
    for label, min_age, max_age in AGE_BRACKETS:
        if label != bracket:
            continue
        max_birth_year = current_year - min_age
        min_birth_year = (current_year - max_age) if max_age is not None else None
        return min_birth_year, max_birth_year
    return None, None


def apply_audience_filters(
    q,
    *,
    country: str | None = None,
    age_bracket: str | None = None,
    interest: str | None = None,
    vibe: str | None = None,
):
    """Filter a User query by the audience-insight dimensions: region, age, interest, event vibe."""
    from app.models.community import AttendeeProfile
    from app.models.ticketing import Registration

    if country:
        q = q.where(User.country == country)
    if age_bracket:
        min_birth_year, max_birth_year = _birth_year_range_for_bracket(age_bracket)
        if min_birth_year is not None:
            q = q.where(User.birth_year >= min_birth_year)
        if max_birth_year is not None:
            q = q.where(User.birth_year <= max_birth_year)
    if interest:
        q = q.join(AttendeeProfile, AttendeeProfile.user_id == User.id).where(
            AttendeeProfile.interests.any(interest)
        )
    if vibe:
        q = (
            q.join(Registration, Registration.user_id == User.id)
            .join(Event, Event.id == Registration.event_id)
            .where(Registration.status == "confirmed", Event.vibe_tags.any(vibe))
            .distinct()
        )
    return q


async def audience_insights(db: AsyncSession) -> dict:
    """Aggregate audience data — region, age, interests, event vibes — for admin insights."""
    current_year = datetime.now(UTC).year

    total_users = await db.scalar(select(func.count()).where(User.deleted_at.is_(None))) or 0
    users_with_country = (
        await db.scalar(
            select(func.count()).where(User.deleted_at.is_(None), User.country.is_not(None))
        )
        or 0
    )
    users_with_birth_year = (
        await db.scalar(
            select(func.count()).where(User.deleted_at.is_(None), User.birth_year.is_not(None))
        )
        or 0
    )

    country_rows = (
        await db.execute(
            select(User.country, func.count().label("cnt"))
            .where(User.deleted_at.is_(None), User.country.is_not(None))
            .group_by(User.country)
            .order_by(func.count().desc())
            .limit(15)
        )
    ).all()
    top_countries = [
        {"code": code, "name": COUNTRY_NAMES.get(code, code), "count": cnt}
        for code, cnt in country_rows
    ]

    age_expr = current_year - User.birth_year
    whens = [
        (age_expr.between(min_age, max_age), label)
        if max_age is not None
        else (age_expr >= min_age, label)
        for label, min_age, max_age in AGE_BRACKETS
    ]
    bracket_case = case(*whens)
    bracket_rows = (
        await db.execute(
            select(bracket_case.label("bracket"), func.count().label("cnt"))
            .where(User.deleted_at.is_(None), User.birth_year.is_not(None))
            .group_by(bracket_case)
        )
    ).all()
    bracket_counts = dict(bracket_rows)
    age_brackets = [
        {"label": label, "count": bracket_counts.get(label, 0)} for label, _, _ in AGE_BRACKETS
    ]

    interest_rows = (
        await db.execute(
            text(
                """
                SELECT interest, count(*) AS cnt
                FROM attendee_profiles ap
                JOIN users u ON u.id = ap.user_id AND u.deleted_at IS NULL
                CROSS JOIN LATERAL unnest(ap.interests) AS interest
                GROUP BY interest
                ORDER BY cnt DESC
                LIMIT 15
                """
            )
        )
    ).all()
    top_interests = [{"interest": interest, "count": cnt} for interest, cnt in interest_rows]

    vibe_rows = (
        await db.execute(
            text(
                """
                SELECT vibe, count(*) AS cnt
                FROM registrations r
                JOIN events e ON e.id = r.event_id
                CROSS JOIN LATERAL unnest(e.vibe_tags) AS vibe
                WHERE r.status = 'confirmed'
                GROUP BY vibe
                ORDER BY cnt DESC
                LIMIT 15
                """
            )
        )
    ).all()
    top_vibes = [{"vibe": vibe, "count": cnt} for vibe, cnt in vibe_rows]

    return {
        "total_users": total_users,
        "users_with_country": users_with_country,
        "users_with_birth_year": users_with_birth_year,
        "top_countries": top_countries,
        "age_brackets": age_brackets,
        "top_interests": top_interests,
        "top_vibes": top_vibes,
    }


def apply_category_filter(q, category: str | None):
    """
    Category is a broader, more useful grouping than raw `role` for admin
    purposes: 'organizer'/'attendee' include role='both' (they're genuinely
    both), and 'vendor' is a separate profile any user can have — not a role
    value at all — so it requires a join instead of a simple equality check.
    """
    from app.models.vendor import Vendor

    if category == "organizer":
        return q.where(User.role.in_(["organizer", "both"]))
    if category == "attendee":
        return q.where(User.role.in_(["attendee", "both"]))
    if category == "admin":
        return q.where(User.role == "admin")
    if category == "vendor":
        return q.join(Vendor, Vendor.user_id == User.id)
    return q


async def list_users(
    db: AsyncSession,
    *,
    search: str | None = None,
    category: str | None = None,
    country: str | None = None,
    age_bracket: str | None = None,
    interest: str | None = None,
    vibe: str | None = None,
    page: int = 1,
    per_page: int = 30,
) -> tuple[list[User], int]:
    q = select(User).where(User.deleted_at.is_(None))
    if search:
        q = q.where(
            or_(
                User.email.ilike(f"%{search}%"),
                User.full_name.ilike(f"%{search}%"),
            )
        )
    q = apply_category_filter(q, category)
    q = apply_audience_filters(
        q, country=country, age_bracket=age_bracket, interest=interest, vibe=vibe
    )

    total = await db.scalar(select(func.count()).select_from(q.subquery()))
    rows = await db.scalars(
        q.order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    return list(rows.all()), total or 0


async def get_user_category_counts(db: AsyncSession) -> dict[str, int]:
    from app.models.vendor import Vendor

    base = select(func.count()).select_from(User).where(User.deleted_at.is_(None))
    all_count = await db.scalar(base)
    organizer = await db.scalar(base.where(User.role.in_(["organizer", "both"])))
    attendee = await db.scalar(base.where(User.role.in_(["attendee", "both"])))
    admin_count = await db.scalar(base.where(User.role == "admin"))
    vendor = await db.scalar(
        select(func.count())
        .select_from(User)
        .join(Vendor, Vendor.user_id == User.id)
        .where(User.deleted_at.is_(None))
    )
    return {
        "all": all_count or 0,
        "organizer": organizer or 0,
        "attendee": attendee or 0,
        "vendor": vendor or 0,
        "admin": admin_count or 0,
    }


async def batch_vendor_user_ids(db: AsyncSession, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Which of these users also have a vendor profile — for a badge in list views."""
    if not user_ids:
        return set()
    from app.models.vendor import Vendor

    rows = await db.scalars(select(Vendor.user_id).where(Vendor.user_id.in_(user_ids)))
    return set(rows.all())


async def get_user_detail(db: AsyncSession, user_id: uuid.UUID) -> dict | None:
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        return None

    orgs = list(
        (
            await db.scalars(select(Organization).where(Organization.owner_id == user_id).limit(20))
        ).all()
    )
    from app.models.ticketing import Registration

    reg_count = await db.scalar(
        select(func.count()).where(
            Registration.attendee_email == user.email,
            Registration.status == "confirmed",
        )
    )
    return {
        "user": user,
        "owned_orgs": orgs,
        "confirmed_registration_count": reg_count or 0,
    }


async def ban_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise ValueError("User not found")
    user.deleted_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(user)
    return user


async def unban_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise ValueError("User not found")
    user.deleted_at = None
    await db.commit()
    await db.refresh(user)
    return user


async def set_user_role(db: AsyncSession, user_id: uuid.UUID, role: str) -> User:
    allowed = {"attendee", "organizer", "both", "admin"}
    if role not in allowed:
        raise ValueError(f"Invalid role: {role}")
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise ValueError("User not found")
    user.role = role
    await db.commit()
    await db.refresh(user)
    return user


async def set_org_plan(db: AsyncSession, org_id: uuid.UUID, plan: str) -> Organization:
    allowed = {"starter", "growth", "pro", "enterprise"}
    if plan not in allowed:
        raise ValueError(f"Invalid plan: {plan}")
    org = await db.scalar(select(Organization).where(Organization.id == org_id))
    if not org:
        raise ValueError("Org not found")
    org.plan = plan
    await db.commit()
    await db.refresh(org)
    return org
