from __future__ import annotations

import re
import uuid

from fastapi import HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vendor import (
    VENDOR_CATEGORIES,
    BoothApplication,
    EventBoothPackage,
    Vendor,
    VendorBooking,
    VendorFeaturedCampaign,
    VendorLead,
    VendorLeadCreditPurchase,
    VendorPayout,
    VendorQuotation,
    VendorQuoteRecipient,
    VendorQuoteRequest,
    VendorReview,
    VendorServiceListing,
    VendorSubscription,
    VendorTransaction,
    VendorVerificationRequest,
)


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
    from sqlalchemy.orm import selectinload

    return await db.scalar(
        select(Vendor).where(Vendor.slug == slug).options(selectinload(Vendor.user))
    )


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
    cover_image_url: str,
    address: str | None = None,
    capacity: int | None = None,
    portfolio_urls: list[str] | None = None,
    portfolio_link: str | None = None,
    currency: str | None = None,
    starting_price: float | None = None,
) -> Vendor:
    if category not in VENDOR_CATEGORIES:
        raise HTTPException(400, f"Invalid category. Choose from: {', '.join(VENDOR_CATEGORIES)}")

    existing = await get_vendor_by_user(db, user_id)
    if existing:
        raise HTTPException(409, "You already have a vendor profile.")

    base_slug = _slugify(business_name) or "vendor"
    slug = await _unique_slug(db, base_slug)

    vendor_currency = (currency or "").strip().upper()
    if not vendor_currency or vendor_currency == "NGN":
        if location_country:
            from app.utils.currency import country_to_currency
            vendor_currency = country_to_currency(location_country, default=vendor_currency or "USD")
        elif not vendor_currency:
            vendor_currency = "USD"

    vendor = Vendor(
        user_id=user_id,
        business_name=business_name,
        slug=slug,
        category=category,
        description=description,
        tagline=tagline,
        location_city=location_city,
        location_country=location_country,
        address=address,
        capacity=capacity,
        contact_email=contact_email,
        contact_phone=contact_phone,
        website_url=website_url,
        price_range=price_range,
        cover_image_url=cover_image_url,
        portfolio_urls=portfolio_urls,
        portfolio_link=portfolio_link,
        currency=vendor_currency,
        starting_price=starting_price,
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
    min_capacity: int | None = None,
    max_capacity: int | None = None,
    venue_type: str | None = None,
    verified_only: bool = False,
    sort_by: str | None = None,
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
                Vendor.address.ilike(f"%{q}%"),
                Vendor.location_city.ilike(f"%{q}%"),
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
    if min_capacity:
        stmt = stmt.where(Vendor.capacity.is_not(None), Vendor.capacity >= min_capacity)
    if max_capacity:
        stmt = stmt.where(Vendor.capacity.is_not(None), Vendor.capacity <= max_capacity)
    if verified_only:
        stmt = stmt.where(Vendor.is_verified.is_(True))

    if venue_type:
        vt = venue_type.lower().strip()
        if vt == "ballroom":
            stmt = stmt.where(
                or_(
                    Vendor.business_name.ilike("%ballroom%"),
                    Vendor.description.ilike("%ballroom%"),
                    Vendor.tagline.ilike("%ballroom%"),
                )
            )
        elif vt == "convention":
            stmt = stmt.where(
                or_(
                    Vendor.business_name.ilike("%convention%"),
                    Vendor.business_name.ilike("%dome%"),
                    Vendor.business_name.ilike("%arena%"),
                    Vendor.business_name.ilike("%rotunda%"),
                    Vendor.business_name.ilike("%hall%"),
                    Vendor.description.ilike("%convention%"),
                )
            )
        elif vt == "historic":
            stmt = stmt.where(
                or_(
                    Vendor.business_name.ilike("%historic%"),
                    Vendor.business_name.ilike("%palace%"),
                    Vendor.business_name.ilike("%castle%"),
                    Vendor.business_name.ilike("%palazzo%"),
                    Vendor.business_name.ilike("%hofburg%"),
                    Vendor.business_name.ilike("%heritage%"),
                    Vendor.description.ilike("%historic%"),
                    Vendor.description.ilike("%renaissance%"),
                    Vendor.description.ilike("%victorian%"),
                )
            )
        elif vt in ("rooftop", "skyline"):
            stmt = stmt.where(
                or_(
                    Vendor.business_name.ilike("%rooftop%"),
                    Vendor.business_name.ilike("%skyline%"),
                    Vendor.business_name.ilike("%penthouse%"),
                    Vendor.business_name.ilike("%terrace%"),
                    Vendor.tagline.ilike("%skyline%"),
                    Vendor.tagline.ilike("%terrace%"),
                    Vendor.description.ilike("%skyline%"),
                )
            )
        elif vt in ("waterfront", "beach"):
            stmt = stmt.where(
                or_(
                    Vendor.business_name.ilike("%oceanfront%"),
                    Vendor.business_name.ilike("%harbour%"),
                    Vendor.business_name.ilike("%lake%"),
                    Vendor.business_name.ilike("%sea%"),
                    Vendor.business_name.ilike("%beach%"),
                    Vendor.business_name.ilike("%canal%"),
                    Vendor.business_name.ilike("%waterfront%"),
                    Vendor.description.ilike("%waterfront%"),
                    Vendor.description.ilike("%ocean%"),
                )
            )
        elif vt == "industrial":
            stmt = stmt.where(
                or_(
                    Vendor.business_name.ilike("%warehouse%"),
                    Vendor.business_name.ilike("%loft%"),
                    Vendor.business_name.ilike("%hangar%"),
                    Vendor.business_name.ilike("%kraftwerk%"),
                    Vendor.business_name.ilike("%arena%"),
                    Vendor.description.ilike("%industrial%"),
                    Vendor.description.ilike("%concrete%"),
                )
            )
        elif vt in ("botanical", "outdoor", "estate"):
            stmt = stmt.where(
                or_(
                    Vendor.business_name.ilike("%garden%"),
                    Vendor.business_name.ilike("%vineyard%"),
                    Vendor.business_name.ilike("%glasshouse%"),
                    Vendor.business_name.ilike("%amphitheatre%"),
                    Vendor.business_name.ilike("%safari%"),
                    Vendor.business_name.ilike("%conservatory%"),
                    Vendor.business_name.ilike("%courtyard%"),
                    Vendor.description.ilike("%garden%"),
                    Vendor.description.ilike("%botanical%"),
                )
            )

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    if sort_by == "capacity_desc":
        order_clauses = [Vendor.capacity.desc().nullslast(), Vendor.is_verified.desc()]
    elif sort_by == "capacity_asc":
        order_clauses = [Vendor.capacity.asc().nullslast(), Vendor.is_verified.desc()]
    elif sort_by == "rating":
        order_clauses = [Vendor.rating_avg.desc(), Vendor.reviews_count.desc()]
    elif sort_by == "price_asc":
        order_clauses = [Vendor.starting_price.asc().nullslast()]
    elif sort_by == "price_desc":
        order_clauses = [Vendor.starting_price.desc().nullslast()]
    elif sort_by == "name":
        order_clauses = [Vendor.business_name.asc()]
    else:
        order_clauses = [
            Vendor.is_featured.desc(),
            Vendor.is_verified.desc(),
            Vendor.rating_avg.desc(),
            Vendor.lead_count.desc(),
            Vendor.created_at.desc(),
        ]

    result = await db.scalars(
        stmt.order_by(*order_clauses)
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
        stmt.order_by(VendorLead.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    return list(result.all()), total




async def create_booth_package(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    name: str,
    price: float,
    currency: str = "NGN",
    total_booths: int = 10,
    description: str | None = None,
    dimensions: str | None = None,
    amenities: list[str] | None = None,
) -> EventBoothPackage:
    pkg = EventBoothPackage(
        event_id=event_id,
        name=name,
        price=price,
        currency=currency.upper(),
        total_booths=total_booths,
        booths_remaining=total_booths,
        description=description,
        dimensions=dimensions,
        amenities=amenities or [],
        is_active=True,
    )
    db.add(pkg)
    await db.commit()
    await db.refresh(pkg)
    return pkg


async def list_booth_packages(
    db: AsyncSession, event_id: uuid.UUID, active_only: bool = False
) -> list[EventBoothPackage]:
    stmt = select(EventBoothPackage).where(EventBoothPackage.event_id == event_id)
    if active_only:
        stmt = stmt.where(EventBoothPackage.is_active.is_(True))
    result = await db.scalars(
        stmt.order_by(EventBoothPackage.price.asc(), EventBoothPackage.name.asc())
    )
    return list(result.all())


async def get_booth_package(db: AsyncSession, package_id: uuid.UUID) -> EventBoothPackage | None:
    return await db.scalar(select(EventBoothPackage).where(EventBoothPackage.id == package_id))


async def create_booth_application(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    business_name: str,
    contact_name: str,
    contact_email: str,
    contact_phone: str,
    category: str,
    package_id: uuid.UUID | None = None,
    description: str | None = None,
    booth_requirements: str | None = None,
    vendor_id: uuid.UUID | None = None,
) -> BoothApplication:
    price = 0.0
    currency = "NGN"
    if package_id:
        pkg = await get_booth_package(db, package_id)
        if pkg:
            price = float(pkg.price)
            currency = pkg.currency

    app = BoothApplication(
        event_id=event_id,
        vendor_id=vendor_id,
        package_id=package_id,
        business_name=business_name,
        contact_name=contact_name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        category=category,
        description=description,
        booth_requirements=booth_requirements,
        price=price,
        currency=currency,
        status="pending",
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return app



async def list_booth_applications(
    db: AsyncSession,
    *,
    org_id: uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[BoothApplication], int]:
    from sqlalchemy.orm import selectinload

    from app.models.event import Event

    stmt = select(BoothApplication).options(
        selectinload(BoothApplication.package),
        selectinload(BoothApplication.event),
        selectinload(BoothApplication.vendor),
    )
    if event_id:
        stmt = stmt.where(BoothApplication.event_id == event_id)
    elif org_id:
        stmt = stmt.join(Event, BoothApplication.event_id == Event.id).where(Event.org_id == org_id)

    if status and status != "all":
        stmt = stmt.where(BoothApplication.status == status)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    result = await db.scalars(
        stmt.order_by(BoothApplication.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return list(result.all()), total


async def get_booth_application(db: AsyncSession, app_id: uuid.UUID) -> BoothApplication | None:
    from sqlalchemy.orm import selectinload

    return await db.scalar(
        select(BoothApplication)
        .options(
            selectinload(BoothApplication.package),
            selectinload(BoothApplication.event),
            selectinload(BoothApplication.vendor),
        )
        .where(BoothApplication.id == app_id)
    )


async def approve_booth_application(
    db: AsyncSession,
    app: BoothApplication,
    *,
    assigned_booth_number: str | None = None,
    base_url: str = "",
) -> BoothApplication:
    app.status = "approved"
    if assigned_booth_number:
        app.assigned_booth_number = assigned_booth_number
    if not app.payment_reference:
        app.payment_reference = f"booth_{app.id.hex[:12]}_{uuid.uuid4().hex[:6]}"
    app.invoice_url = f"{base_url.rstrip('/')}/booths/{app.id}/pay"

    await db.commit()
    await db.refresh(app)
    return app



async def reject_booth_application(
    db: AsyncSession, app: BoothApplication, *, reason: str | None = None
) -> BoothApplication:
    app.status = "rejected"
    app.rejection_reason = reason
    await db.commit()
    await db.refresh(app)
    return app



async def confirm_booth_payment(
    db: AsyncSession,
    app: BoothApplication,
    *,
    payment_reference: str | None = None,
) -> BoothApplication:
    from datetime import UTC, datetime

    from app.models.speaker import Sponsor

    app.status = "paid"
    app.paid_at = datetime.now(UTC)
    if payment_reference:
        app.payment_reference = payment_reference

    # Decrement remaining booths on package
    if app.package_id:
        pkg = await get_booth_package(db, app.package_id)
        if pkg and pkg.booths_remaining > 0:
            pkg.booths_remaining -= 1

    # Check if a sponsor/exhibitor entry already exists for this event and business
    existing_sponsor = await db.scalar(
        select(Sponsor).where(
            Sponsor.event_id == app.event_id,
            func.lower(Sponsor.name) == app.business_name.lower().strip(),
        )
    )
    if not existing_sponsor:
        sponsor = Sponsor(
            event_id=app.event_id,
            name=app.business_name,
            is_exhibitor=True,
            booth_number=app.assigned_booth_number,
            category=app.category,
            contact_email=app.contact_email,
            tier="partner",
        )
        db.add(sponsor)
    else:
        existing_sponsor.is_exhibitor = True
        if app.assigned_booth_number:
            existing_sponsor.booth_number = app.assigned_booth_number

    await db.commit()
    await db.refresh(app)
    return app



# ── Configuration Constants ───────────────────────────────────────────────────
DEFAULT_PLATFORM_COMMISSION_PERCENT = 10.0

VENDOR_SUBSCRIPTION_PLANS_BY_CURRENCY: dict[str, dict[str, dict]] = {
    "USD": {
        "free": {"name": "Free", "price": 0.0, "currency": "USD", "symbol": "$", "max_services": 2, "max_portfolio": 3, "lead_credits": 0, "badge": None, "priority_placement": False},
        "starter": {"name": "Starter", "price": 29.0, "currency": "USD", "symbol": "$", "max_services": 10, "max_portfolio": 10, "lead_credits": 5, "badge": "Pro Listed", "priority_placement": False},
        "pro": {"name": "Professional", "price": 69.0, "currency": "USD", "symbol": "$", "max_services": 30, "max_portfolio": 25, "lead_credits": 20, "badge": "Top Rated", "priority_placement": True},
        "premium": {"name": "Premium", "price": 149.0, "currency": "USD", "symbol": "$", "max_services": 100, "max_portfolio": 50, "lead_credits": 50, "badge": "Elite Vendor", "priority_placement": True},
    },
    "GBP": {
        "free": {"name": "Free", "price": 0.0, "currency": "GBP", "symbol": "£", "max_services": 2, "max_portfolio": 3, "lead_credits": 0, "badge": None, "priority_placement": False},
        "starter": {"name": "Starter", "price": 25.0, "currency": "GBP", "symbol": "£", "max_services": 10, "max_portfolio": 10, "lead_credits": 5, "badge": "Pro Listed", "priority_placement": False},
        "pro": {"name": "Professional", "price": 55.0, "currency": "GBP", "symbol": "£", "max_services": 30, "max_portfolio": 25, "lead_credits": 20, "badge": "Top Rated", "priority_placement": True},
        "premium": {"name": "Premium", "price": 119.0, "currency": "GBP", "symbol": "£", "max_services": 100, "max_portfolio": 50, "lead_credits": 50, "badge": "Elite Vendor", "priority_placement": True},
    },
    "EUR": {
        "free": {"name": "Free", "price": 0.0, "currency": "EUR", "symbol": "€", "max_services": 2, "max_portfolio": 3, "lead_credits": 0, "badge": None, "priority_placement": False},
        "starter": {"name": "Starter", "price": 27.0, "currency": "EUR", "symbol": "€", "max_services": 10, "max_portfolio": 10, "lead_credits": 5, "badge": "Pro Listed", "priority_placement": False},
        "pro": {"name": "Professional", "price": 59.0, "currency": "EUR", "symbol": "€", "max_services": 30, "max_portfolio": 25, "lead_credits": 20, "badge": "Top Rated", "priority_placement": True},
        "premium": {"name": "Premium", "price": 129.0, "currency": "EUR", "symbol": "€", "max_services": 100, "max_portfolio": 50, "lead_credits": 50, "badge": "Elite Vendor", "priority_placement": True},
    },
    "CAD": {
        "free": {"name": "Free", "price": 0.0, "currency": "CAD", "symbol": "CA$", "max_services": 2, "max_portfolio": 3, "lead_credits": 0, "badge": None, "priority_placement": False},
        "starter": {"name": "Starter", "price": 39.0, "currency": "CAD", "symbol": "CA$", "max_services": 10, "max_portfolio": 10, "lead_credits": 5, "badge": "Pro Listed", "priority_placement": False},
        "pro": {"name": "Professional", "price": 89.0, "currency": "CAD", "symbol": "CA$", "max_services": 30, "max_portfolio": 25, "lead_credits": 20, "badge": "Top Rated", "priority_placement": True},
        "premium": {"name": "Premium", "price": 199.0, "currency": "CAD", "symbol": "CA$", "max_services": 100, "max_portfolio": 50, "lead_credits": 50, "badge": "Elite Vendor", "priority_placement": True},
    },
    "AUD": {
        "free": {"name": "Free", "price": 0.0, "currency": "AUD", "symbol": "A$", "max_services": 2, "max_portfolio": 3, "lead_credits": 0, "badge": None, "priority_placement": False},
        "starter": {"name": "Starter", "price": 45.0, "currency": "AUD", "symbol": "A$", "max_services": 10, "max_portfolio": 10, "lead_credits": 5, "badge": "Pro Listed", "priority_placement": False},
        "pro": {"name": "Professional", "price": 99.0, "currency": "AUD", "symbol": "A$", "max_services": 30, "max_portfolio": 25, "lead_credits": 20, "badge": "Top Rated", "priority_placement": True},
        "premium": {"name": "Premium", "price": 219.0, "currency": "AUD", "symbol": "A$", "max_services": 100, "max_portfolio": 50, "lead_credits": 50, "badge": "Elite Vendor", "priority_placement": True},
    },
    "NGN": {
        "free": {"name": "Free", "price": 0.0, "currency": "NGN", "symbol": "₦", "max_services": 2, "max_portfolio": 3, "lead_credits": 0, "badge": None, "priority_placement": False},
        "starter": {"name": "Starter", "price": 15000.0, "currency": "NGN", "symbol": "₦", "max_services": 10, "max_portfolio": 10, "lead_credits": 5, "badge": "Pro Listed", "priority_placement": False},
        "pro": {"name": "Professional", "price": 35000.0, "currency": "NGN", "symbol": "₦", "max_services": 30, "max_portfolio": 25, "lead_credits": 20, "badge": "Top Rated", "priority_placement": True},
        "premium": {"name": "Premium", "price": 75000.0, "currency": "NGN", "symbol": "₦", "max_services": 100, "max_portfolio": 50, "lead_credits": 50, "badge": "Elite Vendor", "priority_placement": True},
    },
    "KES": {
        "free": {"name": "Free", "price": 0.0, "currency": "KES", "symbol": "KSh", "max_services": 2, "max_portfolio": 3, "lead_credits": 0, "badge": None, "priority_placement": False},
        "starter": {"name": "Starter", "price": 3500.0, "currency": "KES", "symbol": "KSh", "max_services": 10, "max_portfolio": 10, "lead_credits": 5, "badge": "Pro Listed", "priority_placement": False},
        "pro": {"name": "Professional", "price": 8000.0, "currency": "KES", "symbol": "KSh", "max_services": 30, "max_portfolio": 25, "lead_credits": 20, "badge": "Top Rated", "priority_placement": True},
        "premium": {"name": "Premium", "price": 18000.0, "currency": "KES", "symbol": "KSh", "max_services": 100, "max_portfolio": 50, "lead_credits": 50, "badge": "Elite Vendor", "priority_placement": True},
    },
    "GHS": {
        "free": {"name": "Free", "price": 0.0, "currency": "GHS", "symbol": "GH₵", "max_services": 2, "max_portfolio": 3, "lead_credits": 0, "badge": None, "priority_placement": False},
        "starter": {"name": "Starter", "price": 350.0, "currency": "GHS", "symbol": "GH₵", "max_services": 10, "max_portfolio": 10, "lead_credits": 5, "badge": "Pro Listed", "priority_placement": False},
        "pro": {"name": "Professional", "price": 800.0, "currency": "GHS", "symbol": "GH₵", "max_services": 30, "max_portfolio": 25, "lead_credits": 20, "badge": "Top Rated", "priority_placement": True},
        "premium": {"name": "Premium", "price": 1800.0, "currency": "GHS", "symbol": "GH₵", "max_services": 100, "max_portfolio": 50, "lead_credits": 50, "badge": "Elite Vendor", "priority_placement": True},
    },
    "ZAR": {
        "free": {"name": "Free", "price": 0.0, "currency": "ZAR", "symbol": "R", "max_services": 2, "max_portfolio": 3, "lead_credits": 0, "badge": None, "priority_placement": False},
        "starter": {"name": "Starter", "price": 450.0, "currency": "ZAR", "symbol": "R", "max_services": 10, "max_portfolio": 10, "lead_credits": 5, "badge": "Pro Listed", "priority_placement": False},
        "pro": {"name": "Professional", "price": 1100.0, "currency": "ZAR", "symbol": "R", "max_services": 30, "max_portfolio": 25, "lead_credits": 20, "badge": "Top Rated", "priority_placement": True},
        "premium": {"name": "Premium", "price": 2400.0, "currency": "ZAR", "symbol": "R", "max_services": 100, "max_portfolio": 50, "lead_credits": 50, "badge": "Elite Vendor", "priority_placement": True},
    },
}

# Backward compatibility default (NGN)
VENDOR_SUBSCRIPTION_PLANS = VENDOR_SUBSCRIPTION_PLANS_BY_CURRENCY["NGN"]


def get_vendor_subscription_plans(currency: str | None = None) -> dict[str, dict]:
    curr = (currency or "USD").upper()
    return VENDOR_SUBSCRIPTION_PLANS_BY_CURRENCY.get(curr, VENDOR_SUBSCRIPTION_PLANS_BY_CURRENCY["USD"])


FEATURED_CAMPAIGN_PRICING_BY_CURRENCY: dict[str, dict[str, dict[str, float]]] = {
    "USD": {
        "marketplace_top": {"7_days": 25.0, "30_days": 75.0},
        "category_featured": {"7_days": 15.0, "30_days": 45.0},
        "hero_spotlight": {"7_days": 39.0, "30_days": 119.0},
    },
    "GBP": {
        "marketplace_top": {"7_days": 20.0, "30_days": 59.0},
        "category_featured": {"7_days": 12.0, "30_days": 35.0},
        "hero_spotlight": {"7_days": 30.0, "30_days": 95.0},
    },
    "EUR": {
        "marketplace_top": {"7_days": 22.0, "30_days": 65.0},
        "category_featured": {"7_days": 14.0, "30_days": 39.0},
        "hero_spotlight": {"7_days": 35.0, "30_days": 105.0},
    },
    "NGN": {
        "marketplace_top": {"7_days": 10000.0, "30_days": 30000.0},
        "category_featured": {"7_days": 6000.0, "30_days": 18000.0},
        "hero_spotlight": {"7_days": 15000.0, "30_days": 45000.0},
    },
}

FEATURED_CAMPAIGN_PRICING = FEATURED_CAMPAIGN_PRICING_BY_CURRENCY["NGN"]


def get_featured_pricing(placement: str, duration_days: int, currency: str | None = None) -> tuple[float, str, str]:
    curr = (currency or "USD").upper()
    curr_dict = FEATURED_CAMPAIGN_PRICING_BY_CURRENCY.get(curr, FEATURED_CAMPAIGN_PRICING_BY_CURRENCY["USD"])
    rates = curr_dict.get(placement, curr_dict["marketplace_top"])
    duration_key = "30_days" if duration_days >= 30 else "7_days"
    price = rates.get(duration_key, 25.0)
    symbol = "£" if curr == "GBP" else ("€" if curr == "EUR" else ("₦" if curr == "NGN" else "$"))
    return price, curr, symbol


LEAD_CREDIT_PACKAGES_BY_CURRENCY: dict[str, dict[int, float]] = {
    "USD": {5: 10.0, 15: 25.0, 30: 45.0},
    "GBP": {5: 8.0, 15: 20.0, 30: 35.0},
    "EUR": {5: 9.0, 15: 22.0, 30: 40.0},
    "NGN": {5: 5000.0, 15: 12000.0, 30: 20000.0},
}

LEAD_CREDIT_PACKAGES = LEAD_CREDIT_PACKAGES_BY_CURRENCY["NGN"]


def get_lead_credit_price(credits_count: int, currency: str | None = None) -> tuple[float, str, str]:
    curr = (currency or "USD").upper()
    pkg = LEAD_CREDIT_PACKAGES_BY_CURRENCY.get(curr, LEAD_CREDIT_PACKAGES_BY_CURRENCY["USD"])
    default_unit = 2.0 if curr in ("USD", "EUR", "GBP") else 1000.0
    price = pkg.get(credits_count, credits_count * default_unit)
    symbol = "£" if curr == "GBP" else ("€" if curr == "EUR" else ("₦" if curr == "NGN" else "$"))
    return price, curr, symbol


async def get_vendor_by_id(db: AsyncSession, vendor_id: uuid.UUID) -> Vendor | None:
    from sqlalchemy.orm import selectinload

    return await db.scalar(
        select(Vendor)
        .where(Vendor.id == vendor_id)
        .options(selectinload(Vendor.user))
    )


# ── Granular Service Listings CRUD ────────────────────────────────────────────
async def create_service_listing(
    db: AsyncSession,
    *,
    vendor_id: uuid.UUID,
    title: str,
    category: str,
    description: str | None = None,
    price: float = 0.0,
    price_max: float | None = None,
    pricing_type: str = "fixed",
    currency: str = "NGN",
    inclusions: list[str] | None = None,
    image_urls: list[str] | None = None,
    duration_hours: int | None = None,
) -> VendorServiceListing:
    vendor = await get_vendor_by_id(db, vendor_id)
    if not vendor:
        raise HTTPException(404, "Vendor not found.")

    # Check subscription entitlement limits
    plan_info = VENDOR_SUBSCRIPTION_PLANS.get(vendor.subscription_tier, VENDOR_SUBSCRIPTION_PLANS["free"])
    current_count = await db.scalar(
        select(func.count(VendorServiceListing.id)).where(VendorServiceListing.vendor_id == vendor_id)
    ) or 0
    if current_count >= plan_info["max_services"]:
        raise HTTPException(
            403,
            f"Your current {plan_info['name']} subscription plan permits up to {plan_info['max_services']} service listings. Please upgrade to add more.",
        )

    slug_base = _slugify(title) or "service"
    slug = f"{slug_base}-{uuid.uuid4().hex[:6]}"

    effective_currency = (currency or "NGN").upper()
    if effective_currency == "NGN" and vendor.currency and vendor.currency != "NGN":
        effective_currency = vendor.currency.upper()

    listing = VendorServiceListing(
        vendor_id=vendor_id,
        title=title,
        slug=slug,
        category=category,
        description=description,
        price=price,
        price_max=price_max,
        pricing_type=pricing_type,
        currency=effective_currency,
        inclusions=inclusions or [],
        image_urls=image_urls or [],
        duration_hours=duration_hours,
        is_active=True,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    return listing


async def get_service_listing(db: AsyncSession, listing_id: uuid.UUID) -> VendorServiceListing | None:
    from sqlalchemy.orm import selectinload

    return await db.scalar(
        select(VendorServiceListing)
        .where(VendorServiceListing.id == listing_id)
        .options(selectinload(VendorServiceListing.vendor))
    )


async def list_vendor_services(
    db: AsyncSession, vendor_id: uuid.UUID, active_only: bool = False
) -> list[VendorServiceListing]:
    stmt = select(VendorServiceListing).where(VendorServiceListing.vendor_id == vendor_id)
    if active_only:
        stmt = stmt.where(VendorServiceListing.is_active.is_(True))
    result = await db.scalars(stmt.order_by(VendorServiceListing.created_at.desc()))
    return list(result.all())


async def update_service_listing(
    db: AsyncSession, listing: VendorServiceListing, **fields
) -> VendorServiceListing:
    for k, v in fields.items():
        if hasattr(listing, k) and v is not None:
            setattr(listing, k, v)
    await db.commit()
    await db.refresh(listing)
    return listing


async def delete_service_listing(db: AsyncSession, listing: VendorServiceListing) -> None:
    await db.delete(listing)
    await db.commit()


# ── Advanced Marketplace Discovery & Ranking ──────────────────────────────────
async def list_vendors_advanced(
    db: AsyncSession,
    *,
    q: str | None = None,
    category: str | None = None,
    city: str | None = None,
    country: str | None = None,
    price_range: str | None = None,
    verified_only: bool = False,
    min_rating: float | None = None,
    sort_by: str = "relevance",  # relevance, rating, price_asc, price_desc, popularity
    page: int = 1,
    per_page: int = 24,
) -> tuple[list[Vendor], int]:
    from datetime import UTC, datetime

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
    if verified_only:
        stmt = stmt.where(Vendor.is_verified.is_(True))
    if min_rating:
        stmt = stmt.where(Vendor.rating_avg >= min_rating)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    now = datetime.now(UTC)
    is_featured_active = or_(
        Vendor.is_featured.is_(True),
        Vendor.featured_until > now,
    )

    if sort_by == "rating":
        stmt = stmt.order_by(Vendor.rating_avg.desc(), Vendor.reviews_count.desc())
    elif sort_by == "price_asc":
        stmt = stmt.order_by(Vendor.starting_price.asc().nulls_last())
    elif sort_by == "price_desc":
        stmt = stmt.order_by(Vendor.starting_price.desc().nulls_last())
    elif sort_by == "popularity":
        stmt = stmt.order_by(Vendor.lead_count.desc(), Vendor.reviews_count.desc())
    else:  # relevance default: featured -> verified -> rating -> lead_count
        stmt = stmt.order_by(
            is_featured_active.desc(),
            Vendor.is_verified.desc(),
            Vendor.rating_avg.desc(),
            Vendor.lead_count.desc(),
            Vendor.created_at.desc(),
        )

    from sqlalchemy.orm import selectinload

    result = await db.scalars(stmt.options(selectinload(Vendor.user)).offset((page - 1) * per_page).limit(per_page))
    return list(result.all()), total


# ── Request-a-Quote (RFQ) Flow ────────────────────────────────────────────────
async def create_quote_request(
    db: AsyncSession,
    *,
    requester_id: uuid.UUID,
    event_name: str,
    service_category: str,
    requirements: str,
    org_id: uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    event_type: str | None = None,
    event_date: datetime | None = None,
    event_location: str | None = None,
    expected_attendance: int | None = None,
    budget_min: float | None = None,
    budget_max: float | None = None,
    currency: str = "NGN",
    preferred_deadline: datetime | None = None,
    attachments: list[str] | None = None,
    vendor_ids: list[uuid.UUID] | None = None,
) -> VendorQuoteRequest:
    req = VendorQuoteRequest(
        requester_id=requester_id,
        org_id=org_id,
        event_id=event_id,
        event_name=event_name,
        event_type=event_type,
        event_date=event_date,
        event_location=event_location,
        expected_attendance=expected_attendance,
        service_category=service_category,
        budget_min=budget_min,
        budget_max=budget_max,
        currency=currency.upper(),
        requirements=requirements,
        preferred_deadline=preferred_deadline,
        attachments=attachments or [],
        status="open",
    )
    db.add(req)
    await db.flush()

    # Link recipients
    if vendor_ids:
        for vid in vendor_ids:
            rcp = VendorQuoteRecipient(
                request_id=req.id,
                vendor_id=vid,
                status="pending",
            )
            db.add(rcp)

    await db.commit()
    await db.refresh(req)
    return req


async def get_quote_request(db: AsyncSession, request_id: uuid.UUID) -> VendorQuoteRequest | None:
    from sqlalchemy.orm import selectinload

    return await db.scalar(
        select(VendorQuoteRequest)
        .where(VendorQuoteRequest.id == request_id)
        .options(
            selectinload(VendorQuoteRequest.recipients).selectinload(VendorQuoteRecipient.vendor),
            selectinload(VendorQuoteRequest.quotations).selectinload(VendorQuotation.vendor),
            selectinload(VendorQuoteRequest.requester),
        )
    )


async def list_vendor_inquiries(
    db: AsyncSession, vendor_id: uuid.UUID, status: str | None = None
) -> list[VendorQuoteRecipient]:
    from sqlalchemy.orm import selectinload

    stmt = select(VendorQuoteRecipient).where(VendorQuoteRecipient.vendor_id == vendor_id)
    if status:
        stmt = stmt.where(VendorQuoteRecipient.status == status)
    result = await db.scalars(
        stmt.options(
            selectinload(VendorQuoteRecipient.request).selectinload(VendorQuoteRequest.requester),
            selectinload(VendorQuoteRecipient.quotations),
        ).order_by(VendorQuoteRecipient.created_at.desc())
    )
    return list(result.all())


async def list_requester_quote_requests(
    db: AsyncSession, requester_id: uuid.UUID, status: str | None = None
) -> list[VendorQuoteRequest]:
    from sqlalchemy.orm import selectinload

    stmt = select(VendorQuoteRequest).where(VendorQuoteRequest.requester_id == requester_id)
    if status:
        stmt = stmt.where(VendorQuoteRequest.status == status)
    result = await db.scalars(
        stmt.options(
            selectinload(VendorQuoteRequest.recipients).selectinload(VendorQuoteRecipient.vendor),
            selectinload(VendorQuoteRequest.quotations).selectinload(VendorQuotation.vendor),
        ).order_by(VendorQuoteRequest.created_at.desc())
    )
    return list(result.all())


async def submit_quotation(
    db: AsyncSession,
    *,
    vendor_id: uuid.UUID,
    requester_id: uuid.UUID,
    title: str,
    scope_of_work: str,
    total_amount: float,
    quote_request_id: uuid.UUID | None = None,
    recipient_id: uuid.UUID | None = None,
    items: list[dict] | None = None,
    currency: str = "NGN",
    deposit_required: float = 0.0,
    valid_until: datetime | None = None,
    notes: str | None = None,
    attachment_url: str | None = None,
    attachment_name: str | None = None,
) -> VendorQuotation:
    effective_currency = (currency or "NGN").upper()
    if effective_currency == "NGN":
        vendor = await get_vendor_by_id(db, vendor_id)
        if vendor and vendor.currency and vendor.currency != "NGN":
            effective_currency = vendor.currency.upper()

    quote = VendorQuotation(
        vendor_id=vendor_id,
        requester_id=requester_id,
        quote_request_id=quote_request_id,
        recipient_id=recipient_id,
        title=title,
        scope_of_work=scope_of_work,
        items=items or [],
        total_amount=total_amount,
        currency=effective_currency,
        deposit_required=deposit_required,
        valid_until=valid_until,
        notes=notes,
        attachment_url=attachment_url,
        attachment_name=attachment_name,
        status="submitted",
    )
    db.add(quote)

    if recipient_id:
        recipient = await db.get(VendorQuoteRecipient, recipient_id)
        if recipient:
            recipient.status = "quoted"

    await db.commit()
    await db.refresh(quote)
    return quote


async def get_quotation(db: AsyncSession, quotation_id: uuid.UUID) -> VendorQuotation | None:
    from sqlalchemy.orm import selectinload

    return await db.scalar(
        select(VendorQuotation)
        .where(VendorQuotation.id == quotation_id)
        .options(
            selectinload(VendorQuotation.vendor),
            selectinload(VendorQuotation.requester),
            selectinload(VendorQuotation.quote_request),
        )
    )


async def accept_quotation(db: AsyncSession, quotation: VendorQuotation) -> VendorQuotation:
    quotation.status = "accepted"
    if quotation.quote_request_id:
        req = await db.get(VendorQuoteRequest, quotation.quote_request_id)
        if req:
            req.status = "accepted"
    await db.commit()
    await db.refresh(quotation)
    return quotation


async def decline_quote_request(
    db: AsyncSession, recipient: VendorQuoteRecipient, reason: str | None = None
) -> VendorQuoteRecipient:
    recipient.status = "declined"
    recipient.declined_reason = reason
    await db.commit()
    await db.refresh(recipient)
    return recipient


# ── Booking & Contract Lifecycle ──────────────────────────────────────────────
async def create_booking_from_quotation(
    db: AsyncSession,
    quotation: VendorQuotation,
    *,
    cancellation_policy: str = "moderate",
    cancellation_terms: str | None = None,
) -> VendorBooking:
    vendor = await get_vendor_by_id(db, quotation.vendor_id)
    if not vendor:
        raise HTTPException(404, "Vendor not found.")

    # Calculate platform commission (Model A)
    commission_rate = (
        float(vendor.custom_commission_rate)
        if vendor.custom_commission_rate is not None
        else DEFAULT_PLATFORM_COMMISSION_PERCENT
    )
    total_amount = float(quotation.total_amount)
    commission_amount = round((total_amount * commission_rate) / 100.0, 2)
    vendor_earnings = round(total_amount - commission_amount, 2)

    ref = f"VB-{uuid.uuid4().hex[:8].upper()}"

    booking = VendorBooking(
        booking_reference=ref,
        vendor_id=quotation.vendor_id,
        quotation_id=quotation.id,
        requester_id=quotation.requester_id,
        org_id=quotation.quote_request.org_id if quotation.quote_request else None,
        event_id=quotation.quote_request.event_id if quotation.quote_request else None,
        event_name=quotation.quote_request.event_name if quotation.quote_request else quotation.title,
        event_date=quotation.quote_request.event_date if quotation.quote_request else None,
        event_location=quotation.quote_request.event_location if quotation.quote_request else None,
        service_summary=f"{quotation.title}\n{quotation.scope_of_work}",
        total_amount=total_amount,
        platform_commission_rate=commission_rate,
        commission_amount=commission_amount,
        vendor_earnings=vendor_earnings,
        currency=quotation.currency,
        cancellation_policy=cancellation_policy,
        cancellation_terms=cancellation_terms or "Standard Tixdoo cancellation terms apply.",
        payment_reference=f"vbook_{uuid.uuid4().hex[:12]}_{uuid.uuid4().hex[:6]}",
        status="pending_payment",
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)
    return booking


async def create_direct_booking(
    db: AsyncSession,
    *,
    vendor_id: uuid.UUID,
    requester_id: uuid.UUID,
    service_listing_id: uuid.UUID,
    event_name: str | None = None,
    event_date: datetime | None = None,
    event_location: str | None = None,
    cancellation_policy: str = "moderate",
) -> VendorBooking:
    vendor = await get_vendor_by_id(db, vendor_id)
    listing = await get_service_listing(db, service_listing_id)
    if not vendor or not listing:
        raise HTTPException(404, "Vendor or service not found.")

    commission_rate = (
        float(vendor.custom_commission_rate)
        if vendor.custom_commission_rate is not None
        else DEFAULT_PLATFORM_COMMISSION_PERCENT
    )
    total_amount = float(listing.price)
    commission_amount = round((total_amount * commission_rate) / 100.0, 2)
    vendor_earnings = round(total_amount - commission_amount, 2)

    ref = f"VB-{uuid.uuid4().hex[:8].upper()}"

    booking = VendorBooking(
        booking_reference=ref,
        vendor_id=vendor_id,
        service_listing_id=listing.id,
        requester_id=requester_id,
        event_name=event_name or f"Booking for {listing.title}",
        event_date=event_date,
        event_location=event_location,
        service_summary=f"{listing.title}: {listing.description or ''}",
        total_amount=total_amount,
        platform_commission_rate=commission_rate,
        commission_amount=commission_amount,
        vendor_earnings=vendor_earnings,
        currency=listing.currency,
        cancellation_policy=cancellation_policy,
        payment_reference=f"vbook_{uuid.uuid4().hex[:12]}_{uuid.uuid4().hex[:6]}",
        status="pending_payment",
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)
    return booking


async def get_booking_by_ref(db: AsyncSession, reference: str) -> VendorBooking | None:
    from sqlalchemy.orm import selectinload

    return await db.scalar(
        select(VendorBooking)
        .where(VendorBooking.booking_reference == reference)
        .options(
            selectinload(VendorBooking.vendor),
            selectinload(VendorBooking.requester),
            selectinload(VendorBooking.service_listing),
            selectinload(VendorBooking.review),
        )
    )


async def get_booking_by_id(db: AsyncSession, booking_id: uuid.UUID) -> VendorBooking | None:
    from sqlalchemy.orm import selectinload

    return await db.scalar(
        select(VendorBooking)
        .where(VendorBooking.id == booking_id)
        .options(
            selectinload(VendorBooking.vendor),
            selectinload(VendorBooking.requester),
            selectinload(VendorBooking.service_listing),
            selectinload(VendorBooking.review),
        )
    )


async def list_vendor_bookings(
    db: AsyncSession, vendor_id: uuid.UUID, status: str | None = None
) -> list[VendorBooking]:
    from sqlalchemy.orm import selectinload

    stmt = select(VendorBooking).where(VendorBooking.vendor_id == vendor_id)
    if status:
        stmt = stmt.where(VendorBooking.status == status)
    result = await db.scalars(
        stmt.options(
            selectinload(VendorBooking.requester),
            selectinload(VendorBooking.review),
        ).order_by(VendorBooking.created_at.desc())
    )
    return list(result.all())


async def list_requester_bookings(
    db: AsyncSession, requester_id: uuid.UUID, status: str | None = None
) -> list[VendorBooking]:
    from sqlalchemy.orm import selectinload

    stmt = select(VendorBooking).where(VendorBooking.requester_id == requester_id)
    if status:
        stmt = stmt.where(VendorBooking.status == status)
    result = await db.scalars(
        stmt.options(
            selectinload(VendorBooking.vendor),
            selectinload(VendorBooking.review),
        ).order_by(VendorBooking.created_at.desc())
    )
    return list(result.all())


async def confirm_booking_payment(
    db: AsyncSession,
    booking: VendorBooking,
    *,
    payment_reference: str,
    payment_method: str = "paystack",
) -> VendorBooking:
    from datetime import UTC, datetime

    if booking.status not in ("pending_payment",):
        return booking

    booking.status = "confirmed"
    booking.escrow_status = "held_in_escrow"
    booking.payment_reference = payment_reference
    booking.payment_method = payment_method
    booking.paid_at = datetime.now(UTC)

    # Immutable ledger recording for Escrow Deposit (held in trust)
    tx = VendorTransaction(
        reference=f"TX-{payment_reference}",
        vendor_id=booking.vendor_id,
        booking_id=booking.id,
        type="escrow_deposit",
        gross_amount=booking.total_amount,
        platform_fee=booking.commission_amount,
        net_amount=booking.vendor_earnings,
        currency=booking.currency,
        status="completed",
        payment_provider=payment_method,
        provider_reference=payment_reference,
        metadata_json={
            "description": f"Escrow deposit for booking {booking.booking_reference}",
            "escrow_status": "held_in_escrow",
        },
    )
    db.add(tx)

    # Credit vendor ESCROW balance (funds locked in trust, not withdrawable yet)
    vendor = await db.get(Vendor, booking.vendor_id)
    if vendor:
        vendor.escrow_balance = float(vendor.escrow_balance) + float(booking.vendor_earnings)

    await db.commit()
    await db.refresh(booking)
    try:
        from app.tasks.email import send_vendor_booking_confirmed_notification
        send_vendor_booking_confirmed_notification.delay(str(booking.id))
    except Exception:
        pass
    return booking


async def mark_booking_delivered(
    db: AsyncSession,
    booking: VendorBooking,
    *,
    proof_notes: str | None = None,
    proof_urls: list | None = None,
) -> VendorBooking:
    """Vendor signals service fulfillment with optional delivery notes/proofs, starting the 48-hour client review window."""
    from datetime import UTC, datetime, timedelta

    if booking.status not in ("confirmed", "in_progress"):
        raise HTTPException(400, f"Cannot mark booking as delivered when current status is '{booking.status}'.")

    now = datetime.now(UTC)
    booking.status = "delivered"
    booking.fulfillment_submitted_at = now
    booking.fulfillment_proof_notes = proof_notes
    booking.fulfillment_proof_urls = proof_urls or []
    # 48-hour auto-release SLA
    booking.auto_release_deadline = now + timedelta(hours=48)

    await db.commit()
    await db.refresh(booking)

    try:
        from app.tasks.email import send_vendor_fulfillment_submitted_notification
        send_vendor_fulfillment_submitted_notification.delay(str(booking.id))
    except Exception:
        pass

    return booking


async def release_booking_escrow(
    db: AsyncSession,
    booking: VendorBooking,
    *,
    reason: str = "client_confirmation",
) -> VendorBooking:
    """Releases net booking earnings from escrow to the vendor's withdrawable payable balance and books platform commission."""
    from datetime import UTC, datetime

    if booking.escrow_status != "held_in_escrow":
        if booking.escrow_status == "released":
            return booking
        raise HTTPException(400, f"Cannot release escrow with status '{booking.escrow_status}'.")

    now = datetime.now(UTC)
    booking.status = "completed"
    booking.escrow_status = "released"
    booking.escrow_released_at = now
    booking.completed_at = now

    vendor = await db.get(Vendor, booking.vendor_id)
    if vendor:
        earnings = float(booking.vendor_earnings)
        vendor.escrow_balance = max(0.0, float(vendor.escrow_balance) - earnings)
        vendor.payable_balance = float(vendor.payable_balance) + earnings
        vendor.total_earned = float(vendor.total_earned) + earnings

    # Record immutable ledger release
    tx = VendorTransaction(
        reference=f"REL-{uuid.uuid4().hex[:8].upper()}",
        vendor_id=booking.vendor_id,
        booking_id=booking.id,
        type="escrow_release",
        gross_amount=booking.total_amount,
        platform_fee=booking.commission_amount,
        net_amount=booking.vendor_earnings,
        currency=booking.currency,
        status="completed",
        payment_provider=booking.payment_method or "paystack",
        metadata_json={"release_reason": reason, "released_at": now.isoformat()},
    )
    db.add(tx)

    await db.commit()
    await db.refresh(booking)

    try:
        from app.tasks.email import send_vendor_booking_completed_notification
        send_vendor_booking_completed_notification.delay(str(booking.id))
    except Exception:
        pass

    return booking


async def complete_booking(db: AsyncSession, booking: VendorBooking) -> VendorBooking:
    """Manual completion that delegates directly to escrow release."""
    return await release_booking_escrow(db, booking, reason="manual_completion")


async def dispute_booking(
    db: AsyncSession,
    booking: VendorBooking,
    *,
    reason: str,
) -> VendorBooking:
    """Client reports an issue with fulfillment, freezing funds into disputed balance pending support mediation."""
    from datetime import UTC, datetime

    if booking.status in ("completed", "cancelled"):
        raise HTTPException(400, f"Cannot dispute a {booking.status} booking.")

    booking.status = "disputed"
    booking.dispute_reason = reason

    if booking.escrow_status == "held_in_escrow":
        booking.escrow_status = "disputed"
        vendor = await db.get(Vendor, booking.vendor_id)
        if vendor:
            earnings = float(booking.vendor_earnings)
            vendor.escrow_balance = max(0.0, float(vendor.escrow_balance) - earnings)
            vendor.disputed_balance = float(vendor.disputed_balance) + earnings

        tx = VendorTransaction(
            reference=f"DISP-{uuid.uuid4().hex[:8].upper()}",
            vendor_id=booking.vendor_id,
            booking_id=booking.id,
            type="escrow_dispute_freeze",
            gross_amount=-float(booking.vendor_earnings),
            platform_fee=0.0,
            net_amount=-float(booking.vendor_earnings),
            currency=booking.currency,
            status="completed",
            payment_provider=booking.payment_method or "paystack",
            metadata_json={"dispute_reason": reason, "disputed_at": datetime.now(UTC).isoformat()},
        )
        db.add(tx)

    await db.commit()
    await db.refresh(booking)
    return booking


async def cancel_booking(
    db: AsyncSession,
    booking: VendorBooking,
    *,
    reason: str,
    refund_amount: float = 0.0,
) -> VendorBooking:
    from datetime import UTC, datetime

    booking.status = "cancelled"
    booking.cancelled_at = datetime.now(UTC)
    booking.cancellation_reason = reason
    booking.refund_amount = refund_amount

    # If already paid and refund occurs, adjust balances safely from escrow
    vendor = await db.get(Vendor, booking.vendor_id)
    if booking.paid_at and refund_amount > 0 and vendor:
        if booking.escrow_status == "held_in_escrow":
            vendor.escrow_balance = max(0.0, float(vendor.escrow_balance) - refund_amount)
            booking.escrow_status = "refunded"
        elif booking.escrow_status == "disputed":
            vendor.disputed_balance = max(0.0, float(vendor.disputed_balance) - refund_amount)
            booking.escrow_status = "refunded"
        elif booking.escrow_status == "released":
            vendor.payable_balance = max(0.0, float(vendor.payable_balance) - refund_amount)

        tx = VendorTransaction(
            reference=f"REF-{uuid.uuid4().hex[:8].upper()}",
            vendor_id=booking.vendor_id,
            booking_id=booking.id,
            type="refund",
            gross_amount=-refund_amount,
            platform_fee=0.0,
            net_amount=-refund_amount,
            currency=booking.currency,
            status="completed",
            payment_provider=booking.payment_method or "paystack",
            metadata_json={"cancellation_reason": reason},
        )
        db.add(tx)

    await db.commit()
    await db.refresh(booking)
    return booking


async def process_auto_release_escrows(db: AsyncSession) -> list[str]:
    """Finds vendor bookings where the 48-hour SLA has expired and auto-releases escrow."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    stmt = (
        select(VendorBooking)
        .where(
            VendorBooking.escrow_status == "held_in_escrow",
            VendorBooking.status.in_(["delivered", "confirmed", "in_progress"]),
            VendorBooking.auto_release_deadline.is_not(None),
            VendorBooking.auto_release_deadline <= now,
        )
    )
    result = await db.scalars(stmt)
    bookings = list(result.all())
    released_refs = []

    for b in bookings:
        await release_booking_escrow(db, b, reason="auto_release_timeout")
        released_refs.append(b.booking_reference)

    return released_refs


# ── Reviews & Reputation (Phase 12) ───────────────────────────────────────────
async def create_vendor_review(
    db: AsyncSession,
    *,
    booking_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    rating: int,
    content: str,
    title: str | None = None,
) -> VendorReview:
    booking = await get_booking_by_id(db, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found.")
    if booking.status != "completed":
        raise HTTPException(400, "Reviews can only be submitted for completed bookings.")
    if booking.requester_id != reviewer_id:
        raise HTTPException(403, "Only the organizer/client of this booking can review this vendor.")

    existing = await db.scalar(select(VendorReview).where(VendorReview.booking_id == booking_id))
    if existing:
        raise HTTPException(409, "A review has already been submitted for this booking.")

    if not (1 <= rating <= 5):
        raise HTTPException(422, "Rating must be between 1 and 5 stars.")

    rev = VendorReview(
        vendor_id=booking.vendor_id,
        booking_id=booking_id,
        reviewer_id=reviewer_id,
        rating=rating,
        title=title,
        content=content,
        status="published",
    )
    db.add(rev)
    await db.flush()

    # Recalculate vendor average rating and review count
    stats = await db.execute(
        select(func.avg(VendorReview.rating), func.count(VendorReview.id)).where(
            VendorReview.vendor_id == booking.vendor_id,
            VendorReview.status == "published",
        )
    )
    avg_r, cnt_r = stats.first() or (0.0, 0)
    vendor = await db.get(Vendor, booking.vendor_id)
    if vendor:
        vendor.rating_avg = round(float(avg_r or 0.0), 2)
        vendor.reviews_count = int(cnt_r or 0)

    await db.commit()
    await db.refresh(rev)
    return rev


async def list_vendor_reviews(
    db: AsyncSession, vendor_id: uuid.UUID, status: str = "published"
) -> list[VendorReview]:
    from sqlalchemy.orm import selectinload

    stmt = select(VendorReview).where(VendorReview.vendor_id == vendor_id)
    if status:
        stmt = stmt.where(VendorReview.status == status)
    result = await db.scalars(
        stmt.options(selectinload(VendorReview.reviewer)).order_by(VendorReview.created_at.desc())
    )
    return list(result.all())


async def respond_to_review(
    db: AsyncSession, review: VendorReview, response: str
) -> VendorReview:
    review.response_from_vendor = response
    await db.commit()
    await db.refresh(review)
    return review


# ── Subscriptions, Featured Campaigns, Leads, Payouts (Models B, C, D, Payouts) ─
async def activate_vendor_subscription(
    db: AsyncSession,
    vendor: Vendor,
    tier: str,
    *,
    period_days: int = 30,
    payment_reference: str | None = None,
) -> VendorSubscription:
    from datetime import UTC, datetime, timedelta

    plans = get_vendor_subscription_plans(vendor.currency)
    if tier not in plans:
        raise HTTPException(400, "Invalid subscription tier.")

    plan = plans[tier]
    now = datetime.now(UTC)
    period_end = now + timedelta(days=period_days)

    vendor.subscription_tier = tier
    vendor.subscription_expires_at = period_end
    if plan["lead_credits"] > 0:
        vendor.lead_credits_balance += plan["lead_credits"]

    sub = VendorSubscription(
        vendor_id=vendor.id,
        tier=tier,
        price=plan["price"],
        currency=plan["currency"],
        period_start=now,
        period_end=period_end,
        payment_reference=payment_reference,
        status="active",
    )
    db.add(sub)

    if plan["price"] > 0:
        tx = VendorTransaction(
            reference=f"SUB-{payment_reference or uuid.uuid4().hex[:8].upper()}",
            vendor_id=vendor.id,
            type="subscription_fee",
            gross_amount=plan["price"],
            platform_fee=plan["price"],
            net_amount=0.0,
            currency=plan["currency"],
            status="completed",
            provider_reference=payment_reference,
        )
        db.add(tx)

    await db.commit()
    await db.refresh(sub)
    return sub


async def create_featured_campaign(
    db: AsyncSession,
    vendor: Vendor,
    *,
    placement: str = "marketplace_top",
    duration_days: int = 30,
    category: str | None = None,
    payment_reference: str | None = None,
) -> VendorFeaturedCampaign:
    from datetime import UTC, datetime, timedelta

    price, currency, _ = get_featured_pricing(placement, duration_days, vendor.currency)

    now = datetime.now(UTC)
    end_date = now + timedelta(days=duration_days)

    camp = VendorFeaturedCampaign(
        vendor_id=vendor.id,
        placement=placement,
        category=category or vendor.category,
        start_date=now,
        end_date=end_date,
        price_paid=price,
        currency=currency,
        payment_reference=payment_reference,
        status="active",
    )
    db.add(camp)

    vendor.is_featured = True
    vendor.featured_until = end_date

    tx = VendorTransaction(
        reference=f"FEAT-{payment_reference or uuid.uuid4().hex[:8].upper()}",
        vendor_id=vendor.id,
        type="featured_listing_fee",
        gross_amount=price,
        platform_fee=price,
        net_amount=0.0,
        currency=currency,
        status="completed",
        provider_reference=payment_reference,
    )
    db.add(tx)

    await db.commit()
    await db.refresh(camp)
    return camp


async def purchase_lead_credits(
    db: AsyncSession,
    vendor: Vendor,
    *,
    credits_count: int,
    payment_reference: str | None = None,
) -> VendorLeadCreditPurchase:
    price, currency, _ = get_lead_credit_price(credits_count, vendor.currency)

    vendor.lead_credits_balance += credits_count

    purchase = VendorLeadCreditPurchase(
        vendor_id=vendor.id,
        credits_purchased=credits_count,
        price_paid=price,
        currency=currency,
        payment_reference=payment_reference,
        status="completed",
    )
    db.add(purchase)

    tx = VendorTransaction(
        reference=f"LEAD-{payment_reference or uuid.uuid4().hex[:8].upper()}",
        vendor_id=vendor.id,
        type="lead_credit_purchase",
        gross_amount=price,
        platform_fee=price,
        net_amount=0.0,
        currency=currency,
        status="completed",
        provider_reference=payment_reference,
    )
    db.add(tx)

    await db.commit()
    await db.refresh(purchase)
    return purchase


async def deduct_lead_credit(db: AsyncSession, vendor: Vendor) -> bool:
    if vendor.lead_credits_balance < 1:
        return False
    vendor.lead_credits_balance -= 1
    await db.commit()
    await db.refresh(vendor)
    return True


async def request_vendor_payout(
    db: AsyncSession,
    vendor: Vendor,
    *,
    amount: float,
    method: str = "manual",
    account_details: dict | None = None,
    initiated_by: uuid.UUID | None = None,
) -> VendorPayout:
    if amount <= 0:
        raise HTTPException(422, "Payout amount must be greater than zero.")
    if amount > float(vendor.payable_balance):
        from app.utils.currency import currency_symbol
        sym = currency_symbol(vendor.currency)
        raise HTTPException(400, f"Insufficient balance. Your payable balance is {sym}{vendor.payable_balance:,.2f}.")

    vendor.payable_balance = float(vendor.payable_balance) - amount
    vendor.total_withdrawn = float(vendor.total_withdrawn) + amount

    payout = VendorPayout(
        vendor_id=vendor.id,
        amount=amount,
        currency=vendor.currency,
        method=method,
        account_details=account_details or {},
        status="pending",
        initiated_by=initiated_by,
    )
    db.add(payout)
    await db.flush()

    tx = VendorTransaction(
        reference=f"PAYOUT-{payout.id.hex[:8].upper()}",
        vendor_id=vendor.id,
        type="payout",
        gross_amount=-amount,
        platform_fee=0.0,
        net_amount=-amount,
        currency=vendor.currency,
        status="pending",
    )
    db.add(tx)

    await db.commit()
    await db.refresh(payout)
    try:
        from app.tasks.email import send_vendor_payout_requested_notification
        send_vendor_payout_requested_notification.delay(str(payout.id))
    except Exception:
        pass
    return payout


async def disburse_vendor_payout(
    db: AsyncSession,
    payout: VendorPayout,
    *,
    provider_reference: str | None = None,
    transfer_code: str | None = None,
) -> VendorPayout:
    from datetime import UTC, datetime

    payout.status = "completed"
    payout.provider_reference = provider_reference
    payout.transfer_code = transfer_code
    payout.paid_at = datetime.now(UTC)

    # Update ledger transaction to completed
    tx = await db.scalar(
        select(VendorTransaction).where(
            VendorTransaction.reference == f"PAYOUT-{payout.id.hex[:8].upper()}"
        )
    )
    if tx:
        tx.status = "completed"
        tx.provider_reference = provider_reference or transfer_code

    await db.commit()
    await db.refresh(payout)
    try:
        from app.tasks.email import send_vendor_payout_completed_notification
        send_vendor_payout_completed_notification.delay(str(payout.id))
    except Exception:
        pass
    return payout


# ── Vendor Verification (Phase 11) ─────────────────────────────────────────────
async def submit_verification_request(
    db: AsyncSession,
    vendor: Vendor,
    *,
    business_registration_number: str | None = None,
    tax_id: str | None = None,
    document_urls: list[str] | None = None,
    government_id_url: str | None = None,
    notes: str | None = None,
) -> VendorVerificationRequest:
    vendor.verification_status = "pending"

    req = VendorVerificationRequest(
        vendor_id=vendor.id,
        business_registration_number=business_registration_number,
        tax_id=tax_id,
        document_urls=document_urls or [],
        government_id_url=government_id_url,
        notes=notes,
        status="pending",
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return req


async def review_verification_request(
    db: AsyncSession,
    request_id: uuid.UUID,
    *,
    approved: bool,
    reviewer_id: uuid.UUID,
    admin_notes: str | None = None,
) -> VendorVerificationRequest:
    from datetime import UTC, datetime

    req = await db.get(VendorVerificationRequest, request_id)
    if not req:
        raise HTTPException(404, "Verification request not found.")

    vendor = await db.get(Vendor, req.vendor_id)
    if not vendor:
        raise HTTPException(404, "Vendor not found.")

    req.status = "approved" if approved else "rejected"
    req.admin_notes = admin_notes
    req.reviewed_by = reviewer_id
    req.reviewed_at = datetime.now(UTC)

    if approved:
        vendor.is_verified = True
        vendor.verification_status = "verified"
        vendor.verified_at = datetime.now(UTC)
        vendor.verification_notes = admin_notes
    else:
        vendor.is_verified = False
        vendor.verification_status = "rejected"
        vendor.verification_notes = admin_notes

    await db.commit()
    await db.refresh(req)
    return req

