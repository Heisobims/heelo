"""Feed-style event discovery (/discover) - ranking, pagination, HTMX partials."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import event_service as ev_svc


async def _make_event(db: AsyncSession, org, **overrides):
    from app.models.event import Event

    now = datetime.now(UTC)
    defaults = {
        "org_id": org.id,
        "title": "Event",
        "slug": f"event-{datetime.now(UTC).timestamp()}",
        "status": "published",
        "format": "in_person",
        "start_datetime": now + timedelta(days=3),
        "end_datetime": now + timedelta(days=3, hours=3),
    }
    defaults.update(overrides)
    e = Event(**defaults)
    db.add(e)
    await db.flush()
    return e


async def _make_registrations(
    db: AsyncSession, event, ticket_type, count: int, *, status="confirmed"
):
    import uuid as _uuid

    from app.models.ticketing import Registration

    for i in range(count):
        db.add(
            Registration(
                event_id=event.id,
                ticket_type_id=ticket_type.id,
                attendee_name=f"Attendee {i}",
                attendee_email=f"attendee-{_uuid.uuid4()}@example.com",
                qr_code=f"qr-{_uuid.uuid4()}",
                status=status,
            )
        )
    await db.flush()


async def _make_ticket_type(db: AsyncSession, event):
    from app.models.ticketing import TicketType

    tt = TicketType(event_id=event.id, name="GA", price=0, currency="NGN", quantity=None)
    db.add(tt)
    await db.flush()
    return tt


# ── Service-level ranking ───────────────────────────────────────────────────────


async def test_discovery_feed_orders_by_date_proximity(db: AsyncSession, org, client: AsyncClient):
    now = datetime.now(UTC)
    await _make_event(db, org, slug="soon", start_datetime=now + timedelta(days=1))
    await _make_event(db, org, slug="later", start_datetime=now + timedelta(days=10))

    ranked, total = await ev_svc.get_discovery_feed(db, page=1, per_page=10)
    slugs = [e.slug for e, _ in ranked]

    assert total == 2
    assert slugs.index("soon") < slugs.index("later")


async def test_discovery_feed_same_day_ranks_by_popularity(
    db: AsyncSession, org, client: AsyncClient
):
    # Pinned mid-day date (not `now`-relative) so adding a couple of hours can
    # never cross a UTC midnight boundary and make this test flaky.
    day = datetime(2030, 6, 15, 10, 0, tzinfo=UTC)

    await _make_event(
        db, org, slug="quiet", start_datetime=day, end_datetime=day + timedelta(hours=1)
    )
    popular = await _make_event(
        db,
        org,
        slug="popular",
        start_datetime=day + timedelta(hours=2),
        end_datetime=day + timedelta(hours=3),
    )

    tt_popular = await _make_ticket_type(db, popular)
    await _make_registrations(db, popular, tt_popular, count=5)

    ranked, _ = await ev_svc.get_discovery_feed(db, page=1, per_page=10)
    slugs = [e.slug for e, _ in ranked]

    # Same calendar day: the more popular event should surface first even
    # though "quiet" technically starts a couple hours earlier.
    assert slugs.index("popular") < slugs.index("quiet")


async def test_discovery_feed_excludes_past_draft_and_private_events(
    db: AsyncSession, org, client: AsyncClient
):
    now = datetime.now(UTC)
    await _make_event(
        db, org, slug="past", start_datetime=now - timedelta(days=1), status="published"
    )
    await _make_event(db, org, slug="draft", status="draft")
    await _make_event(db, org, slug="private", is_private=True)
    visible = await _make_event(db, org, slug="visible")

    ranked, total = await ev_svc.get_discovery_feed(db, page=1, per_page=10)
    slugs = [e.slug for e, _ in ranked]

    assert total == 1
    assert slugs == [visible.slug]


async def test_discovery_feed_registration_count_is_correct(
    db: AsyncSession, org, client: AsyncClient
):
    event = await _make_event(db, org, slug="counted")
    tt = await _make_ticket_type(db, event)
    await _make_registrations(db, event, tt, count=3, status="confirmed")
    await _make_registrations(db, event, tt, count=2, status="pending")  # should not count

    ranked, _ = await ev_svc.get_discovery_feed(db, page=1, per_page=10)
    counts = {e.slug: count for e, count in ranked}

    assert counts["counted"] == 3


async def test_discovery_feed_pagination(db: AsyncSession, org, client: AsyncClient):
    now = datetime.now(UTC)
    for i in range(3):
        await _make_event(
            db, org, slug=f"page-test-{i}", start_datetime=now + timedelta(days=i + 1)
        )

    page1, total = await ev_svc.get_discovery_feed(db, page=1, per_page=2)
    page2, _ = await ev_svc.get_discovery_feed(db, page=2, per_page=2)

    assert total == 3
    assert len(page1) == 2
    assert len(page2) == 1


# ── Route-level ──────────────────────────────────────────────────────────────


async def test_discover_page_renders(client: AsyncClient, db: AsyncSession, org):
    await _make_event(db, org, slug="feed-visible")

    resp = await client.get("/discover")
    assert resp.status_code == 200
    assert "feed-visible" in resp.text


async def test_discover_htmx_request_returns_partial_only(
    client: AsyncClient, db: AsyncSession, org
):
    await _make_event(db, org, slug="feed-partial")

    resp = await client.get("/discover", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    # Partial should not include the full page shell (nav/html wrapper)
    assert "<nav" not in resp.text
    assert "feed-partial" in resp.text


async def test_discover_empty_state(client: AsyncClient):
    resp = await client.get("/discover")
    assert resp.status_code == 200
    assert "No upcoming events yet" in resp.text
