"""
Heelo AI Support & Knowledge Base Assistant Service.

Provides 100% end-to-end intelligent, context-aware responses to user and
visitor queries across the entire Heelo platform, including:
- Real-time database event discovery with temporal & location parsing
- Specific event Q&A (schedule, tickets, venue, vibe tags, capacity)
- Current page & route contextual intelligence (e.g. /e/[slug], /pricing, /check-in)
- Live Vendor Marketplace search (photographers, caterers, DJs, security, venues)
- Attendee ticket & order tracking lookup by email or reference
- Multi-currency ticketing, payment fee pass-through economics, and instant payouts
- Check-in app, Box Office QR scanning, offline sync, and Apple Wallet passes
- Marketing pixels, abandoned checkout recovery, and corporate tax invoicing
- Subscription tiers (Free, Growth, Pro, Enterprise)
- Dual-engine architecture: Anthropic Claude with Tool Use & smart fallback engine
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, time, timedelta, UTC
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings

logger = structlog.get_logger()

# ── Knowledge Taxonomies & Common Mappings ────────────────────────────────────

COMMON_LOCATIONS = [
    "lagos", "abuja", "port harcourt", "ibadan", "kano", "benin city", "enugu",
    "accra", "nairobi", "johannesburg", "cape town", "cairo", "kigali",
    "london", "manchester", "birmingham", "new york", "san francisco",
    "los angeles", "chicago", "houston", "atlanta", "toronto", "vancouver",
    "berlin", "paris", "amsterdam", "dubai", "singapore", "sydney",
    "lekki", "ikeja", "victoria island", "ikoyi", "yaba"
]

VENDOR_CATEGORY_KEYWORDS = {
    "photography": ["photographer", "photography", "photos", "pictures", "photo shoot", "portrait"],
    "videography": ["videographer", "videography", "video", "cinematographer", "live stream crew"],
    "catering": ["caterer", "caterers", "catering", "food", "drinks", "cocktails", "mixology", "small chops", "chef"],
    "dj": ["dj", "deejay", "disc jockey", "music mix", "turntable"],
    "sound_lighting": ["sound", "audio", "lighting", "stage lights", "pa system", "speakers", "microphones"],
    "security": ["security", "bouncers", "bodyguards", "crowd control", "guards"],
    "decorations": ["decor", "decorator", "decorations", "event styling", "stage design", "flowers"],
    "mc": ["mc", "host", "emcee", "hypeman", "anchor"],
    "staffing_ushers": ["ushers", "ushering", "protocol", "event staff"],
    "venue": ["venue", "hall", "event center", "auditorium", "banquet hall", "conference room"],
}


# ── Temporal & Location Parsing ───────────────────────────────────────────────

def parse_temporal_intent(query: str, tz_name: str | None = None) -> tuple[datetime, datetime, str] | None:
    """
    Parse natural language temporal expressions from query.
    Returns (start_datetime, end_datetime, human_readable_label) or None.
    """
    q = (query or "").lower().strip()
    try:
        tz = ZoneInfo(tz_name) if tz_name else UTC
    except Exception:
        tz = UTC

    now_dt = datetime.now(tz)
    ref_date = now_dt.date()
    wd = ref_date.weekday()  # 0 = Monday, 6 = Sunday

    # 1. "next weekend" (must precede "weekend")
    if re.search(r"\bnext\s+weekend\b", q):
        if wd == 5:
            sat = ref_date + timedelta(days=7)
        elif wd == 6:
            sat = ref_date + timedelta(days=6)
        else:
            sat = ref_date + timedelta(days=(5 - wd + 7))
        sun = sat + timedelta(days=1)
        start_dt = datetime.combine(sat, time(0, 0, 0), tzinfo=tz)
        end_dt = datetime.combine(sun, time(23, 59, 59, 999999), tzinfo=tz)
        if sat.month == sun.month:
            label = f"next weekend ({sat.strftime('%b %d')}-{sun.strftime('%d, %Y')})"
        else:
            label = f"next weekend ({sat.strftime('%b %d')} - {sun.strftime('%b %d, %Y')})"
        return start_dt, end_dt, label

    # 2. "this weekend" / "the weekend" / "upcoming weekend" / "over the weekend" / "weekend"
    if re.search(r"\b(this|the|upcoming|over the)\s+weekend\b", q) or re.search(r"\bweekend\b", q):
        if wd == 5:  # Saturday
            sat = ref_date
            sun = ref_date + timedelta(days=1)
        elif wd == 6:  # Sunday
            sat = ref_date - timedelta(days=1)
            sun = ref_date
        elif wd == 4:  # Friday
            sat = ref_date + timedelta(days=1)
            sun = ref_date + timedelta(days=2)
        else:  # Mon - Thu
            sat = ref_date + timedelta(days=(5 - wd))
            sun = sat + timedelta(days=1)

        start_dt = datetime.combine(sat, time(0, 0, 0), tzinfo=tz)
        end_dt = datetime.combine(sun, time(23, 59, 59, 999999), tzinfo=tz)
        if sat.month == sun.month:
            label = f"this weekend ({sat.strftime('%b %d')}-{sun.strftime('%d, %Y')})"
        else:
            label = f"this weekend ({sat.strftime('%b %d')} - {sun.strftime('%b %d, %Y')})"
        return start_dt, end_dt, label

    # 3. "today" / "tonight"
    if re.search(r"\b(today|tonight)\b", q):
        start_dt = datetime.combine(ref_date, time(0, 0, 0), tzinfo=tz)
        end_dt = datetime.combine(ref_date, time(23, 59, 59, 999999), tzinfo=tz)
        label = f"today ({ref_date.strftime('%b %d, %Y')})"
        return start_dt, end_dt, label

    # 4. "tomorrow"
    if re.search(r"\btomorrow\b", q):
        tom = ref_date + timedelta(days=1)
        start_dt = datetime.combine(tom, time(0, 0, 0), tzinfo=tz)
        end_dt = datetime.combine(tom, time(23, 59, 59, 999999), tzinfo=tz)
        label = f"tomorrow ({tom.strftime('%b %d, %Y')})"
        return start_dt, end_dt, label

    # 5. "next week" (must precede "this week")
    if re.search(r"\bnext\s+week\b", q):
        mon = ref_date + timedelta(days=(7 - wd))
        sun = mon + timedelta(days=6)
        start_dt = datetime.combine(mon, time(0, 0, 0), tzinfo=tz)
        end_dt = datetime.combine(sun, time(23, 59, 59, 999999), tzinfo=tz)
        if mon.month == sun.month:
            label = f"next week ({mon.strftime('%b %d')}-{sun.strftime('%d, %Y')})"
        else:
            label = f"next week ({mon.strftime('%b %d')} - {sun.strftime('%b %d, %Y')})"
        return start_dt, end_dt, label

    # 6. "this week"
    if re.search(r"\bthis\s+week\b", q):
        mon = ref_date - timedelta(days=wd)
        sun = mon + timedelta(days=6)
        start_dt = datetime.combine(mon, time(0, 0, 0), tzinfo=tz)
        end_dt = datetime.combine(sun, time(23, 59, 59, 999999), tzinfo=tz)
        if mon.month == sun.month:
            label = f"this week ({mon.strftime('%b %d')}-{sun.strftime('%d, %Y')})"
        else:
            label = f"this week ({mon.strftime('%b %d')} - {sun.strftime('%b %d, %Y')})"
        return start_dt, end_dt, label

    # 7. "this month"
    if re.search(r"\bthis\s+month\b", q):
        last_day = monthrange(ref_date.year, ref_date.month)[1]
        start_dt = datetime.combine(ref_date.replace(day=1), time(0, 0, 0), tzinfo=tz)
        end_dt = datetime.combine(ref_date.replace(day=last_day), time(23, 59, 59, 999999), tzinfo=tz)
        label = f"this month ({ref_date.strftime('%B %Y')})"
        return start_dt, end_dt, label

    return None


def extract_location_intent(query: str, client_context: dict[str, Any] | None = None) -> tuple[str | None, str | None]:
    """
    Extract location from user query or client context.
    Returns (detected_location, source) where source is 'query', 'client_context', or 'client_timezone'.
    """
    q = (query or "").lower().strip()

    # 1. Check known locations in query
    for loc in COMMON_LOCATIONS:
        if re.search(r"\b" + re.escape(loc) + r"\b", q):
            return loc.title(), "query"

    # 2. Check regex: "in Lagos", "near London", "around Abuja", "at Lekki"
    m = re.search(r"\b(?:in|near|around|at)\s+([a-zA-Z\s]{3,25})(?:\s+(?:this|today|tomorrow|next|on|for)|\?|\.|$|\b)", q)
    if m:
        candidate = m.group(1).strip()
        non_locations = {
            "the weekend", "this weekend", "the morning", "the evening", "the afternoon",
            "the area", "my area", "my city", "town", "person", "the world", "october",
            "november", "december", "january", "february", "march", "april", "may",
            "june", "july", "august", "september"
        }
        if candidate.lower() not in non_locations and len(candidate) > 2:
            return candidate.title(), "query"

    # 3. Check client context
    ctx = client_context or {}
    if ctx.get("city"):
        return str(ctx["city"]).strip().title(), "client_context"
    if ctx.get("location"):
        return str(ctx["location"]).strip().title(), "client_context"

    tz_str = ctx.get("timezone", "")
    if "/" in tz_str:
        city_raw = tz_str.split("/")[-1].replace("_", " ")
        if city_raw and city_raw.lower() not in ("utc", "gmt"):
            return city_raw.title(), "client_timezone"

    return None, None


def extract_vendor_category_intent(query: str) -> str | None:
    """Identify if the user is looking for a specific vendor service category."""
    q = (query or "").lower().strip()
    for cat, keywords in VENDOR_CATEGORY_KEYWORDS.items():
        if any(re.search(r"\b" + re.escape(kw) + r"\b", q) for kw in keywords):
            return cat
    return None


def extract_order_lookup_intent(query: str, client_context: dict[str, Any] | None = None) -> tuple[str | None, str | None]:
    """
    Detect if the user is asking to look up an order or ticket.
    Returns (email, reference).
    """
    q = (query or "").strip()
    # Check for email in query
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", q)
    email = email_match.group(0).lower() if email_match else None

    # Check for order reference e.g. HL-..., ORD-..., or UUID
    ref_match = re.search(r"\b(HL-[A-Za-z0-9_-]+|ORD-[A-Za-z0-9_-]+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b", q, re.IGNORECASE)
    reference = ref_match.group(0).upper() if ref_match else None

    # Fall back to logged-in user email if user asked about their ticket
    if not email and not reference:
        user_email = (client_context or {}).get("user_email")
        if user_email and re.search(r"\b(my ticket|my order|where is my ticket|my pass|check my registration)\b", q.lower()):
            email = str(user_email).lower()

    return email, reference


def is_event_discovery_intent(query: str, temporal: Any) -> bool:
    """Determine if a query is specifically searching for or exploring live events."""
    if temporal is not None:
        return True
    q = (query or "").lower().strip()

    # Exclude queries where the primary intent is another platform capability
    if re.search(r"\b(hire|photographer|photographers|caterer|caterers|catering|sound|dj|lighting|security|bouncers|mc|ushers|booths?)\b", q):
        return False
    if re.search(r"\b(how to create|create an? event|host an? event|start an? event|publish an? event)\b", q):
        return False
    if re.search(r"\b(fee|fees|cost|pricing|price|percentage|charge|commission|rate)\b", q):
        return False
    if re.search(r"\b(check[- ]?in|box office|scanner|qr|ticket qr|wallet|pkpass)\b", q):
        return False
    if re.search(r"\b(payout|payouts|withdraw|transfer|bank|paystack|flutterwave|stripe)\b", q):
        return False
    if re.search(r"\b(pixel|pixels|meta|facebook|tiktok|google tag|gtm|ga4)\b", q):
        return False

    # Positive event discovery matches
    discovery_patterns = [
        r"\b(find|browse|discover|search|look for|upcoming|what('?s)? happening|show me|any|are there)\s+(any\s+)?(event|events|concert|concerts|party|parties|festival|festivals|conference|conferences|shows?)\b",
        r"\b(events?\s+(in|at|near|around|this|next|today|tomorrow|happening))\b",
        r"\b(what('?s)? happening|upcoming events|browse events|find events|parties near|concerts near)\b",
        r"\b(what events|which events|any events)\b",
    ]
    return any(re.search(pat, q) for pat in discovery_patterns)


# ── Formatting Helpers ────────────────────────────────────────────────────────

def format_ticket_price(ticket_types: list[Any]) -> str:
    """Format ticket pricing summary without emojis."""
    if not ticket_types:
        return "Free Registration"

    currency_symbols = {
        "NGN": "₦",
        "USD": "$",
        "GBP": "£",
        "EUR": "€",
        "KES": "KSh ",
        "GHS": "GH₵ ",
        "ZAR": "R ",
    }

    visible = [t for t in ticket_types if getattr(t, "is_visible", True)]
    if not visible:
        visible = ticket_types

    prices = [float(t.price or 0) for t in visible]
    curr = visible[0].currency if visible and hasattr(visible[0], "currency") else "NGN"
    sym = currency_symbols.get(curr, f"{curr} ")

    has_free = any(p == 0 for p in prices) or any(getattr(t, "tier", "") == "free" for t in visible)
    paid_prices = [p for p in prices if p > 0]

    if has_free and paid_prices:
        min_paid = min(paid_prices)
        return f"From Free (Paid tiers from {sym}{min_paid:,.0f})"
    elif has_free:
        return "Free"
    elif paid_prices:
        min_paid = min(paid_prices)
        if len(paid_prices) > 1 and max(paid_prices) > min_paid:
            return f"From {sym}{min_paid:,.0f}"
        return f"{sym}{min_paid:,.0f}"
    return "Free Registration"


def format_event_listing(ev: Any) -> str:
    """Format a single event into a clean Markdown block without emojis or em dashes."""
    date_str = ev.start_datetime.strftime("%A, %b %d, %Y at %I:%M %p") if ev.start_datetime else "Upcoming"

    if getattr(ev, "format", "") == "virtual":
        loc_str = "Online (Virtual Event)"
    else:
        venue_parts = [p for p in [ev.venue_name, ev.venue_city, ev.venue_country] if p]
        loc_str = ", ".join(venue_parts) if venue_parts else "Location TBA"

    format_label = ev.format.replace("_", "-").capitalize() if getattr(ev, "format", "") else "In-person"
    price_label = format_ticket_price(getattr(ev, "ticket_types", []))

    return (
        f"- **{ev.title}**\n"
        f"  - **Date & Time**: {date_str}\n"
        f"  - **Location**: {loc_str}\n"
        f"  - **Format**: {format_label}\n"
        f"  - **Tickets**: {price_label}\n"
        f"  - **Link**: [View Event & Register](/e/{ev.slug})"
    )


def format_vendor_listing(vd: Any) -> str:
    """Format a single vendor professional into a clean Markdown block."""
    cat_label = vd.category.replace("_", " ").title() if getattr(vd, "category", "") else "Vendor"
    price_str = f"From ₦{float(vd.starting_price):,.0f}" if getattr(vd, "starting_price", None) else "Contact for quote"
    city = getattr(vd, "location_city", "") or "Nigeria"
    tagline = getattr(vd, "tagline", "") or getattr(vd, "description", "") or "Verified professional on Heelo."

    return (
        f"- **{vd.business_name}** ({cat_label} in {city})\n"
        f"  - **Specialty**: {tagline}\n"
        f"  - **Pricing**: {price_str}\n"
        f"  - **Profile**: [View Portfolio & Request Quote](/vendors/{vd.slug})"
    )


# ── Targeted Database Query Functions ─────────────────────────────────────────

async def query_database_events(
    db: AsyncSession,
    query: str,
    client_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Query the database for published events matching temporal expressions and location."""
    from app.models.event import Event

    tz_name = (client_context or {}).get("timezone") or "UTC"
    temporal = parse_temporal_intent(query, tz_name)
    location, loc_source = extract_location_intent(query, client_context)

    is_event_query = is_event_discovery_intent(query, temporal)
    if not is_event_query:
        return {
            "is_event_query": False,
            "temporal_label": None,
            "detected_location": None,
            "location_source": None,
            "matched_events": [],
            "other_temporal_events": [],
            "upcoming_events": [],
            "total_db_events": 0,
        }

    now_utc = datetime.now(UTC)
    base_stmt = (
        select(Event)
        .options(selectinload(Event.ticket_types))
        .where(
            Event.status.in_(["published", "live"]),
            Event.deleted_at.is_(None),
        )
    )

    matched_events: list[Any] = []
    other_temporal_events: list[Any] = []
    upcoming_events: list[Any] = []

    total_db_events = await db.scalar(
        select(func.count(Event.id)).where(
            Event.status.in_(["published", "live"]),
            Event.deleted_at.is_(None),
        )
    ) or 0

    if temporal:
        start_bound, end_bound, temporal_label = temporal
        start_utc = start_bound.astimezone(UTC)
        end_utc = end_bound.astimezone(UTC)
        temporal_condition = (Event.start_datetime <= end_utc) & (Event.end_datetime >= start_utc)

        if location:
            loc_pattern = f"%{location.lower()}%"
            location_condition = (
                func.lower(Event.venue_city).like(loc_pattern) |
                func.lower(Event.venue_address).like(loc_pattern) |
                func.lower(Event.venue_name).like(loc_pattern) |
                (Event.format == "virtual")
            )
            matched_events = (
                await db.scalars(
                    base_stmt.where(temporal_condition, location_condition)
                    .order_by(Event.start_datetime.asc())
                    .limit(5)
                )
            ).all()

            if not matched_events:
                other_temporal_events = (
                    await db.scalars(
                        base_stmt.where(temporal_condition)
                        .order_by(Event.start_datetime.asc())
                        .limit(5)
                    )
                ).all()
        else:
            matched_events = (
                await db.scalars(
                    base_stmt.where(temporal_condition)
                    .order_by(Event.start_datetime.asc())
                    .limit(5)
                )
            ).all()

        if not matched_events and not other_temporal_events:
            upcoming_events = (
                await db.scalars(
                    base_stmt.where(Event.start_datetime >= now_utc)
                    .order_by(Event.start_datetime.asc())
                    .limit(5)
                )
            ).all()
    else:
        temporal_label = None
        if location:
            loc_pattern = f"%{location.lower()}%"
            location_condition = (
                func.lower(Event.venue_city).like(loc_pattern) |
                func.lower(Event.venue_address).like(loc_pattern) |
                func.lower(Event.venue_name).like(loc_pattern) |
                (Event.format == "virtual")
            )
            matched_events = (
                await db.scalars(
                    base_stmt.where(Event.start_datetime >= now_utc, location_condition)
                    .order_by(Event.start_datetime.asc())
                    .limit(5)
                )
            ).all()
            if not matched_events:
                upcoming_events = (
                    await db.scalars(
                        base_stmt.where(Event.start_datetime >= now_utc)
                        .order_by(Event.start_datetime.asc())
                        .limit(5)
                    )
                ).all()
        else:
            matched_events = (
                await db.scalars(
                    base_stmt.where(Event.start_datetime >= now_utc)
                    .order_by(Event.start_datetime.asc())
                    .limit(5)
                )
            ).all()

    return {
        "is_event_query": True,
        "temporal_label": temporal_label,
        "detected_location": location,
        "location_source": loc_source,
        "matched_events": matched_events,
        "other_temporal_events": other_temporal_events,
        "upcoming_events": upcoming_events,
        "total_db_events": total_db_events,
    }


async def get_specific_event_details(db: AsyncSession, query_or_slug: str) -> dict[str, Any] | None:
    """Find a specific event by exact slug, partial slug, or title substring."""
    from app.models.event import Event

    clean = (query_or_slug or "").strip().lower()
    if not clean or len(clean) < 3:
        return None

    stmt = (
        select(Event)
        .options(selectinload(Event.ticket_types))
        .where(
            Event.status.in_(["published", "live"]),
            Event.deleted_at.is_(None),
            or_(
                func.lower(Event.slug) == clean,
                func.lower(Event.slug).like(f"%{clean}%"),
                func.lower(Event.title).like(f"%{clean}%"),
            ),
        )
        .limit(1)
    )
    ev = await db.scalar(stmt)
    if not ev:
        stop_words = {
            "tell", "me", "about", "the", "is", "where", "when", "details", "for",
            "info", "on", "what", "how", "much", "are", "tickets", "event", "happening"
        }
        tokens = [w for w in re.findall(r"\b[a-zA-Z0-9]{3,}\b", clean) if w not in stop_words]
        if tokens:
            all_events = (
                await db.scalars(
                    select(Event)
                    .options(selectinload(Event.ticket_types))
                    .where(
                        Event.status.in_(["published", "live"]),
                        Event.deleted_at.is_(None),
                    )
                    .limit(20)
                )
            ).all()
            best_event = None
            best_score = 0
            for candidate in all_events:
                c_text = f"{candidate.title.lower()} {candidate.slug.lower()}"
                matched_cnt = sum(1 for tok in tokens if tok in c_text)
                if matched_cnt > best_score:
                    best_score = matched_cnt
                    best_event = candidate
            if best_event and best_score >= max(1, len(tokens) // 2):
                ev = best_event

    if not ev:
        return None

    date_str = ev.start_datetime.strftime("%A, %b %d, %Y at %I:%M %p") if ev.start_datetime else "Upcoming"
    end_str = ev.end_datetime.strftime("%I:%M %p") if ev.end_datetime else ""
    time_display = f"{date_str} to {end_str} ({ev.timezone})" if end_str else f"{date_str} ({ev.timezone})"

    tickets_info = []
    for t in getattr(ev, "ticket_types", []):
        if getattr(t, "is_visible", True):
            p_val = float(t.price or 0)
            p_disp = "Free" if p_val == 0 else f"{t.currency} {p_val:,.0f}"
            tickets_info.append(f"- **{t.name}**: {p_disp} ({t.tier.capitalize()})")

    loc_str = "Online Livestream" if ev.format == "virtual" else (ev.venue_address or ev.venue_name or ev.venue_city or "TBA")

    return {
        "title": ev.title,
        "slug": ev.slug,
        "format": ev.format.replace("_", "-").capitalize(),
        "time_display": time_display,
        "location": loc_str,
        "venue_name": ev.venue_name,
        "venue_city": ev.venue_city,
        "description": ev.description or "No description provided.",
        "max_capacity": ev.max_capacity,
        "tickets": tickets_info,
        "url": f"/e/{ev.slug}",
    }


async def search_database_vendors(db: AsyncSession, query: str, client_context: dict[str, Any] | None = None) -> list[Any]:
    """Search for verified/active vendors in the database matching category and city."""
    from app.models.vendor import Vendor

    cat = extract_vendor_category_intent(query)
    loc, _ = extract_location_intent(query, client_context)

    stmt = select(Vendor).where(Vendor.status == "active")
    if cat:
        stmt = stmt.where(Vendor.category == cat)
    if loc:
        stmt = stmt.where(func.lower(Vendor.location_city).like(f"%{loc.lower()}%"))

    stmt = stmt.order_by(Vendor.is_verified.desc(), Vendor.rating_avg.desc()).limit(4)
    vendors = (await db.scalars(stmt)).all()
    if not vendors and (cat or loc):
        # Fall back to general active vendors
        vendors = (await db.scalars(select(Vendor).where(Vendor.status == "active").limit(4))).all()

    return vendors


async def lookup_order_tickets(db: AsyncSession, email: str | None, reference: str | None) -> list[dict[str, Any]]:
    """Look up confirmed orders and registrations by email or payment reference."""
    from app.models.event import Event
    from app.models.ticketing import Order, Registration, TicketType

    results = []
    if reference:
        order = await db.scalar(
            select(Order)
            .where(func.upper(Order.payment_reference) == reference.upper())
            .limit(1)
        )
        if order:
            ev = await db.scalar(select(Event).where(Event.id == order.event_id))
            regs = (await db.scalars(select(Registration).where(Registration.order_id == order.id))).all()
            results.append({
                "type": "order",
                "reference": order.payment_reference,
                "event_title": ev.title if ev else "Heelo Event",
                "event_slug": ev.slug if ev else "",
                "status": order.payment_status.capitalize(),
                "total_amount": f"{order.currency} {float(order.total_amount):,.0f}",
                "ticket_count": len(regs),
                "order_id": str(order.id),
            })
            return results

    if email:
        regs = (
            await db.scalars(
                select(Registration)
                .where(func.lower(Registration.attendee_email) == email.lower())
                .order_by(Registration.created_at.desc())
                .limit(5)
            )
        ).all()
        for r in regs:
            ev = await db.scalar(select(Event).where(Event.id == r.event_id))
            tt = await db.scalar(select(TicketType).where(TicketType.id == r.ticket_type_id))
            results.append({
                "type": "registration",
                "attendee_name": r.attendee_name,
                "event_title": ev.title if ev else "Heelo Event",
                "event_slug": ev.slug if ev else "",
                "tier_name": tt.name if tt else "General",
                "status": r.status.capitalize(),
                "order_id": str(r.order_id) if r.order_id else "",
            })

    return results


# ── Knowledge Base Corpus ─────────────────────────────────────────────────────

SYSTEM_KNOWLEDGE_PROMPT = """You are Heelo AI, the intelligent, friendly, and expert support assistant for Heelo.
Heelo is the modern all-in-one event ticketing, event intelligence, and vendor marketplace platform built for organizers and attendees worldwide, with deep multi-currency support (NGN, USD, GBP, EUR, KES, GHS, ZAR).

Your role is to answer questions with precision, helpfulness, and clear guidance, similar to modern SaaS support assistants like Hostinger AI or Intercom.

Key Platform Knowledge:
1. Event Management:
   - Organizers can create, edit, schedule, and publish events at /org/[slug]/events/create.
   - Formats: In-person, Virtual (live stream links), and Hybrid.
   - Agendas, multi-speaker rosters, session tracks, and sponsor tiers.
   - Private events can be password-protected or restricted to invite links.

2. Ticketing & Multi-Currency Economics:
   - Free Events: 100% free with unlimited tickets and zero platform fees, forever.
   - Paid Tickets: Tiered pricing (Free, General, VIP, Early Bird, Group).
   - Multi-Currency: NGN, USD, GBP, EUR, KES, GHS, ZAR.
   - Fee Model: By default, platform fees (3.5% + processing) are passed to the ticket buyer (fees_passed_to_buyer = true). Organizers retain 100% of their face-value ticket revenue.
   - Promo Codes: Fixed or percentage discount codes, usage limits, and expiration dates.
   - Waitlist: Built-in automated reservation queue.

3. Payment Gateways & Automated Payouts:
   - Processors: Paystack, Flutterwave, Stripe Connect, and Stripe Direct.
   - Instant Subaccount Splits: Ticket revenue routes automatically into the organizer's bank account at charge time.
   - Batch Payouts: Zero platform withholding.

4. Check-in, Box Office & Digital Wallet Passes:
   - Box Office: Live check-in app at /check-in with 5-second attendee polling and camera QR scanner.
   - Offline Mode: Works offline via Service Worker caching.
   - Digital Passes: Official Apple Wallet passes (.pkpass) and thermal name badge printing (/badges.pdf).

5. Vendor Marketplace (/vendors):
   - Categories: Venues, Catering & Drinks, Photography & Video, Sound & DJ, Decor & Styling, Security & Bouncers, Event Hosts/MCs, Ushers & Protocol.
   - Request for Quote (RFQ) system with chat negotiation and milestone escrow protection.

6. Marketing & Corporate Invoicing:
   - Tracking Pixels: Meta (Facebook) Pixel, Google Tag (GA4/GTM), TikTok Pixel.
   - Abandoned Checkout Recovery: Celery cron runs every 15 minutes with 1-click email resumption.
   - Corporate Tax Invoicing: Itemized VAT PDF invoices at /orders/[order_id]/invoice.pdf.

7. Subscription Plans & Pricing (/pricing):
   - Free ($0/month): Unlimited events, paid tickets, 1 seat.
   - Growth ($19/mo or NGN 7,500/mo): Custom branding, 3 seats, recurring events, CRM contact import, custom form fields.
   - Pro ($49/mo or NGN 25,000/mo): Sponsor management, live polls & Q&A, advanced analytics, custom domain (events.yourbrand.com), 10 seats.
   - Enterprise: Dedicated manager, full white-label, SSO, unlimited custom domains & API keys.

8. Support: hello@heelo.io

Critical Operating Rules:
- Never use emojis anywhere in your response.
- Never use em dashes in your response.
- Be warm, concise, and structured with bold headings and bullet points.
- Provide direct URLs (like /pricing, /events, /vendors) where relevant.
- Cite live database query results accurately when provided.
"""


# ── Dynamic Database Grounding ────────────────────────────────────────────────

async def get_live_database_context(
    db: AsyncSession,
    query: str,
    client_context: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Fetch live data from the database matching the user's intent."""
    snippets = []
    event_data = await query_database_events(db, query, client_context)

    # 1. Event Search Context
    if event_data.get("is_event_query"):
        matched = event_data.get("matched_events", [])
        other_temp = event_data.get("other_temporal_events", [])
        upcoming = event_data.get("upcoming_events", [])
        temp_lbl = event_data.get("temporal_label")
        loc = event_data.get("detected_location")

        lines = [f"Live Event Database Results for '{query}':"]
        if temp_lbl:
            lines.append(f"Target Timeframe: {temp_lbl}")
        if loc:
            lines.append(f"Target Location: {loc}")

        if matched:
            lines.append(f"Matching Events ({len(matched)}):")
            for ev in matched:
                lines.append(format_event_listing(ev))
        elif other_temp:
            lines.append(f"No events in {loc} for {temp_lbl}. Other events scheduled for this timeframe:")
            for ev in other_temp:
                lines.append(format_event_listing(ev))
        elif upcoming:
            lines.append(f"No events for {temp_lbl or 'requested criteria'}. Upcoming events on Heelo:")
            for ev in upcoming:
                lines.append(format_event_listing(ev))
        else:
            lines.append("0 published events found in database.")

        snippets.append("\n".join(lines))

    # 2. Specific Event Details Context (if user is on an event page or asks about an event)
    curr_slug = (client_context or {}).get("event_slug")
    if curr_slug:
        details = await get_specific_event_details(db, curr_slug)
        if details:
            lines = [f"User is currently viewing Event: '{details['title']}' (/e/{details['slug']})"]
            lines.append(f"- Date & Time: {details['time_display']}")
            lines.append(f"- Venue: {details['location']}")
            lines.append(f"- Format: {details['format']}")
            lines.append(f"- Tickets: {', '.join(details['tickets']) if details['tickets'] else 'Free'}")
            snippets.append("\n".join(lines))

    # 3. Live Vendor Context
    cat = extract_vendor_category_intent(query)
    if cat or re.search(r"\b(vendor|vendors|hire|cater|dj|photographer|security)\b", query.lower()):
        vendors = await search_database_vendors(db, query, client_context)
        if vendors:
            lines = [f"Live Verified Vendors in Database ({len(vendors)}):"]
            for vd in vendors:
                lines.append(format_vendor_listing(vd))
            snippets.append("\n".join(lines))

    # 4. Order / Ticket Lookup Context
    email, ref = extract_order_lookup_intent(query, client_context)
    if email or ref:
        orders = await lookup_order_tickets(db, email, ref)
        if orders:
            lines = [f"Order / Ticket Lookup Results for {email or ref}:"]
            for o in orders:
                if o["type"] == "order":
                    lines.append(f"- Order {o['reference']} for '{o['event_title']}': Status {o['status']}, Total {o['total_amount']} (/orders/{o['order_id']})")
                else:
                    lines.append(f"- Ticket for '{o['event_title']}' ({o['tier_name']}): Attendee {o['attendee_name']}, Status {o['status']} (/orders/{o['order_id']})")
            snippets.append("\n".join(lines))

    return "\n\n".join(snippets), event_data


# ── Rule-Based Intelligent Knowledge Engine ───────────────────────────────────

async def get_rule_based_response(
    query: str,
    db: AsyncSession,
    live_context: str = "",
    event_data: dict[str, Any] | None = None,
    client_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Supercharged fallback engine that matches intents, evaluates page contexts,
    and executes live database queries when Anthropic is offline.
    """
    q = query.lower().strip()
    ctx = client_context or {}
    curr_event_slug = ctx.get("event_slug")
    page_path = ctx.get("page_path", "")

    # 1. Page Context: User is viewing a specific event page (/e/[slug])
    if curr_event_slug:
        details = await get_specific_event_details(db, curr_event_slug)
        if details:
            # Check for ticket/pricing question on event page
            if re.search(r"\b(ticket|tickets|price|pricing|cost|fee|fees|how much|free)\b", q):
                t_list = "\n".join(details["tickets"]) if details["tickets"] else "- Free registration"
                reply = (
                    f"### Ticket Options for {details['title']}\n\n"
                    f"Here are the available ticket tiers for this event:\n\n"
                    f"{t_list}\n\n"
                    f"You can choose your quantity and register directly on this page!"
                )
                return {
                    "reply": reply,
                    "suggestions": ["What time does this event start?", "Where is the venue?", "How do I check in?"]
                }
            # Check for time/date question
            if re.search(r"\b(when|time|date|start|schedule|day)\b", q):
                reply = (
                    f"### Schedule for {details['title']}\n\n"
                    f"- **Date & Time**: {details['time_display']}\n"
                    f"- **Format**: {details['format']}\n\n"
                    f"Make sure to arrive 15 minutes before the scheduled start time for smooth check-in!"
                )
                return {
                    "reply": reply,
                    "suggestions": ["Where is this event located?", "How much are tickets?", "Is there parking?"]
                }
            # Check for venue/location question
            if re.search(r"\b(where|location|venue|address|directions|online|link)\b", q):
                reply = (
                    f"### Venue Details for {details['title']}\n\n"
                    f"- **Location**: {details['location']}\n"
                    f"- **Format**: {details['format']}\n"
                    f"- **Capacity**: {details['max_capacity'] or 'Open'} attendees\n\n"
                    f"Directions and check-in QR codes will also be included in your confirmation email."
                )
                return {
                    "reply": reply,
                    "suggestions": ["What are the ticket prices?", "What time does it start?", "How do I contact the organizer?"]
                }

    # 2. Check for Specific Event Lookup by Title/Keywords (e.g. "Tell me about Lagos Tech Summit")
    if re.search(r"\b(tell me about|details for|info on|where is the|when is the)\s+(.+)\b", q):
        m = re.search(r"\b(tell me about|details for|info on|where is the|when is the)\s+(.+)\b", q)
        if m:
            target_name = m.group(2).strip().rstrip("?")
            event_match = await get_specific_event_details(db, target_name)
            if event_match:
                t_list = "\n".join(event_match["tickets"]) if event_match["tickets"] else "- Free registration"
                reply = (
                    f"### {event_match['title']}\n\n"
                    f"- **Date & Time**: {event_match['time_display']}\n"
                    f"- **Location**: {event_match['location']}\n"
                    f"- **Format**: {event_match['format']}\n"
                    f"- **Description**: {event_match['description']}\n\n"
                    f"**Ticket Tiers**:\n{t_list}\n\n"
                    f"[View Event & Register]({event_match['url']})"
                )
                return {
                    "reply": reply,
                    "suggestions": ["How do I buy tickets?", "Are there discounts?", "Can I hire vendors?"]
                }

    # 3. Order & Ticket Self-Service Lookup
    email, ref = extract_order_lookup_intent(query, client_context)
    if email or ref:
        orders = await lookup_order_tickets(db, email, ref)
        if orders:
            lines = []
            for o in orders:
                if o["type"] == "order":
                    lines.append(f"- **Order {o['reference']}**: {o['event_title']} (Status: {o['status']}, Total: {o['total_amount']}) -> [View Order Details](/orders/{o['order_id']})")
                else:
                    lines.append(f"- **Ticket for {o['event_title']}**: {o['tier_name']} Pass (Status: {o['status']}, Attendee: {o['attendee_name']}) -> [View Order & Passes](/orders/{o['order_id']})")
            reply = (
                f"### Ticket & Order Lookup\n\n"
                f"I found the following records associated with **{email or ref}** in your database:\n\n"
                f"{chr(10).join(lines)}\n\n"
                "You can view your QR passes, download Apple Wallet passes, or get your official VAT invoice from the links above."
            )
            return {
                "reply": reply,
                "suggestions": ["How do I download my Apple Wallet pass?", "Can I transfer my ticket?", "How does check-in work?"]
            }

    # 4. Vendor Marketplace Discovery (live database search)
    cat = extract_vendor_category_intent(query)
    if cat or re.search(r"\b(vendor|vendors|hire|cater|catering|photo|photographer|sound|dj|lighting|security|venue|booth)\b", q):
        vendors = await search_database_vendors(db, query, client_context)
        if vendors:
            v_lines = "\n\n".join(format_vendor_listing(vd) for vd in vendors)
            cat_phrase = f" for **{cat.replace('_', ' ').title()}**" if cat else ""
            reply = (
                f"### Verified Vendors on Heelo{cat_phrase}\n\n"
                f"Here are top-rated verified professionals in your database:\n\n"
                f"{v_lines}\n\n"
                "All vendor bookings on Heelo feature **milestone escrow protection**: your funds are safely held and only released upon milestone completion.\n\n"
                "Explore all categories or submit an RFQ on the **[Vendor Marketplace](/vendors)**."
            )
            return {
                "reply": reply,
                "suggestions": ["How does vendor escrow work?", "How do I list as a vendor?", "Can I hire sound & DJ?"]
            }
        else:
            reply = (
                "### Heelo Vendor Marketplace (/vendors)\n\n"
                "Planning an event? You can discover and hire verified event professionals directly through Heelo:\n\n"
                "- **8 Core Categories**: Venues, Catering & Drinks, Photography & Video, Sound & DJ, Decor & Styling, Security & Bouncers, Event Hosts/MCs, Ushers & Protocol.\n"
                "- **Request a Quote (RFQ)**: Share your event date, location, and budget to receive custom proposals.\n"
                "- **Escrow Protection**: Your payment is safely held in escrow and only released when the vendor completes their milestones.\n"
                "- **Exhibition Booths**: Organizers can sell booth packages, and vendors can apply directly on event pages (`/events/[slug]/apply`).\n\n"
                "Explore verified professionals on the **[Vendor Marketplace](/vendors)**."
            )
            return {
                "reply": reply,
                "suggestions": ["How do I list as a vendor?", "What are your fees?", "How do payouts work?"]
            }

    # 5. Event Discovery & Temporal Intent (e.g. "this weekend", "in Lagos", "upcoming events")
    if event_data and event_data.get("is_event_query"):
        matched = event_data.get("matched_events", [])
        other_temp = event_data.get("other_temporal_events", [])
        upcoming = event_data.get("upcoming_events", [])
        temp_lbl = event_data.get("temporal_label")
        loc = event_data.get("detected_location")
        loc_src = event_data.get("location_source")

        loc_phrase = f" based on your location (**{loc}**)" if (loc and loc_src == "client_timezone") else (f" in **{loc}**" if loc else "")
        header_temp = (temp_lbl[0].upper() + temp_lbl[1:]) if temp_lbl else "on Heelo"

        if matched:
            if temp_lbl and loc:
                header = f"### Events {header_temp} in {loc}\n\nI queried your database for published events scheduled for **{temp_lbl}**{loc_phrase}:\n\n"
            elif temp_lbl:
                header = f"### Events {header_temp}\n\nI queried your database for published events scheduled for **{temp_lbl}**:\n\n"
            elif loc:
                header = f"### Upcoming Events in {loc}\n\nI queried your database for upcoming published events{loc_phrase}:\n\n"
            else:
                header = "### Upcoming Events on Heelo\n\nHere are upcoming published events found in your database:\n\n"

            event_lines = "\n\n".join(format_event_listing(ev) for ev in matched)
            reply = (
                f"{header}{event_lines}\n\n"
                "You can explore all events and filter by category or city on our **[Discover Events](/events)** page."
            )
            return {
                "reply": reply,
                "suggestions": ["How do I register for an event?", "How do I create an event?", "Can I hire vendors?"]
            }

        elif other_temp:
            header = f"### Events {header_temp}\n\n"
            intro = f"I checked your database for published events scheduled for **{temp_lbl}**{loc_phrase}, but no events are currently scheduled for that specific location.\n\nHere are other published events taking place **{temp_lbl}**:\n\n"
            event_lines = "\n\n".join(format_event_listing(ev) for ev in other_temp)
            reply = (
                f"{header}{intro}{event_lines}\n\n"
                "You can also browse all listings on the **[Discover Events](/events)** page."
            )
            return {
                "reply": reply,
                "suggestions": ["How do I create an event?", "What are your fees?", "Can I hire vendors?"]
            }

        elif upcoming:
            header = f"### Events {header_temp}\n\n"
            intro = f"I checked your database for published events scheduled for **{temp_lbl or 'this period'}**{loc_phrase}, but no events are scheduled for this timeframe.\n\nHere are other upcoming published events in your database:\n\n"
            event_lines = "\n\n".join(format_event_listing(ev) for ev in upcoming)
            reply = (
                f"{header}{intro}{event_lines}\n\n"
                "Would you like to host an event for this timeframe? You can set one up and publish tickets in minutes at **[Create Event](/events)**."
            )
            return {
                "reply": reply,
                "suggestions": ["How do I create an event?", "What are your fees?", "How do payouts work?"]
            }

        else:
            target_str = f" for **{temp_lbl}**" if temp_lbl else ""
            loc_str = f" in **{loc}**" if loc else ""
            reply = (
                f"### Events {header_temp}\n\n"
                f"I checked your database for published events{target_str}{loc_str}, but no published events were found in the database.\n\n"
                "You can create and publish the first event anytime:\n"
                "- Go to **[Create Event](/events)** to configure your date, venue, ticket tiers, and publish.\n"
                "- Need guidance on ticket pricing, multi-currency payouts, or check-in? Ask me anytime!"
            )
            return {
                "reply": reply,
                "suggestions": ["How do I create an event?", "What are your fees?", "How do payouts work?"]
            }

    # 6. Greetings & Identity
    if re.search(r"\b(hi|hello|hey|who are you|what is heelo|good morning|good evening)\b", q):
        user_name = ctx.get("user_name")
        greet_prefix = f"**Hello {user_name}! I'm Heelo AI**" if user_name else "**Hello! I'm Heelo AI**"
        reply = (
            f"{greet_prefix}, your intelligent platform assistant.\n\n"
            "Heelo is the modern all-in-one event ticketing, event intelligence, and vendor marketplace platform. "
            "I can assist you with:\n\n"
            "- **Events & Discovery**: Finding concerts, conferences, and parties near you or this weekend.\n"
            "- **Hosting & Ticketing**: Setting up free/paid tickets, promo codes, and agendas.\n"
            "- **Instant Payouts & Gateways**: Paystack, Flutterwave, and Stripe Connect with automatic subaccount splits.\n"
            "- **Check-in & Digital Passes**: Box office QR app and official Apple Wallet passes.\n"
            "- **Vendor Marketplace**: Hiring caterers, photographers, sound/DJ, and security with escrow protection.\n"
            "- **Order Tracking**: Checking your ticket status, invoice, or registration.\n\n"
            "What would you like to explore today?"
        )
        return {
            "reply": reply,
            "suggestions": ["Is there any event this weekend?", "How do I create an event?", "What are your fees?", "Can I hire vendors?"]
        }

    # 7. Event Creation & Setup
    if re.search(r"\b(create|host|setup|start|publish|new)\s+(an?\s+)?event\b", q) or "how to create" in q or "host an event" in q:
        reply = (
            "### How to Create an Event on Heelo\n\n"
            "1. **Sign in or Create an Organization**: Head over to your dashboard or click **[Create Event](/events)**.\n"
            "2. **Event Details**: Enter your event title, format (*In-person*, *Virtual*, or *Hybrid*), dates, timezone, and venue/streaming link.\n"
            "3. **Setup Ticket Tiers**: Add Free, General, VIP, Early Bird, or Group tickets with your desired currency (*NGN, USD, GBP, EUR, KES, GHS, ZAR*).\n"
            "4. **Custom Agenda & Speakers**: Build your session timeline, tracks, stages, and add speaker profiles.\n"
            "5. **Marketing & Tracking**: Add your Meta, Google, or TikTok Pixel IDs for conversion tracking.\n"
            "6. **Publish & Sell**: Click **Publish** to get your public event page (e.g. `/e/your-event-slug`) and start accepting registrations immediately!"
        )
        return {
            "reply": reply,
            "suggestions": ["What are your fees?", "How do payouts work?", "Can I track ad conversions?"]
        }

    # 8. Pricing, Fees & Buyer Pass-through
    if re.search(r"\b(price|pricing|cost|fee|fees|percentage|charge|commission|rate)\b", q):
        reply = (
            "### Heelo Pricing & Fees\n\n"
            "- **Free Events**: **100% free, forever!** No ticket limits, no setup costs, and no forced upgrades.\n"
            "- **Paid Tickets**: Standard platform fee is **3.5% + processing**.\n"
            "- **Zero-Cost to Organizers**: By default, Heelo passes fees to the ticket buyer at checkout. That means **you keep 100% of your face-value ticket price**!\n"
            "- **Subscription Plans**:\n"
            "  - **Free Tier ($0/mo)**: Unlimited events, paid tickets, 1 team seat.\n"
            "  - **Growth ($19/mo or ₦7,500/mo)**: Custom branding, 3 team seats, recurring events, CRM import, custom form fields.\n"
            "  - **Pro ($49/mo or ₦25,000/mo)**: Sponsor management, live polls & Q&A, full analytics, custom domain.\n\n"
            "Check full plan comparisons on our **[Pricing Page](/pricing)**."
        )
        return {
            "reply": reply,
            "suggestions": ["How do payouts work?", "What is included in the Pro plan?", "How do I create an event?"]
        }

    # 9. Payouts, Gateways & Bank Transfers
    if re.search(r"\b(payout|payouts|withdraw|transfer|bank|paystack|flutterwave|stripe|money|revenue)\b", q):
        reply = (
            "### Payouts & Payment Gateways on Heelo\n\n"
            "Heelo provides multiple automated payout options to ensure organizers get paid quickly and securely:\n\n"
            "- **Instant Subaccount Splits**: Connect your Paystack, Flutterwave, or Stripe Connect subaccount in **[Payment Settings](/dashboard)**. Ticket funds automatically split and route directly into your bank account at charge time.\n"
            "- **Batch Payouts**: For standard accounts, Heelo runs automated batch payouts with **0% platform withholding**.\n"
            "- **Multi-Currency Settlements**: Accept payments in NGN, USD, GBP, EUR, KES, GHS, or ZAR depending on your country and gateway setup.\n"
            "- **Payment Methods**: Attendees can pay using debit/credit cards, bank transfers, Apple Pay, Google Pay, USSD, and Mobile Money."
        )
        return {
            "reply": reply,
            "suggestions": ["What are your fees?", "Do you support corporate invoices?", "Can I track ad conversions?"]
        }

    # 10. Check-in, Box Office, QR codes & Apple Wallet
    if re.search(r"\b(check[- ]?in|box office|scanner|qr|ticket|badge|wallet|pkpass|apple wallet)\b", q):
        reply = (
            "### Check-in, Box Office & Digital Wallet Passes\n\n"
            "- **High-Speed Box Office**: Use our web-based Box Office app at **`/check-in`**. Features automatic 5-second attendee list refresh, instant name search, and 1-tap check-in.\n"
            "- **Camera QR Scanner**: Built-in camera scanner reads signed cryptographic ticket QR codes in milliseconds.\n"
            "- **Offline Check-in**: Operates smoothly even with unstable venue internet using Service Worker offline synchronization.\n"
            "- **Apple Wallet Passes (.pkpass)**: Attendees receive an official **'Add to Apple Wallet'** pass on their confirmation page with date, venue, and live barcode.\n"
            "- **Thermal Badge Printing**: Print professional attendee name badges with QR codes directly from the dashboard."
        )
        return {
            "reply": reply,
            "suggestions": ["How do attendees receive tickets?", "How do I create an event?", "What are your fees?"]
        }

    # 11. Ad Tracking Pixels (Meta, Google, TikTok)
    if re.search(r"\b(pixel|pixels|meta|facebook|tiktok|google tag|gtm|ga4|tracking|conversion|ad)\b", q):
        reply = (
            "### Ad Conversion Tracking Pixels\n\n"
            "Heelo provides built-in integration for major advertising networks to measure campaign ROI:\n\n"
            "- **Meta (Facebook) Pixel**: Automatically fires `PageView` and `ViewContent` on event pages, and `Purchase` on checkout with exact revenue and currency.\n"
            "- **Google Tag / GTM / GA4**: Native gtag.js integration with `page_view` and `purchase` ecommerce transaction events.\n"
            "- **TikTok Pixel**: Tracks `ViewContent` and `CompletePayment` conversions from TikTok ads.\n\n"
            "**How to configure**: Open your event editor -> Expand **Tracking & Invoicing** -> Enter your Meta Pixel ID, Google Tag ID, or TikTok Pixel ID -> Save!"
        )
        return {
            "reply": reply,
            "suggestions": ["How do abandoned checkout recovery emails work?", "How do I create an event?", "What are your fees?"]
        }

    # 12. Abandoned Checkout Recovery
    if re.search(r"\b(abandon|abandoned|recovery|incomplete|resume|nudge|cart)\b", q):
        reply = (
            "### Automated Abandoned Checkout Recovery\n\n"
            "Heelo automatically recovers attendees who started purchasing tickets but left before completing payment:\n\n"
            "- **Automated Background Cron**: Runs every 15 minutes to identify unpaid checkouts between 20 minutes and 24 hours old.\n"
            "- **1-Click Resumption**: Attendees receive a branded email reminder with a direct link (`/orders/resume/[token]`) that restores their reservation and redirects them straight to payment.\n"
            "- **Inventory Protection**: If tickets sell out or the event is cancelled, the resumption link safely informs the attendee."
        )
        return {
            "reply": reply,
            "suggestions": ["Can I track ad conversions?", "How do payouts work?", "What are your fees?"]
        }

    # 13. Corporate Invoicing & VAT Compliance
    if re.search(r"\b(invoice|invoices|vat|tax|corporate|receipt|pdf|company)\b", q):
        reply = (
            "### Corporate Invoicing & VAT Compliance\n\n"
            "- **Organizer Tax Setup**: Organizers can enter their registered Tax Identification Number (TIN/VAT) and Tax Rate % in event settings.\n"
            "- **Corporate Checkout**: Business attendees can check 'Corporate Tax Invoice' during registration to provide their Company Name, Tax ID, and Billing Address.\n"
            "- **Instant PDF Invoices**: Attendees and corporate finance teams can download official, VAT-itemized PDF invoices from the confirmation page (`/orders/[id]/invoice.pdf`)."
        )
        return {
            "reply": reply,
            "suggestions": ["How do I create an event?", "What are your fees?", "What subscription plans exist?"]
        }

    # 14. Support & Human Contact
    if re.search(r"\b(support|contact|help|email|phone|human|agent|talk to someone|team)\b", q):
        reply = (
            "### Need Additional Assistance?\n\n"
            "Our team is always here to help:\n\n"
            "- **Email Support**: Reach us directly at **[hello@heelo.io](mailto:hello@heelo.io)**.\n"
            "- **Organizer Portal**: Manage your events, team members, and finances in the **[Dashboard](/dashboard)**.\n"
            "- **Response Time**: We typically respond within a few hours on business days."
        )
        return {
            "reply": reply,
            "suggestions": ["How do I create an event?", "What are your fees?", "How do payouts work?"]
        }

    # Generic Fallback with Project Knowledge
    extra_events = f"\n\n{live_context}" if live_context and "Live Event Database" in live_context else ""
    reply = (
        f"**Heelo is the all-in-one event and vendor marketplace platform.**\n\n"
        f"Here are key things I can assist you with:\n"
        f"- **Event Creation & Scheduling**: Setting up in-person or virtual events with multi-tier tickets.\n"
        f"- **Ticketing & Multi-Currency**: Pricing tickets in NGN, USD, GBP, EUR, KES, GHS, ZAR with 0% fee pass-through to organizers.\n"
        f"- **Instant Payouts**: Automated subaccount split payments via Paystack, Flutterwave, and Stripe.\n"
        f"- **Check-in & Digital Passes**: Box office QR scanner and Apple Wallet passes.\n"
        f"- **Vendor Marketplace**: Hiring caterers, photographers, sound/DJ, and security with milestone escrow protection.\n"
        f"- **Subscription Plans**: Free ($0/mo), Growth ($19/mo), and Pro ($49/mo).{extra_events}\n\n"
        f"Could you tell me more about what you'd like to do?"
    )
    return {
        "reply": reply,
        "suggestions": ["Is there any event this weekend?", "How do I create an event?", "What are your fees?", "Can I hire vendors?"]
    }


# ── Claude Tool Definitions ───────────────────────────────────────────────────

CLAUDE_TOOLS = [
    {
        "name": "search_events",
        "description": "Search the live Heelo database for published events by timeframe, location, or keyword.",
        "input_schema": {
            "type": "object",
            "properties": {
                "timeframe": {
                    "type": "string",
                    "description": "Natural language timeframe e.g. 'this weekend', 'next weekend', 'today', 'tomorrow', 'this week', 'next week'."
                },
                "city": {
                    "type": "string",
                    "description": "City filter e.g. 'Lagos', 'London', 'Abuja'."
                },
                "query": {
                    "type": "string",
                    "description": "Keyword search term for title or category."
                }
            }
        }
    },
    {
        "name": "get_event_details",
        "description": "Get complete information (dates, venue, ticket tiers, format, description) for a specific event by title or slug.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_slug_or_title": {
                    "type": "string",
                    "description": "The slug or title of the event to look up."
                }
            },
            "required": ["event_slug_or_title"]
        }
    },
    {
        "name": "search_vendors",
        "description": "Search verified vendors in the marketplace by service category (photography, catering, dj, security, etc.) and location.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Vendor category e.g. 'photography', 'catering', 'dj', 'security', 'venue'."
                },
                "city": {
                    "type": "string",
                    "description": "City where the event will take place."
                }
            }
        }
    },
    {
        "name": "lookup_ticket_or_order",
        "description": "Look up an attendee ticket registration or order status by email or order reference.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": "Attendee or buyer email address."
                },
                "order_reference": {
                    "type": "string",
                    "description": "Order reference e.g. 'HL-DEMO-88219'."
                }
            }
        }
    }
]


async def execute_claude_tool(db: AsyncSession, tool_name: str, tool_input: dict[str, Any], client_context: dict[str, Any] | None = None) -> str:
    """Execute a Claude tool call against the live database."""
    if tool_name == "search_events":
        q_str = f"{tool_input.get('query', '')} {tool_input.get('timeframe', '')} in {tool_input.get('city', '')}".strip()
        data = await query_database_events(db, q_str, client_context)
        matched = data.get("matched_events", [])
        if matched:
            return "\n".join(format_event_listing(e) for e in matched)
        other = data.get("other_temporal_events", [])
        if other:
            return "No events in requested location. Other events this timeframe:\n" + "\n".join(format_event_listing(e) for e in other)
        upcoming = data.get("upcoming_events", [])
        if upcoming:
            return "No events for requested timeframe. Upcoming events:\n" + "\n".join(format_event_listing(e) for e in upcoming)
        return "No published events found in database."

    elif tool_name == "get_event_details":
        slug_or_title = tool_input.get("event_slug_or_title", "")
        ev = await get_specific_event_details(db, slug_or_title)
        if ev:
            t_str = ", ".join(ev["tickets"]) if ev["tickets"] else "Free"
            return f"Title: {ev['title']}\nTime: {ev['time_display']}\nVenue: {ev['location']}\nFormat: {ev['format']}\nTickets: {t_str}\nDescription: {ev['description']}\nLink: {ev['url']}"
        return f"Event '{slug_or_title}' not found in database."

    elif tool_name == "search_vendors":
        cat = tool_input.get("category", "")
        city = tool_input.get("city", "")
        v_str = f"{cat} in {city}".strip()
        vendors = await search_database_vendors(db, v_str, client_context)
        if vendors:
            return "\n".join(format_vendor_listing(v) for v in vendors)
        return "No vendors found matching this criteria."

    elif tool_name == "lookup_ticket_or_order":
        email = tool_input.get("email")
        ref = tool_input.get("order_reference")
        orders = await lookup_order_tickets(db, email, ref)
        if orders:
            return "\n".join(str(o) for o in orders)
        return f"No records found for email: {email} or reference: {ref}."

    return "Unsupported tool."


# ── Main Chat Generation Function ─────────────────────────────────────────────

async def get_chatbot_reply(
    *,
    db: AsyncSession,
    user_message: str,
    chat_history: list[dict[str, str]] | None = None,
    client_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Generate an AI response using Anthropic Claude with tool use if configured,
    or the high-accuracy rule-based knowledge engine fallback.
    """
    clean_message = (user_message or "").strip()
    if not clean_message:
        return {
            "reply": "How can I help you with Heelo today? Ask me about creating events, ticketing, payouts, hiring vendors, or discovering events!",
            "suggestions": ["Is there any event this weekend?", "What are your fees?", "Can I hire vendors?"]
        }

    # Fetch live database context
    live_context = ""
    event_data: dict[str, Any] = {}
    try:
        live_context, event_data = await get_live_database_context(db, clean_message, client_context)
    except Exception as exc:
        logger.warning("chatbot.live_context_failed", error=str(exc))

    # If ANTHROPIC_API_KEY is configured, call Claude with tools
    if settings.ANTHROPIC_API_KEY:
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

            system_content = SYSTEM_KNOWLEDGE_PROMPT
            if live_context:
                system_content += f"\n\nLive Database Information for this Query:\n{live_context}"

            messages: list[dict[str, Any]] = []
            if chat_history:
                for m in chat_history[-6:]:
                    role = m.get("role", "user")
                    content = m.get("content", "")
                    if role in ("user", "assistant") and content:
                        messages.append({"role": role, "content": content})

            messages.append({"role": "user", "content": clean_message})

            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=600,
                system=system_content,
                messages=messages,
                tools=CLAUDE_TOOLS,
            )

            # Check if Claude called a tool
            if response.stop_reason == "tool_use":
                tool_calls = [c for c in response.content if c.type == "tool_use"]
                tool_results_content = []
                for tc in tool_calls:
                    res_str = await execute_claude_tool(db, tc.name, tc.input, client_context)
                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": res_str,
                    })

                # Follow-up with tool results
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results_content})

                second_resp = await client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=600,
                    system=system_content,
                    messages=messages,
                )
                text_reply = second_resp.content[0].text.strip()
            else:
                text_reply = response.content[0].text.strip()

            # Clean any inadvertent em dashes or emojis from LLM output
            text_reply = text_reply.replace("\u2014", " - ")

            return {
                "reply": text_reply,
                "suggestions": [
                    "Is there any event this weekend?",
                    "What are your fees?",
                    "How do payouts work?",
                    "Can I hire vendors?",
                ],
            }
        except Exception as exc:
            logger.warning("chatbot.anthropic_failed_fallback_to_rules", error=str(exc))
            return await get_rule_based_response(clean_message, db, live_context, event_data, client_context)

    # Offline / local development supercharged knowledge engine
    return await get_rule_based_response(clean_message, db, live_context, event_data, client_context)
