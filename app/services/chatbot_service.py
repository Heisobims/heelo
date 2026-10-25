"""
Heelo AI Support & Knowledge Base Assistant Service.

Provides intelligent, context-aware responses to user and visitor queries
about the entire Heelo platform, including:
- Event creation, lifecycle, scheduling, and timezone support
- Multi-currency ticketing, payment fee models, promo codes, and waitlists
- Payment gateways (Paystack, Flutterwave, Stripe) and automated payouts
- Check-in app, Box Office QR scanning, offline sync, and Apple Wallet passes
- Vendor Marketplace (finding, hiring, quoting, milestone escrow payments)
- Marketing tools (Meta, Google, TikTok conversion pixels, abandoned checkout recovery, share cards)
- Corporate compliance (VAT/Tax invoices, PDF receipts via ReportLab)
- Subscription plans (Free, Growth, Pro, Enterprise) and features
- Live database grounding for active events and vendor categories
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, time, timedelta, UTC
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings

logger = structlog.get_logger()

# ── Known Locations ───────────────────────────────────────────────────────────

COMMON_LOCATIONS = [
    "lagos", "abuja", "port harcourt", "ibadan", "kano", "benin city", "enugu",
    "accra", "nairobi", "johannesburg", "cape town", "cairo", "kigali",
    "london", "manchester", "birmingham", "new york", "san francisco",
    "los angeles", "chicago", "houston", "atlanta", "toronto", "vancouver",
    "berlin", "paris", "amsterdam", "dubai", "singapore", "sydney",
    "lekki", "ikeja", "victoria island", "ikoyi", "yaba"
]


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


# ── Event Formatting Helpers ──────────────────────────────────────────────────

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


# ── Targeted Database Event Query ─────────────────────────────────────────────

async def query_database_events(
    db: AsyncSession,
    query: str,
    client_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Query the database for published events matching temporal expressions and location.
    """
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

    # Base query for active published events
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

    # Count total published events in database
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

        # Event overlaps with window
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
                # Check if there are events in other locations for this timeframe
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
        # No temporal expression specified
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


# ── Knowledge Base Corpus ─────────────────────────────────────────────────────

SYSTEM_KNOWLEDGE_PROMPT = """You are Heelo AI, the intelligent, friendly, and expert support assistant for Heelo.
Heelo is the modern all-in-one event ticketing, event intelligence, and vendor marketplace platform built for organizers and attendees worldwide, with deep multi-currency support (NGN, USD, GBP, EUR, KES, GHS, ZAR).

Your role is to answer questions from event organizers, ticket buyers, and vendors with precision, helpfulness, and clear guidance, similar to modern SaaS support assistants like Hostinger AI or Intercom.

Key Knowledge Points about Heelo:
1. Event Management:
   - Organizers can create, edit, schedule, and publish events at /org/[slug]/events/create.
   - Supports formats: In-person, Virtual (with live stream URLs), and Hybrid.
   - Features customizable registration forms, multi-speaker rosters, session agendas with tracks/stages, and sponsor tiers.
   - Private events can be password-protected or restricted to verified invite links.

2. Ticketing & Multi-Currency Economics:
   - Free Events: 100% free with unlimited tickets and zero platform fees, forever.
   - Paid Tickets: Tiered pricing (Free, General, VIP, Early Bird, Group).
   - Multi-Currency: Organizers can price tickets in NGN, USD, GBP, EUR, KES, GHS, ZAR.
   - Fee Model: By default, platform fees (3.5% + processing) are passed to the ticket buyer (fees_passed_to_buyer = true), so the organizer retains 100% of their face-value ticket revenue. Organizers can also choose to absorb fees.
   - Promo Codes: Discount codes (fixed or percentage), usage limits, and expiration dates.
   - Referral Discounts: Attendees can share unique "Refer a Friend" links for automatic discounts.
   - Waitlist: Built-in waitlist that automatically reserves spots and notifies next in line when tickets become available.

3. Payment Gateways & Automated Payouts:
   - Processors: Paystack, Flutterwave, Stripe Connect, and Stripe Direct.
   - Instant Subaccount Splits: On Paystack and Flutterwave, ticket revenue can split automatically at charge time directly into the organizer's bank account.
   - Payout System: Heelo processes automatic batch payouts with zero platform withholding. Organizers configure bank accounts at /org/[slug]/settings/payments.

4. Check-in, Box Office & Digital Wallet Passes:
   - Box Office: Live check-in scanner at /check-in with 5-second automatic background polling.
   - QR Codes: Signed cryptographic QR codes on every confirmed ticket.
   - Offline Mode: Check-in works offline via Service Worker caching.
   - Digital Passes: Attendees can download official Apple Wallet digital passes (.pkpass) directly from order confirmation.
   - Thermal Badges: Organizers can generate and print professional attendee name badges (/badges.pdf).

5. Vendor Marketplace (/vendors):
   - Organizers can discover and hire verified event professionals across 8 categories: Venues, Catering & Drinks, Photography & Video, Sound & DJ, Decor & Styling, Security & Bouncers, Event Hosts/MCs, Ushers & Protocol.
   - Request for Quote (RFQ) system with chat negotiation.
   - Escrow Payments: Funds are safely held in escrow and released upon milestone completion and fulfillment.
   - Booth Applications: Vendors can apply for exhibition booths on events (/events/[slug]/apply).

6. Marketing, Social Virality & Tracking:
   - Conversion Tracking Pixels: Organizers can configure Meta (Facebook) Pixel ID, Google Tag (GA4/GTM) ID, and TikTok Pixel ID in event settings to track PageView, ViewContent, and Purchase events.
   - Abandoned Checkout Recovery: Celery cron runs every 15 minutes to identify unpaid checkouts and send branded 1-click recovery emails.
   - Viral Share Cards: Attendees get vertical 1080x1920 Instagram Story share cards (/api/v1/events/[slug]/share-card/[id]) to post on social media.

7. Corporate Invoicing & VAT Compliance:
   - Organizers can configure VAT/Tax rate % and registered Tax ID.
   - Corporate checkout allows buyers to input Company Name, Tax ID, and Billing Address.
   - Generates official downloadable PDF tax invoices at /orders/[order_id]/invoice.pdf.

8. Subscription Plans & Pricing (/pricing):
   - Free ($0/month forever): Unlimited events, paid tickets, 1 seat, basic analytics.
   - Growth ($19/month or NGN 7,500/month): Custom branding, 3 seats, recurring events, CRM contact import, custom form fields, speaker agendas, 1,000 WhatsApp messages/month.
   - Pro ($49/month or NGN 25,000/month): Sponsor management, live polls & Q&A, advanced analytics, custom domain (e.g. events.yourbrand.com), 10 seats, 5,000 WhatsApp messages/month.
   - Enterprise: Dedicated manager, full white-label, SSO, unlimited custom domains & API keys.

9. Support & Contact:
   - Direct support email: hello@heelo.io
   - Community & Help: In-app support and knowledge base.

Guidelines for Responses:
- Never use emojis anywhere in your response.
- Never use em dashes in your response.
- Be warm, encouraging, concise, and structured.
- Use markdown bolding and bullet points for readability.
- Provide direct URLs (like /pricing, /events, /vendors) where relevant.
- When live database information is provided below, accurately cite the events found. If zero events matched the timeframe/location, state that clearly to the user.
"""


# ── Dynamic Database Grounding ────────────────────────────────────────────────

async def get_live_database_context(
    db: AsyncSession,
    query: str,
    client_context: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Fetch live data from the database matching the user's intent."""
    q_lower = query.lower()
    snippets = []

    # Run targeted database event search
    event_data = await query_database_events(db, query, client_context)

    if event_data.get("is_event_query"):
        matched = event_data.get("matched_events", [])
        other_temp = event_data.get("other_temporal_events", [])
        upcoming = event_data.get("upcoming_events", [])
        temp_lbl = event_data.get("temporal_label")
        loc = event_data.get("detected_location")

        lines = [f"Live Event Database Query Results for: '{query}'"]
        if temp_lbl:
            lines.append(f"Target Timeframe: {temp_lbl}")
        if loc:
            lines.append(f"Target Location: {loc} (Source: {event_data.get('location_source')})")

        if matched:
            lines.append(f"Matching Events Found in Database ({len(matched)}):")
            for ev in matched:
                lines.append(format_event_listing(ev))
        elif other_temp:
            lines.append(f"No events found in {loc} for {temp_lbl}. Other events in database for this timeframe:")
            for ev in other_temp:
                lines.append(format_event_listing(ev))
        elif upcoming:
            lines.append(f"No events scheduled for {temp_lbl or 'requested criteria'}. Upcoming events in database:")
            for ev in upcoming:
                lines.append(format_event_listing(ev))
        else:
            lines.append("Database has 0 published events matching this criteria.")

        snippets.append("\n".join(lines))

    # Check for vendor queries
    vendor_keywords = ["vendor", "caterer", "catering", "photographer", "dj", "security", "venue", "sound", "lighting", "hire"]
    if any(k in q_lower for k in vendor_keywords):
        snippets.append(
            "Heelo Vendor Marketplace Categories: Venues, Catering & Drinks, Photography & Video, "
            "Sound, Lighting & DJ, Decor & Styling, Security & Bouncers, Event Hosts/MCs, Ushers & Protocol. "
            "Organizers can explore vendors at /vendors or request custom quotes with escrow protection."
        )

    return "\n\n".join(snippets), event_data


# ── Rule-Based Intelligent Fallback Engine ─────────────────────────────────────

def get_rule_based_response(
    query: str,
    live_context: str = "",
    event_data: dict[str, Any] | None = None,
    client_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Intelligent fallback response engine that matches keywords and intents
    when ANTHROPIC_API_KEY is not configured or during offline operations.
    """
    q = query.lower().strip()

    # 1. Event Discovery & Temporal Intent (e.g. "this weekend", "in Lagos", "upcoming events")
    if event_data and event_data.get("is_event_query"):
        matched = event_data.get("matched_events", [])
        other_temp = event_data.get("other_temporal_events", [])
        upcoming = event_data.get("upcoming_events", [])
        temp_lbl = event_data.get("temporal_label")
        loc = event_data.get("detected_location")
        loc_src = event_data.get("location_source")
        total_db = event_data.get("total_db_events", 0)

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
            # 0 events in database
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

    # 2. Greetings & Identity
    if re.search(r"\b(hi|hello|hey|who are you|what is heelo|good morning|good evening)\b", q):
        reply = (
            "**Hello! I'm Heelo AI**, your platform assistant.\n\n"
            "Heelo is the modern all-in-one event ticketing, event intelligence, and vendor marketplace platform. "
            "I can help you with:\n\n"
            "- **Hosting an Event**: Creating events, scheduling agendas, and managing speakers.\n"
            "- **Ticketing & Multi-Currency**: Setting up free/paid tickets, promo codes, and fees.\n"
            "- **Instant Payouts & Gateways**: Paystack, Flutterwave, and Stripe Connect.\n"
            "- **Check-in & Digital Passes**: QR box office app and Apple Wallet passes.\n"
            "- **Vendor Marketplace**: Hiring caterers, photographers, security, and sound.\n"
            "- **Pricing & Plans**: Free forever tier, Growth ($19/mo), and Pro ($49/mo).\n\n"
            "What would you like to explore today?"
        )
        return {
            "reply": reply,
            "suggestions": ["How do I create an event?", "What are your fees?", "Can I hire vendors?", "What plans do you have?"]
        }

    # 3. Event Creation & Setup
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

    # 4. Pricing, Fees & Buyer Pass-through
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

    # 5. Payouts, Gateways & Bank Transfers
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

    # 6. Check-in, Box Office, QR codes & Apple Wallet
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

    # 7. Vendor Marketplace & Hiring
    if re.search(r"\b(vendor|vendors|cater|catering|photo|photographer|sound|dj|lighting|security|venue|hire|booth)\b", q):
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

    # 8. Ad Tracking Pixels (Meta, Google, TikTok)
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

    # 9. Abandoned Checkout Recovery
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

    # 10. Corporate Invoicing & VAT Compliance
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

    # 11. Support & Human Contact
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
    extra_events = f"\n\n{live_context}" if live_context and "Matching Events Found" in live_context else ""
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
        "suggestions": ["How do I create an event?", "What are your fees?", "Can I hire vendors?", "How do payouts work?"]
    }


# ── Main Chat Generation Function ─────────────────────────────────────────────

async def get_chatbot_reply(
    *,
    db: AsyncSession,
    user_message: str,
    chat_history: list[dict[str, str]] | None = None,
    client_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Generate an AI response using Anthropic Claude if configured,
    or the high-accuracy rule-based knowledge engine fallback.
    """
    clean_message = (user_message or "").strip()
    if not clean_message:
        return {
            "reply": "How can I help you with Heelo today? Ask me about creating events, ticketing, payouts, or hiring vendors!",
            "suggestions": ["How do I create an event?", "What are your fees?", "Can I hire vendors?"]
        }

    # Fetch live database context (e.g. real upcoming events, vendor categories)
    live_context = ""
    event_data: dict[str, Any] = {}
    try:
        live_context, event_data = await get_live_database_context(db, clean_message, client_context)
    except Exception as exc:
        logger.warning("chatbot.live_context_failed", error=str(exc))

    # If ANTHROPIC_API_KEY is configured, call Claude
    if settings.ANTHROPIC_API_KEY:
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

            system_content = SYSTEM_KNOWLEDGE_PROMPT
            if live_context:
                system_content += f"\n\nLive Database Information for this Query:\n{live_context}"

            messages: list[dict[str, str]] = []
            if chat_history:
                # Include up to 6 recent conversation turns
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
            )
            text_reply = response.content[0].text.strip()
            return {
                "reply": text_reply,
                "suggestions": [
                    "How do I create an event?",
                    "What are your fees?",
                    "How do payouts work?",
                    "Can I hire vendors?",
                ],
            }
        except Exception as exc:
            logger.warning("chatbot.anthropic_failed_fallback_to_rules", error=str(exc))
            # Fall back cleanly to the rule-based knowledge engine
            return get_rule_based_response(clean_message, live_context, event_data, client_context)

    # Offline / local development rule-based knowledge engine
    return get_rule_based_response(clean_message, live_context, event_data, client_context)
