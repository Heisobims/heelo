from __future__ import annotations

import re
import uuid

from fastapi import HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.vendor import Vendor, VendorLead, VENDOR_CATEGORIES


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_-]+", "-", slug).strip("-")
    return slug[:190]


async def _unique_slug(db: AsyncSession, base: str) -> str:
    slug = base
    n = 1
    while await db.scalar(select(Vendor).where(Vendor.slug == slug)):
        slug = f"{base}-{n}"
        n += 1
    return slug


async def get_vendor_by_user(db: AsyncSession, user_id: uuid.UUID) -> Vendor | None:
    return await db.scalar(select(Vendor).where(Vendor.user_id == user_id))


async def get_vendor_by_slug(db: AsyncSession, slug: str) -> Vendor | None:
    return await db.scalar(select(Vendor).where(Vendor.slug == slug))


async def create_vendor(
    db: AsyncSession,
    user_id: uuid.UUID,
    business_name: str,
    category: str,
    description: str | None,
    tagline: str | None,
    location_city: str | None,
    location_country: str | None,
    contact_email: str | None,
    contact_phone: str | None,
    website_url: str | None,
    price_range: str | None,
) -> Vendor:
    if category not in VENDOR_CATEGORIES:
        raise HTTPException(400, f"Invalid category. Choose from: {', '.join(VENDOR_CATEGORIES)}")

    existing = await get_vendor_by_user(db, user_id)
    if existing:
        raise HTTPException(409, "You already have a vendor profile.")

    base_slug = _slugify(business_name) or "vendor"
    slug = await _unique_slug(db, base_slug)

    vendor = Vendor(
        user_id=user_id,
        business_name=business_name,
        slug=slug,
        category=category,
        description=description,
        tagline=tagline,
        location_city=location_city,
        location_country=location_country,
        contact_email=contact_email,
        contact_phone=contact_phone,
        website_url=website_url,
        price_range=price_range,
        status="active",
    )
    db.add(vendor)
    await db.commit()
    await db.refresh(vendor)
    return vendor


async def update_vendor(
    db: AsyncSession,
    vendor: Vendor,
    **fields,
) -> Vendor:
    for k, v in fields.items():
        if hasattr(vendor, k) and v is not None:
            setattr(vendor, k, v)
    await db.commit()
    await db.refresh(vendor)
    return vendor


async def list_vendors(
    db: AsyncSession,
    *,
    q: str | None = None,
    category: str | None = None,
    city: str | None = None,
    country: str | None = None,
    price_range: str | None = None,
    page: int = 1,
    per_page: int = 24,
) -> tuple[list[Vendor], int]:
    stmt = select(Vendor).where(Vendor.status == "active")

    if q:
        stmt = stmt.where(
            or_(
                Vendor.business_name.ilike(f"%{q}%"),
                Vendor.description.ilike(f"%{q}%"),
                Vendor.tagline.ilike(f"%{q}%"),
            )
        )
    if category:
        stmt = stmt.where(Vendor.category == category)
    if city:
        stmt = stmt.where(Vendor.location_city.ilike(f"%{city}%"))
    if country:
        stmt = stmt.where(Vendor.location_country == country.upper())
    if price_range:
        stmt = stmt.where(Vendor.price_range == price_range)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    result = await db.scalars(
        stmt.order_by(Vendor.is_verified.desc(), Vendor.lead_count.desc(), Vendor.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return list(result.all()), total


async def create_lead(
    db: AsyncSession,
    vendor: Vendor,
    *,
    org_id: uuid.UUID | None,
    requester_name: str,
    requester_email: str,
    event_name: str | None,
    message: str | None,
) -> VendorLead:
    lead = VendorLead(
        vendor_id=vendor.id,
        org_id=org_id,
        requester_name=requester_name,
        requester_email=requester_email,
        event_name=event_name,
        message=message,
        status="new",
    )
    db.add(lead)
    await db.execute(
        update(Vendor).where(Vendor.id == vendor.id).values(lead_count=Vendor.lead_count + 1)
    )
    await db.commit()
    await db.refresh(lead)
    return lead


async def get_vendor_leads(
    db: AsyncSession,
    vendor_id: uuid.UUID,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[VendorLead], int]:
    stmt = select(VendorLead).where(VendorLead.vendor_id == vendor_id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    result = await db.scalars(
        stmt.order_by(VendorLead.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return list(result.all()), total
