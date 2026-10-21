"""get_landing_categories_with_events, get_platform_proof, and
get_spotlight_event (app/services/event_service.py) - the landing page's
"browse by category" section, social-proof stat/marquee, and case-study
spotlight (a real-event substitute for a customer testimonial, since Heelo
has no real customers to quote yet). The first two replace the old flat
get_landing_showcase_events grid this session moved to a category-grouped
layout. Redis isn't running in the test environment by default, so the
live-query path is exercised without any monkeypatching (fail-open, same
convention as the rate limiter); a fake Redis is used specifically to
exercise the cache round-trip."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services import event_service as ev_svc


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value


async def _make_category(db, *, name="Technology", slug="technology"):
    from app.models.event import EventCategory

    cat = EventCategory(name=name, slug=slug, sort_order=1)
    db.add(cat)
    await db.flush()
    return cat


# ── get_landing_categories_with_events ──────────────────────────────────────


async def test_groups_events_by_category(db, org, published_event, ticket_type):
    cat = await _make_category(db)
    await db.refresh(published_event, attribute_names=["categories"])
    published_event.categories = [cat]
    await db.flush()

    buckets = await ev_svc.get_landing_categories_with_events(db)

    assert len(buckets) == 1
    assert buckets[0]["category"]["slug"] == "technology"
    assert buckets[0]["category"]["icon"] == "computer"
    assert len(buckets[0]["events"]) == 1
    assert buckets[0]["events"][0].slug == published_event.slug


async def test_excludes_categories_with_no_upcoming_events(db, org):
    await _make_category(db)  # no event attached
    buckets = await ev_svc.get_landing_categories_with_events(db)
    assert buckets == []


async def test_unmapped_category_slug_falls_back_to_default_icon(db, org, published_event):
    cat = await _make_category(db, name="Something New", slug="something-new")
    await db.refresh(published_event, attribute_names=["categories"])
    published_event.categories = [cat]
    await db.flush()

    buckets = await ev_svc.get_landing_categories_with_events(db)
    assert buckets[0]["category"]["icon"] == "grid_view"


async def test_orders_categories_by_event_count_descending(db, org, user):
    from app.models.event import Event

    popular = await _make_category(db, name="Popular", slug="popular")
    rare = await _make_category(db, name="Rare", slug="rare")

    for i in range(3):
        e = Event(
            org_id=org.id,
            title=f"Popular Event {i}",
            slug=f"popular-event-{i}",
            status="published",
            format="in_person",
            start_datetime=datetime.now(UTC) + timedelta(days=i + 1),
            end_datetime=datetime.now(UTC) + timedelta(days=i + 1, hours=2),
            categories=[popular],
        )
        db.add(e)

    rare_event = Event(
        org_id=org.id,
        title="Rare Event",
        slug="rare-event",
        status="published",
        format="in_person",
        start_datetime=datetime.now(UTC) + timedelta(days=10),
        end_datetime=datetime.now(UTC) + timedelta(days=10, hours=2),
        categories=[rare],
    )
    db.add(rare_event)
    await db.flush()

    buckets = await ev_svc.get_landing_categories_with_events(db)
    assert buckets[0]["category"]["slug"] == "popular"
    assert len(buckets[0]["events"]) == 3
    assert buckets[1]["category"]["slug"] == "rare"


async def test_categories_cache_round_trip(db, org, published_event, ticket_type, monkeypatch):
    from app.utils import cache as cache_mod

    cat = await _make_category(db)
    await db.refresh(published_event, attribute_names=["categories"])
    published_event.categories = [cat]
    await db.flush()

    fake = _FakeRedis()
    monkeypatch.setattr(cache_mod, "_redis", lambda: fake)

    await ev_svc.get_landing_categories_with_events(db)
    assert fake.store  # cache populated

    cached = await ev_svc.get_landing_categories_with_events(db)
    assert cached[0]["category"]["slug"] == "technology"
    # Cache-hit rows are plain dicts, not ORM Event instances - Jinja's
    # attribute-then-item fallback means template access resolves either way.
    ev = cached[0]["events"][0]
    assert ev["slug"] == published_event.slug
    assert isinstance(ev["start_datetime"], datetime)


# ── get_platform_proof ───────────────────────────────────────────────────────


async def test_platform_proof_counts_non_draft_events(db, org, published_event):
    proof = await ev_svc.get_platform_proof(db)
    assert proof["event_count"] >= 1


async def test_platform_proof_excludes_draft_events(db, org, event):
    """`event` fixture is status=draft - must not count toward the stat."""
    proof = await ev_svc.get_platform_proof(db)
    assert proof["event_count"] == 0


async def test_platform_proof_pads_thumbnails_to_requested_count(db, org):
    from app.models.event import Event

    e = Event(
        org_id=org.id,
        title="Covered Event",
        slug="covered-event",
        status="published",
        format="in_person",
        cover_image_url="https://example.com/cover.jpg",
        start_datetime=datetime.now(UTC) + timedelta(days=1),
        end_datetime=datetime.now(UTC) + timedelta(days=1, hours=2),
    )
    db.add(e)
    await db.flush()

    proof = await ev_svc.get_platform_proof(db, thumbnail_count=5)
    assert len(proof["thumbnails"]) == 5
    assert all(url == "https://example.com/cover.jpg" for url in proof["thumbnails"])


async def test_platform_proof_empty_thumbnails_when_no_cover_images(db, org, published_event):
    proof = await ev_svc.get_platform_proof(db)
    assert proof["thumbnails"] == []


async def test_platform_proof_cache_round_trip_repads_thumbnails(db, org, monkeypatch):
    from app.models.event import Event
    from app.utils import cache as cache_mod

    e = Event(
        org_id=org.id,
        title="Covered Event",
        slug="covered-event-2",
        status="published",
        format="in_person",
        cover_image_url="https://example.com/cover2.jpg",
        start_datetime=datetime.now(UTC) + timedelta(days=1),
        end_datetime=datetime.now(UTC) + timedelta(days=1, hours=2),
    )
    db.add(e)
    await db.flush()

    fake = _FakeRedis()
    monkeypatch.setattr(cache_mod, "_redis", lambda: fake)

    first = await ev_svc.get_platform_proof(db, thumbnail_count=5)
    assert len(first["thumbnails"]) == 5

    cached = await ev_svc.get_platform_proof(db, thumbnail_count=5)
    assert len(cached["thumbnails"]) == 5
    assert cached["event_count"] == first["event_count"]


# ── get_spotlight_event ──────────────────────────────────────────────────────


async def test_spotlight_returns_a_real_upcoming_event(db, org, published_event, ticket_type):
    event = await ev_svc.get_spotlight_event(db)
    assert event is not None
    assert event.slug == published_event.slug
    assert event.organization.name == org.name


async def test_spotlight_returns_none_when_no_upcoming_events(db, org):
    event = await ev_svc.get_spotlight_event(db)
    assert event is None


async def test_spotlight_prefers_featured_event(db, org):
    from app.models.event import Event

    regular = Event(
        org_id=org.id,
        title="Regular Event",
        slug="regular-event",
        status="published",
        format="in_person",
        is_featured=False,
        start_datetime=datetime.now(UTC) + timedelta(days=1),
        end_datetime=datetime.now(UTC) + timedelta(days=1, hours=2),
    )
    featured = Event(
        org_id=org.id,
        title="Featured Event",
        slug="featured-event",
        status="published",
        format="in_person",
        is_featured=True,
        start_datetime=datetime.now(UTC) + timedelta(days=5),
        end_datetime=datetime.now(UTC) + timedelta(days=5, hours=2),
    )
    db.add_all([regular, featured])
    await db.flush()

    event = await ev_svc.get_spotlight_event(db)
    assert event.slug == "featured-event"


async def test_spotlight_cache_round_trip(db, org, published_event, ticket_type, monkeypatch):
    from app.utils import cache as cache_mod

    fake = _FakeRedis()
    monkeypatch.setattr(cache_mod, "_redis", lambda: fake)

    await ev_svc.get_spotlight_event(db)
    assert fake.store  # cache populated

    cached = await ev_svc.get_spotlight_event(db)
    assert cached["slug"] == published_event.slug
    assert isinstance(cached["start_datetime"], datetime)


async def test_spotlight_cache_round_trip_when_none(db, org, monkeypatch):
    from app.utils import cache as cache_mod

    fake = _FakeRedis()
    monkeypatch.setattr(cache_mod, "_redis", lambda: fake)

    first = await ev_svc.get_spotlight_event(db)
    assert first is None
    assert fake.store  # None is still cached, to avoid re-querying every hit

    cached = await ev_svc.get_spotlight_event(db)
    assert cached is None


async def test_events_category_filter_renders_html(client):
    categories = [
        "music",
        "nightlife",
        "performing-visual-arts",
        "holidays",
        "dating",
        "hobbies",
        "business",
        "food-drink",
    ]
    for cat in categories:
        resp = await client.get(f"/events?category={cat}")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "<!doctype html>" in resp.text.lower()

