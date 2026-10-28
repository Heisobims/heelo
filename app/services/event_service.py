from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import structlog
from slugify import slugify
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.event import Event, EventCategory, event_category_link
from app.models.organization import Organization
from app.schemas.event import DEFAULT_SECTION_ORDER, EventCreateRequest, EventUpdateRequest
from app.utils.cache import cache_get, cache_set

logger = structlog.get_logger()


def get_effective_section_order(event: Event) -> list[dict]:
    """The event's saved section_order, with any section keys it's missing
    (e.g. added to DEFAULT_SECTION_ORDER after this event last saved a custom
    order) appended as visible - so a new section type never silently stays
    hidden on events that already customized their layout."""
    saved = event.section_order or []
    seen = {s["key"] for s in saved}
    missing = [{"key": k, "visible": True} for k in DEFAULT_SECTION_ORDER if k not in seen]
    return (
        saved + missing if saved else [{"key": k, "visible": True} for k in DEFAULT_SECTION_ORDER]
    )


# ── Slug helpers ──────────────────────────────────────────────────────────────


async def _unique_event_slug(db: AsyncSession, base: str) -> str:
    slug = base
    counter = 2
    while await db.scalar(select(Event.id).where(Event.slug == slug)):
        slug = f"{base}-{counter}"
        counter += 1
    return slug


# ── CRUD ──────────────────────────────────────────────────────────────────────


async def create_event(
    db: AsyncSession,
    org: Organization,
    created_by: uuid.UUID,
    data: EventCreateRequest,
) -> Event:
    base_slug = slugify(data.title, max_length=180, word_boundary=True, separator="-")
    slug = await _unique_event_slug(db, base_slug)

    event = Event(
        org_id=org.id,
        created_by=created_by,
        title=data.title,
        slug=slug,
        description=data.description,
        format=data.format,
        start_datetime=data.start_datetime,
        end_datetime=data.end_datetime,
        timezone=data.timezone,
        venue_name=data.venue_name,
        venue_address=data.venue_address,
        venue_city=data.venue_city,
        venue_country=data.venue_country,
        venue_lat=data.venue_lat,
        venue_lng=data.venue_lng,
        virtual_url=data.virtual_url,
        virtual_platform=data.virtual_platform,
        max_capacity=data.max_capacity,
        is_private=data.is_private,
        password=data.password,
        vibe_tags=data.vibe_tags,
        extras=data.extras,
        pass_fees_to_buyer=data.pass_fees_to_buyer,
        meta_pixel_id=data.meta_pixel_id,
        google_tag_id=data.google_tag_id,
        tiktok_pixel_id=data.tiktok_pixel_id,
        tax_rate=data.tax_rate,
        tax_id=data.tax_id,
        status="draft",
    )
    event.categories = []
    db.add(event)
    await db.flush()

    await _set_categories(db, event, data.category_ids)

    logger.info("event.created", event_id=str(event.id), slug=slug, org_id=str(org.id))
    return event


async def get_event_by_id(db: AsyncSession, event_id: uuid.UUID) -> Event | None:
    return await db.scalar(
        select(Event)
        .where(Event.id == event_id, Event.deleted_at.is_(None))
        .options(
            selectinload(Event.categories),
            selectinload(Event.ticket_types),
            selectinload(Event.organization),
        )
    )


async def get_event_by_slug(db: AsyncSession, slug: str) -> Event | None:
    return await db.scalar(
        select(Event)
        .where(Event.slug == slug, Event.deleted_at.is_(None))
        .options(
            selectinload(Event.categories),
            selectinload(Event.ticket_types),
            selectinload(Event.organization),
        )
    )


async def update_event(
    db: AsyncSession,
    event: Event,
    data: EventUpdateRequest,
) -> Event:
    update = data.model_dump(exclude_unset=True)
    category_ids = update.pop("category_ids", None)

    for field, value in update.items():
        setattr(event, field, value)

    if category_ids is not None:
        await _set_categories(db, event, category_ids)

    await db.flush()
    logger.info("event.updated", event_id=str(event.id))
    return event


async def soft_delete_event(db: AsyncSession, event: Event) -> None:
    event.deleted_at = datetime.now(UTC)
    event.status = "cancelled"
    logger.info("event.deleted", event_id=str(event.id))


async def publish_event(db: AsyncSession, event: Event) -> Event:
    if event.status != "draft":
        raise ValueError(f"Event is already '{event.status}' and cannot be published again.")
    _validate_publishable(event)
    event.status = "published"
    await db.flush()

    # Generate OG image in background (non-blocking)
    try:
        await _generate_and_store_og_image(db, event)
    except Exception as exc:
        logger.warning("event.og_image_failed", event_id=str(event.id), exc=str(exc))

    logger.info("event.published", event_id=str(event.id))
    return event


async def cancel_event(db: AsyncSession, event: Event) -> Event:
    if event.status == "cancelled":
        raise ValueError("Event is already cancelled.")
    event.status = "cancelled"
    logger.info("event.cancelled", event_id=str(event.id))
    return event


async def go_live(db: AsyncSession, event: Event) -> Event:
    if event.status != "published":
        raise ValueError("Only published events can go live.")
    event.status = "live"
    logger.info("event.live", event_id=str(event.id))
    return event


async def end_event(db: AsyncSession, event: Event) -> Event:
    if event.status not in ("live", "published"):
        raise ValueError("Only live or published events can be ended.")
    event.status = "ended"
    logger.info("event.ended", event_id=str(event.id))
    return event


async def duplicate_event(
    db: AsyncSession,
    source: Event,
    org: Organization,
    created_by: uuid.UUID,
) -> Event:
    base_slug = slugify(
        f"copy of {source.title}", max_length=180, word_boundary=True, separator="-"
    )
    slug = await _unique_event_slug(db, base_slug)

    clone = Event(
        org_id=org.id,
        created_by=created_by,
        cloned_from_id=source.id,
        title=f"Copy of {source.title}",
        slug=slug,
        description=source.description,
        format=source.format,
        start_datetime=source.start_datetime,
        end_datetime=source.end_datetime,
        timezone=source.timezone,
        venue_name=source.venue_name,
        venue_address=source.venue_address,
        venue_city=source.venue_city,
        venue_country=source.venue_country,
        venue_lat=source.venue_lat,
        venue_lng=source.venue_lng,
        virtual_url=source.virtual_url,
        virtual_platform=source.virtual_platform,
        max_capacity=source.max_capacity,
        is_private=source.is_private,
        pass_fees_to_buyer=source.pass_fees_to_buyer,
        vibe_tags=list(source.vibe_tags),
        status="draft",
    )
    db.add(clone)
    await db.flush()

    # Copy categories
    if source.categories:
        clone.categories = list(source.categories)

    from app.services import ticketing_service as tk_svc

    await tk_svc.copy_ticket_types(db, source.id, clone.id)

    logger.info("event.duplicated", source_id=str(source.id), clone_id=str(clone.id))
    return clone


# Safety bound on series generation - a mistyped far-future end_date shouldn't
# silently create hundreds of draft events.
MAX_RECURRING_INSTANCES = 52


def _next_occurrence(dt: datetime, rule: str) -> datetime:
    from dateutil.relativedelta import relativedelta

    if rule == "daily":
        return dt + timedelta(days=1)
    if rule == "weekly":
        return dt + timedelta(weeks=1)
    if rule == "monthly":
        return dt + relativedelta(months=1)
    raise ValueError(f"Unknown recurrence rule: {rule}")


async def generate_recurring_series(
    db: AsyncSession,
    parent: Event,
    org: Organization,
    created_by: uuid.UUID,
    *,
    rule: str,
    end_date: datetime,
) -> list[Event]:
    """
    Generate the occurrences of a recurring event as new draft events, each a
    full copy of `parent` (including ticket types) with start/end shifted
    forward by the recurrence interval. Always drafts, regardless of the
    parent's own status - an organizer reviews and publishes each occurrence
    (or bulk-publishes) rather than a bad end date silently going live across
    every date in the series.
    """
    if rule not in ("daily", "weekly", "monthly"):
        raise ValueError("Recurrence rule must be 'daily', 'weekly', or 'monthly'.")
    if end_date <= parent.start_datetime:
        raise ValueError("Recurrence end date must be after the event's start date.")

    from app.services import ticketing_service as tk_svc

    duration = parent.end_datetime - parent.start_datetime
    children: list[Event] = []
    next_start = _next_occurrence(parent.start_datetime, rule)

    while next_start <= end_date and len(children) < MAX_RECURRING_INSTANCES:
        base_slug = slugify(
            f"{parent.title} {next_start.date().isoformat()}",
            max_length=180,
            word_boundary=True,
            separator="-",
        )
        slug = await _unique_event_slug(db, base_slug)

        child = Event(
            org_id=org.id,
            created_by=created_by,
            parent_event_id=parent.id,
            is_recurring=True,
            title=parent.title,
            slug=slug,
            description=parent.description,
            format=parent.format,
            start_datetime=next_start,
            end_datetime=next_start + duration,
            timezone=parent.timezone,
            venue_name=parent.venue_name,
            venue_address=parent.venue_address,
            venue_city=parent.venue_city,
            venue_country=parent.venue_country,
            venue_lat=parent.venue_lat,
            venue_lng=parent.venue_lng,
            virtual_url=parent.virtual_url,
            virtual_platform=parent.virtual_platform,
            max_capacity=parent.max_capacity,
            is_private=parent.is_private,
            vibe_tags=list(parent.vibe_tags),
            status="draft",
        )
        db.add(child)
        await db.flush()

        if parent.categories:
            child.categories = list(parent.categories)
        await tk_svc.copy_ticket_types(db, parent.id, child.id)

        children.append(child)
        next_start = _next_occurrence(next_start, rule)

    parent.is_recurring = True
    parent.recurrence_rule = rule
    parent.recurrence_end_date = end_date
    await db.flush()

    logger.info(
        "event.recurring_series_generated",
        parent_id=str(parent.id),
        rule=rule,
        count=len(children),
    )
    return children


async def list_recurring_children(db: AsyncSession, parent_id: uuid.UUID) -> list[Event]:
    result = await db.scalars(
        select(Event)
        .where(Event.parent_event_id == parent_id, Event.deleted_at.is_(None))
        .order_by(Event.start_datetime)
    )
    return list(result.all())


async def list_org_templates(db: AsyncSession, org_id: uuid.UUID) -> list[Event]:
    """Events an organizer has marked reusable as a starting point for new events."""
    result = await db.scalars(
        select(Event)
        .where(Event.org_id == org_id, Event.is_template == True, Event.deleted_at.is_(None))  # noqa: E712
        .order_by(Event.title)
    )
    return list(result.all())


# ── Listing & search ──────────────────────────────────────────────────────────


async def list_org_events(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[dict], int]:
    """Returns (list of events with counts, total count)."""
    base_q = select(Event).where(
        Event.org_id == org_id,
        Event.deleted_at.is_(None),
    )
    if status:
        base_q = base_q.where(Event.status == status)

    total = await db.scalar(select(func.count()).select_from(base_q.subquery())) or 0
    events_result = await db.scalars(
        base_q.order_by(Event.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .options(
            selectinload(Event.categories),
            selectinload(Event.ticket_types),
            selectinload(Event.organization),
        )
    )
    events = list(events_result.all())

    # Batch-load registration counts
    event_ids = [e.id for e in events]
    counts = await _batch_registration_counts(db, event_ids)
    revenues = await _batch_revenues(db, event_ids)

    result = []
    for event in events:
        result.append(
            {
                "event": event,
                "registration_count": counts.get(event.id, 0),
                "total_revenue": revenues.get(event.id, Decimal("0")),
            }
        )

    return result, total


_LANDING_CACHE_TTL_SECONDS = 60

# The DB's EventCategory.icon column doesn't reliably hold Material Symbols
# ligature names (it mixes in names from an earlier icon set, e.g.
# "briefcase"/"graduation-cap") - same reason app/templates/vendors/list.html
# keeps its own cat_icons map rather than trusting the DB value directly.
_CATEGORY_ICONS: dict[str, str] = {
    "technology": "computer",
    "business": "work",
    "music": "music_note",
    "arts-culture": "palette",
    "sports-fitness": "sports_soccer",
    "food-drink": "restaurant",
    "education": "school",
    "health-wellness": "self_improvement",
    "networking": "groups",
    "startup-innovation": "rocket_launch",
    "finance": "payments",
    "faith-spirituality": "auto_awesome",
    "community": "diversity_3",
    "government-politics": "account_balance",
    "weddings-celebrations": "favorite",
    "nightlife-parties": "nightlife",
    "hangouts-meetups": "celebration",
    "concerts-live-shows": "mic",
    "other": "grid_view",
}


def _serialize_showcase_event(event: Event) -> dict:
    return {
        "slug": event.slug,
        "title": event.title,
        "cover_image_url": event.cover_image_url,
        "start_datetime": event.start_datetime.isoformat(),
        "format": event.format,
        "venue_city": event.venue_city,
        "organization": {"name": event.organization.name},
        "ticket_types": [{"price": float(tt.price)} for tt in event.ticket_types],
    }


def _hydrate_cached_showcase_event(row: dict) -> dict:
    row = dict(row)
    row["start_datetime"] = datetime.fromisoformat(row["start_datetime"])
    return row


async def get_landing_categories_with_events(
    db: AsyncSession, *, max_categories: int = 6, events_per_category: int = 4
) -> list[dict]:
    """Real upcoming events grouped by category, for the landing page's
    "browse by category" section. Over-fetches a batch of upcoming public
    events (same eligibility as the old flat showcase this replaces),
    groups them by category in Python, and returns only categories that
    actually have at least one live event - ordered by how many events they
    have, most first, so the default/first tab is never empty.

    Cached briefly, same convention as the rest of this file's public-page
    queries - cache rows are plain dicts, not ORM instances; the template
    reads plain field/attribute access either way (Jinja's getattr-then-
    getitem fallback)."""
    cache_key = f"landing_categories_with_events:{max_categories}:{events_per_category}"
    cached = cache_get(cache_key)
    if cached is not None:
        try:
            return [
                {
                    "category": bucket["category"],
                    "events": [_hydrate_cached_showcase_event(e) for e in bucket["events"]],
                }
                for bucket in json.loads(cached)
            ]
        except (ValueError, KeyError, TypeError):
            pass  # corrupt/stale cache entry - fall through to a live query

    now = datetime.now(UTC)
    candidates = (
        (
            await db.scalars(
                select(Event)
                .options(
                    selectinload(Event.organization),
                    selectinload(Event.ticket_types),
                    selectinload(Event.categories),
                )
                .where(
                    Event.status.in_(["published", "live"]),
                    Event.deleted_at.is_(None),
                    Event.is_private == False,  # noqa: E712
                    Event.start_datetime >= now,
                )
                .order_by(Event.is_featured.desc(), Event.start_datetime.asc())
                .limit(200)
            )
        )
        .unique()
        .all()
    )

    grouped: dict[uuid.UUID, dict] = {}
    for event in candidates:
        for category in event.categories:
            bucket = grouped.setdefault(
                category.id,
                {
                    "category": {
                        "name": category.name,
                        "slug": category.slug,
                        "icon": _CATEGORY_ICONS.get(category.slug, "grid_view"),
                    },
                    "events": [],
                },
            )
            if len(bucket["events"]) < events_per_category:
                bucket["events"].append(event)

    buckets = sorted(grouped.values(), key=lambda b: len(b["events"]), reverse=True)
    buckets = buckets[:max_categories]

    cache_set(
        cache_key,
        json.dumps(
            [
                {
                    "category": b["category"],
                    "events": [_serialize_showcase_event(e) for e in b["events"]],
                }
                for b in buckets
            ]
        ),
        ttl_seconds=_LANDING_CACHE_TTL_SECONDS,
    )
    return buckets


def _pad_thumbnails(thumbnails: list[str], count: int) -> list[str]:
    """Cycle whatever real thumbnails exist up to exactly `count` entries, so
    the marquee always reads as a full row - never returns a fabricated URL,
    only repeats real ones. Empty in, empty out (template renders the
    icon-placeholder fallback when there are zero real event covers yet)."""
    if not thumbnails:
        return []
    return [thumbnails[i % len(thumbnails)] for i in range(count)]


async def get_platform_proof(db: AsyncSession, *, thumbnail_count: int = 5) -> dict:
    """A single honest usage stat plus a handful of real event cover images,
    for the landing page's social-proof marquee - no fabricated numbers:
    event_count is a live COUNT of every non-draft event ever run on the
    platform, so it's always accurate whatever the real number is, in dev
    or production alike."""
    cache_key = f"platform_proof:{thumbnail_count}"
    cached = cache_get(cache_key)
    if cached is not None:
        try:
            data = json.loads(cached)
            data["thumbnails"] = _pad_thumbnails(data["thumbnails"], thumbnail_count)
            return data
        except (ValueError, KeyError):
            pass  # corrupt/stale cache entry - fall through to a live query

    event_count = (
        await db.scalar(
            select(func.count(Event.id)).where(
                Event.status.in_(["published", "live", "ended"]),
                Event.deleted_at.is_(None),
            )
        )
        or 0
    )
    raw_thumbnails = list(
        await db.scalars(
            select(Event.cover_image_url)
            .where(
                Event.status.in_(["published", "live", "ended"]),
                Event.deleted_at.is_(None),
                Event.is_private == False,  # noqa: E712
                Event.cover_image_url.isnot(None),
            )
            .order_by(Event.created_at.desc())
            .limit(thumbnail_count)
        )
    )

    cache_set(
        cache_key,
        json.dumps({"event_count": event_count, "thumbnails": raw_thumbnails}),
        ttl_seconds=_LANDING_CACHE_TTL_SECONDS,
    )
    return {
        "event_count": event_count,
        "thumbnails": _pad_thumbnails(raw_thumbnails, thumbnail_count),
    }


async def get_spotlight_event(db: AsyncSession) -> Event | dict | None:
    """The single best real event to feature as a case-study spotlight on
    the landing page (a real substitute for a customer testimonial - Tixdoo
    has no real customers to quote yet, but it does have real events
    actually running) - featured first, then soonest-starting. Same
    eligibility and caching convention as get_landing_categories_with_events."""
    cache_key = "landing_spotlight_event"
    cached = cache_get(cache_key)
    if cached is not None:
        try:
            data = json.loads(cached)
            return _hydrate_cached_showcase_event(data) if data else None
        except (ValueError, KeyError, TypeError):
            pass  # corrupt/stale cache entry - fall through to a live query

    now = datetime.now(UTC)
    event = await db.scalar(
        select(Event)
        .options(selectinload(Event.organization), selectinload(Event.ticket_types))
        .where(
            Event.status.in_(["published", "live"]),
            Event.deleted_at.is_(None),
            Event.is_private == False,  # noqa: E712
            Event.start_datetime >= now,
        )
        .order_by(Event.is_featured.desc(), Event.start_datetime.asc())
        .limit(1)
    )

    cache_set(
        cache_key,
        json.dumps(_serialize_showcase_event(event) if event else None),
        ttl_seconds=_LANDING_CACHE_TTL_SECONDS,
    )
    return event


CURATED_EVENT_SECTIONS: dict[str, dict] = {
    "featured": {
        "key": "featured",
        "title": "Featured Worldwide",
        "subtitle": "Hand-picked international summits, flagship festivals, and spotlighted gatherings",
        "anchor": "featured",
        "badge": "Spotlight",
        "icon": "auto_awesome",
    },
    "weekend": {
        "key": "weekend",
        "title": "Happening This Weekend",
        "subtitle": "Exciting parties, concerts, and weekend cultural outings near you",
        "anchor": "weekend",
        "badge": "This Weekend",
        "icon": "calendar_month",
    },
    "technology": {
        "key": "technology",
        "title": "Tech, AI & Innovation",
        "subtitle": "Artificial intelligence, cloud architecture, Web3 forums, and developer masterclasses",
        "anchor": "tech-innovation",
        "badge": "Innovation",
        "icon": "terminal",
    },
    "concerts": {
        "key": "concerts",
        "title": "Concerts, Festivals & Nightlife",
        "subtitle": "Live music stages, Afrobeats showcases, electronic soundscapes, and club nights",
        "anchor": "concerts",
        "badge": "Live Music",
        "icon": "music_note",
    },
    "business": {
        "key": "business",
        "title": "Business, Leadership & Finance",
        "subtitle": "Executive forums, founder pitch stages, sustainability summits, and investor conclaves",
        "anchor": "business",
        "badge": "Leadership",
        "icon": "business_center",
    },
    "arts_culture": {
        "key": "arts_culture",
        "title": "Arts, Culture & Design",
        "subtitle": "Fashion runways, museum galas, architectural expos, and creative showcases",
        "anchor": "arts-culture",
        "badge": "Culture",
        "icon": "palette",
    },
    "free": {
        "key": "free",
        "title": "Free Admission & Open Access",
        "subtitle": "Free entry workshops, community hackathons, and global webinars",
        "anchor": "free",
        "badge": "Free Entry",
        "icon": "savings",
    },
}


async def search_public_events(
    db: AsyncSession,
    *,
    q: str | None = None,
    format: str | None = None,
    city: str | None = None,
    country: str | None = None,
    category_slug: str | None = None,
    curated_section: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[Event], int]:
    from sqlalchemy import and_, extract
    from app.models.ticketing import TicketType

    stmt = select(Event).where(
        Event.status.in_(["published", "live"]),
        Event.deleted_at.is_(None),
        Event.is_private == False,
    )

    if q:
        stmt = stmt.where(
            or_(
                Event.title.ilike(f"%{q}%"),
                Event.description.ilike(f"%{q}%"),
                Event.venue_city.ilike(f"%{q}%"),
            )
        )
    if format:
        stmt = stmt.where(Event.format == format)
    if city:
        stmt = stmt.where(Event.venue_city.ilike(f"%{city}%"))
    if country:
        stmt = stmt.where(Event.venue_country == country.upper())
    if from_date:
        stmt = stmt.where(Event.start_datetime >= from_date)
    if to_date:
        stmt = stmt.where(Event.start_datetime <= to_date)
    if category_slug:
        stmt = (
            stmt.join(event_category_link, Event.id == event_category_link.c.event_id)
            .join(EventCategory, EventCategory.id == event_category_link.c.category_id)
            .where(EventCategory.slug == category_slug)
        )

    order_by_clause = Event.start_datetime.asc()

    if curated_section:
        sec = curated_section.lower().replace("-", "_").strip()
        if sec == "featured":
            stmt = stmt.where(Event.is_featured == True)
        elif sec in ("weekend", "this_weekend"):
            # Events taking place on Friday (5), Saturday (6), or Sunday (7)
            stmt = stmt.where(extract("isodow", Event.start_datetime).in_([5, 6, 7]))
        elif sec in ("new", "new_on_tixdoo"):
            order_by_clause = Event.created_at.desc()
        elif sec in ("technology", "tech", "tech_innovation"):
            stmt = (
                stmt.join(event_category_link, Event.id == event_category_link.c.event_id)
                .join(EventCategory, EventCategory.id == event_category_link.c.category_id)
                .where(EventCategory.slug.in_(["technology", "startup-innovation"]))
            )
        elif sec in ("concerts", "music", "music_shows", "concerts_festivals"):
            stmt = (
                stmt.join(event_category_link, Event.id == event_category_link.c.event_id)
                .join(EventCategory, EventCategory.id == event_category_link.c.category_id)
                .where(EventCategory.slug.in_(["music", "concerts-live-shows", "nightlife-parties"]))
            )
        elif sec in ("business", "business_networking", "finance", "above_10k", "above10k"):
            stmt = (
                stmt.join(event_category_link, Event.id == event_category_link.c.event_id)
                .join(EventCategory, EventCategory.id == event_category_link.c.category_id)
                .where(EventCategory.slug.in_(["business", "finance", "networking"]))
            )
        elif sec in ("arts_culture", "arts", "culture"):
            stmt = (
                stmt.join(event_category_link, Event.id == event_category_link.c.event_id)
                .join(EventCategory, EventCategory.id == event_category_link.c.category_id)
                .where(EventCategory.slug.in_(["arts-culture", "community", "food-drink"]))
            )
        elif sec in ("free", "zero_dime", "zerodime", "below_10k", "below10k", "under_10k", "under10k"):
            stmt = stmt.where(
                Event.ticket_types.any(
                    and_(TicketType.is_visible == True, TicketType.price == 0)
                )
            )

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    result = await db.scalars(
        stmt.order_by(order_by_clause)
        .offset((page - 1) * per_page)
        .limit(per_page)
        .options(
            selectinload(Event.categories),
            selectinload(Event.ticket_types),
            selectinload(Event.organization),
        )
    )
    return list(result.all()), total


async def get_curated_event_sections(
    db: AsyncSession,
    *,
    limit_per_section: int = 12,
) -> list[dict]:
    """Fetch events grouped by the 6 curated discovery sections for the /events page:
    - featured
    - weekend (Upcoming this weekend)
    - new (New on Tixdoo)
    - above_10k (Events above 10,000)
    - below_10k (Events under 10,000)
    - free (Zero dime events)

    Returns a list of section metadata dicts containing up to limit_per_section events
    (default 12) for horizontal 4-in-a-row scrolling and the total count for the section.
    """
    sections = []
    for key, conf in CURATED_EVENT_SECTIONS.items():
        events, total = await search_public_events(
            db,
            curated_section=key,
            page=1,
            per_page=limit_per_section,
        )
        sections.append({
            **conf,
            "events": events,
            "total": total,
            "view_all_url": f"/events?category_section={key}",
        })
    return sections


async def get_discovery_feed(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 10,
) -> tuple[list[tuple[Event, int]], int]:
    """
    Feed-style ranking for the /discover page: upcoming events soonest-first,
    with same-day events ordered by popularity (confirmed registration count).

    Location proximity is intentionally not ranked server-side - there's no
    stored user location, so the feed template re-sorts the fetched page
    client-side using browser geolocation when available (see discover.html).
    Returns a list of (event, registration_count) tuples.
    """
    now = datetime.now(UTC)
    stmt = select(Event).where(
        Event.status.in_(["published", "live"]),
        Event.deleted_at.is_(None),
        Event.is_private == False,
        Event.start_datetime >= now,
    )

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    result = await db.scalars(
        stmt.order_by(Event.start_datetime.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .options(
            selectinload(Event.categories),
            selectinload(Event.ticket_types),
            selectinload(Event.organization),
        )
    )
    events = list(result.all())

    counts = await _batch_registration_counts(db, [e.id for e in events])

    # Secondary sort: within the same day, more popular events surface first.
    # (Cross-page reordering is out of scope for v1 - see docstring.)
    ranked = sorted(
        events,
        key=lambda e: (e.start_datetime.date(), -counts.get(e.id, 0), e.start_datetime),
    )

    return [(e, counts.get(e.id, 0)) for e in ranked], total


async def get_event_stats(db: AsyncSession, event_id: uuid.UUID) -> dict:
    from app.models.ticketing import Order, Registration

    reg_count = (
        await db.scalar(
            select(func.count(Registration.id)).where(
                Registration.event_id == event_id,
                Registration.status.in_(["confirmed", "checked_in"]),
            )
        )
        or 0
    )

    checkin_count = (
        await db.scalar(
            select(func.count(Registration.id)).where(
                Registration.event_id == event_id,
                Registration.status == "checked_in",
            )
        )
        or 0
    )

    revenue = await db.scalar(
        select(func.coalesce(func.sum(Order.net_amount), 0)).where(
            Order.event_id == event_id,
            Order.payment_status == "paid",
        )
    ) or Decimal("0")

    return {
        "registration_count": reg_count,
        "checkin_count": checkin_count,
        "total_revenue": float(revenue),
    }


async def get_all_categories(db: AsyncSession) -> list[EventCategory]:
    result = await db.scalars(
        select(EventCategory).order_by(EventCategory.sort_order, EventCategory.name)
    )
    return list(result.all())


# ── Cover image & OG ──────────────────────────────────────────────────────────


async def update_cover_image(
    db: AsyncSession,
    event: Event,
    image_bytes: bytes,
) -> Event:
    from app.utils import storage

    url = await storage.upload_image(
        image_bytes,
        folder=f"events/{event.id}/covers",
        filename="cover.jpg",
        max_width=1920,
    )
    event.cover_image_url = url

    # Re-generate OG image with new cover
    if event.status in ("published", "live"):
        try:
            await _generate_and_store_og_image(db, event)
        except Exception as exc:
            logger.warning("event.og_regen_failed", event_id=str(event.id), exc=str(exc))

    return event


async def update_gallery_image(
    db: AsyncSession,
    event: Event,
    image_bytes: bytes,
    slot: int,
) -> Event:
    from app.utils import storage

    url = await storage.upload_image(
        image_bytes,
        folder=f"events/{event.id}/gallery",
        filename=f"image{slot}.jpg",
        max_width=1920,
    )
    if slot == 1:
        event.gallery_1_url = url
    else:
        event.gallery_2_url = url
    return event


async def _generate_and_store_og_image(db: AsyncSession, event: Event) -> str:
    import httpx

    from app.utils import og_image, storage

    # Optionally fetch cover image bytes for the background
    cover_bytes: bytes | None = None
    if event.cover_image_url:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(event.cover_image_url)
                if r.status_code == 200:
                    cover_bytes = r.content
        except Exception as err:
            logger.warning(
                "event.og_image_cover_fetch_failed", event_id=str(event.id), error=str(err)
            )

    date_str = event.start_datetime.strftime("%a %d %b %Y") if event.start_datetime else None
    location_str = (
        event.venue_city
        if event.venue_city
        else (event.virtual_platform or "Online" if event.format == "virtual" else None)
    )

    png_bytes = og_image.generate_event_og_image(
        title=event.title,
        date_str=date_str,
        location_str=location_str,
        format_label=event.format,
        cover_image_bytes=cover_bytes,
    )

    url = await storage.upload_png(
        png_bytes,
        folder=f"events/{event.id}",
        filename="og.png",
    )
    event.og_image_url = url
    return url


# ── Internal helpers ──────────────────────────────────────────────────────────


def _validate_publishable(event: Event) -> None:
    errors = []
    if not event.title:
        errors.append("Title is required.")
    if not event.start_datetime:
        errors.append("Start date is required.")
    if event.format in ("in_person", "hybrid") and not event.venue_city:
        errors.append("Venue city is required for in-person events.")
    if event.format in ("virtual", "hybrid") and not event.virtual_url:
        errors.append("Virtual URL is required for virtual events.")
    if errors:
        raise ValueError("; ".join(errors))


async def _set_categories(
    db: AsyncSession,
    event: Event,
    category_ids: list[uuid.UUID],
) -> None:
    if not category_ids:
        event.categories = []
        return
    cats = await db.scalars(select(EventCategory).where(EventCategory.id.in_(category_ids)))
    event.categories = list(cats.all())


async def _batch_registration_counts(
    db: AsyncSession,
    event_ids: list[uuid.UUID],
) -> dict[uuid.UUID, int]:
    if not event_ids:
        return {}
    from app.models.ticketing import Registration

    rows = await db.execute(
        select(Registration.event_id, func.count(Registration.id))
        .where(
            Registration.event_id.in_(event_ids),
            Registration.status.in_(["confirmed", "checked_in"]),
        )
        .group_by(Registration.event_id)
    )
    return {row[0]: row[1] for row in rows.all()}


async def _batch_revenues(
    db: AsyncSession,
    event_ids: list[uuid.UUID],
) -> dict[uuid.UUID, Decimal]:
    if not event_ids:
        return {}
    from app.models.ticketing import Order

    rows = await db.execute(
        select(Order.event_id, func.coalesce(func.sum(Order.net_amount), 0))
        .where(
            Order.event_id.in_(event_ids),
            Order.payment_status == "paid",
        )
        .group_by(Order.event_id)
    )
    return {row[0]: row[1] for row in rows.all()}
