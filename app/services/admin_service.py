from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.event import Event
from app.models.organization import Organization
from app.models.ticketing import Order
from app.models.user import User


async def platform_stats(db: AsyncSession) -> dict:
    total_users = await db.scalar(
        select(func.count()).where(User.deleted_at.is_(None))
    )
    total_orgs = await db.scalar(select(func.count()).select_from(Organization))
    total_events = await db.scalar(select(func.count()).select_from(Event))
    total_revenue = await db.scalar(
        select(func.coalesce(func.sum(Order.net_amount), 0)).where(
            Order.payment_status == "paid"
        )
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
        q.order_by(Organization.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    orgs = list(rows.all())

    result = []
    for org in orgs:
        event_count = await db.scalar(
            select(func.count()).where(Event.org_id == org.id)
        )
        revenue = await db.scalar(
            select(func.coalesce(func.sum(Order.net_amount), 0))
            .join(Event, Event.id == Order.event_id)
            .where(Event.org_id == org.id, Order.payment_status == "paid")
        )
        result.append({
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
        })
    return result, total or 0


async def get_org_detail(db: AsyncSession, org_id: uuid.UUID) -> dict | None:
    org = await db.scalar(
        select(Organization)
        .where(Organization.id == org_id)
        .options(selectinload(Organization.owner))
    )
    if not org:
        return None

    events = list((await db.scalars(
        select(Event).where(Event.org_id == org.id).order_by(Event.created_at.desc()).limit(20)
    )).all())
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
    members = list((await db.scalars(
        select(OrganizationMember)
        .where(OrganizationMember.org_id == org.id, OrganizationMember.status == "active")
        .options(selectinload(OrganizationMember.user))
    )).all())

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


async def list_users(
    db: AsyncSession,
    *,
    search: str | None = None,
    role: str | None = None,
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
    if role:
        q = q.where(User.role == role)

    total = await db.scalar(select(func.count()).select_from(q.subquery()))
    rows = await db.scalars(
        q.order_by(User.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return list(rows.all()), total or 0


async def get_user_detail(db: AsyncSession, user_id: uuid.UUID) -> dict | None:
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        return None

    orgs = list((await db.scalars(
        select(Organization).where(Organization.owner_id == user_id).limit(20)
    )).all())
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
