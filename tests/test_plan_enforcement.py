"""Subscription-tier enforcement (app/plans.py) - resource-count limits,
feature gates, and usage quotas wired into the actual endpoints. Before this,
Organization.plan was purely a display label with zero enforcement anywhere
in the codebase."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from app.config import settings
from app.plans import get_limits


async def _make_user(db, *, email: str):
    from app.models.user import User
    from app.utils.auth import hash_password

    u = User(
        full_name="Plan Test User",
        email=email,
        password_hash=hash_password("password123"),
        role="organizer",
        is_verified=True,
    )
    db.add(u)
    await db.flush()
    return u


async def _make_org(db, owner, *, plan: str, slug: str):
    from app.models.organization import Organization

    o = Organization(
        owner_id=owner.id, name=f"{plan.capitalize()} Org", slug=slug, plan=plan, currency="NGN"
    )
    db.add(o)
    await db.flush()
    return o


async def _make_event(db, org, *, slug: str):
    from app.models.event import Event

    e = Event(
        org_id=org.id,
        title="Plan Test Event",
        slug=slug,
        status="published",
        format="in_person",
        venue_city="Lagos",
        start_datetime=datetime.now(UTC) + timedelta(days=7),
        end_datetime=datetime.now(UTC) + timedelta(days=7, hours=3),
    )
    db.add(e)
    await db.flush()
    return e


def _token_for(user_id) -> str:
    from jose import jwt

    payload = {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(hours=1), "type": "access"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _headers_for(user_id) -> dict:
    return {"Authorization": f"Bearer {_token_for(user_id)}"}


async def _free_org(db, email="free-owner@example.com", slug="free-org"):
    owner = await _make_user(db, email=email)
    org = await _make_org(db, owner, plan="free", slug=slug)
    return owner, org


async def _growth_org(db, email="growth-owner@example.com", slug="growth-org"):
    owner = await _make_user(db, email=email)
    org = await _make_org(db, owner, plan="growth", slug=slug)
    return owner, org


# ── app/plans.py unit-level sanity ──────────────────────────────────────────


def test_limits_are_monotonically_non_decreasing_across_tiers():
    """Every numeric limit should only ever go up (or stay unlimited) as you
    move up the tier ladder - a regression here would mean a higher tier is
    accidentally more restrictive than a lower one."""
    from app.plans import PLAN_ORDER, get_limits

    fields = [
        "max_seats",
        "max_orgs",
        "max_webhook_subscriptions",
        "max_api_keys",
        "max_custom_domains",
        "whatsapp_messages_per_month",
        "ai_generations_per_month",
    ]
    for field in fields:
        prev = None
        for plan in PLAN_ORDER:
            val = getattr(get_limits(plan), field)
            if val is not None and prev is not None:
                assert val >= prev, f"{field} decreased from a lower tier to {plan}"
            prev = val if val is not None else prev


def test_every_paid_tier_is_a_strict_superset_of_the_one_below():
    from app.plans import _FEATURES, PLAN_ORDER

    for lower, higher in zip(PLAN_ORDER, PLAN_ORDER[1:], strict=False):
        assert _FEATURES[lower].issubset(_FEATURES[higher])


# ── Seat limit ───────────────────────────────────────────────────────────────


async def test_free_org_cannot_invite_a_second_seat(client: AsyncClient, db):
    owner, org = await _free_org(db)
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/members/invite",
        json={"email": "second@example.com", "role": "organizer"},
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 402


async def test_growth_org_can_invite_up_to_its_seat_limit(client: AsyncClient, db):
    owner, org = await _growth_org(db)
    # Growth allows 3 total (owner + 2 more)
    r1 = await client.post(
        f"/api/v1/organizations/{org.slug}/members/invite",
        json={"email": "member1@example.com", "role": "organizer"},
        headers=_headers_for(owner.id),
    )
    assert r1.status_code == 201
    r2 = await client.post(
        f"/api/v1/organizations/{org.slug}/members/invite",
        json={"email": "member2@example.com", "role": "organizer"},
        headers=_headers_for(owner.id),
    )
    assert r2.status_code == 201
    # Third additional seat (owner + 3 members = 4) exceeds Growth's limit of 3
    r3 = await client.post(
        f"/api/v1/organizations/{org.slug}/members/invite",
        json={"email": "member3@example.com", "role": "organizer"},
        headers=_headers_for(owner.id),
    )
    assert r3.status_code == 402


# ── Org limit ────────────────────────────────────────────────────────────────


async def test_free_user_cannot_own_a_second_organization(client: AsyncClient, db):
    owner, _org = await _free_org(db)
    resp = await client.post(
        "/api/v1/organizations",
        json={"name": "Second Org"},
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 402


# ── Promo code limit ─────────────────────────────────────────────────────────


async def test_free_org_limited_to_one_active_promo_code(client: AsyncClient, db):
    owner, org = await _free_org(db)
    event = await _make_event(db, org, slug="free-promo-event")
    from app.models.ticketing import TicketType

    db.add(TicketType(event_id=event.id, name="GA", price=1000.0, currency="NGN", quantity=100))
    await db.flush()
    headers = _headers_for(owner.id)

    first = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/promo-codes",
        json={"code": "FIRST10", "discount_type": "percent", "discount_value": 10},
        headers=headers,
    )
    assert first.status_code == 201

    second = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/promo-codes",
        json={"code": "SECOND10", "discount_type": "percent", "discount_value": 10},
        headers=headers,
    )
    assert second.status_code == 402


# ── Webhook / API key limits ─────────────────────────────────────────────────


async def test_free_org_cannot_create_webhooks(client: AsyncClient, db):
    owner, org = await _free_org(db)
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/webhooks",
        json={"url": "https://example.com/hook", "events": ["order.paid"]},
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 402


async def test_free_org_cannot_create_api_keys(client: AsyncClient, db):
    owner, org = await _free_org(db)
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/api-keys",
        json={"name": "My key"},
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 402


async def test_growth_org_hits_webhook_limit_after_three(client: AsyncClient, db):
    owner, org = await _growth_org(db)
    headers = _headers_for(owner.id)
    for i in range(3):
        r = await client.post(
            f"/api/v1/organizations/{org.slug}/webhooks",
            json={"url": f"https://example.com/hook{i}", "events": ["order.paid"]},
            headers=headers,
        )
        assert r.status_code == 201
    r4 = await client.post(
        f"/api/v1/organizations/{org.slug}/webhooks",
        json={"url": "https://example.com/hook4", "events": ["order.paid"]},
        headers=headers,
    )
    assert r4.status_code == 402


# ── Feature gates ────────────────────────────────────────────────────────────


async def test_free_org_cannot_import_crm_contacts(client: AsyncClient, db):
    owner, org = await _free_org(db)
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/contacts/import",
        files={"file": ("c.csv", b"name,email\nA,a@example.com\n", "text/csv")},
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 402


async def test_growth_org_can_import_crm_contacts(client: AsyncClient, db):
    owner, org = await _growth_org(db)
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/contacts/import",
        files={"file": ("c.csv", b"name,email\nA,a@example.com\n", "text/csv")},
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 201


async def test_free_org_cannot_duplicate_events(client: AsyncClient, db):
    owner, org = await _free_org(db)
    event = await _make_event(db, org, slug="free-dup-event")
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/duplicate",
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 402


async def test_free_org_cannot_add_speakers(client: AsyncClient, db):
    owner, org = await _free_org(db)
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/speakers",
        json={"name": "Ada Lovelace"},
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 402


async def test_growth_org_can_add_speakers(client: AsyncClient, db):
    owner, org = await _growth_org(db)
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/speakers",
        json={"name": "Ada Lovelace"},
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 201


async def test_free_org_cannot_add_agenda_sessions(client: AsyncClient, db):
    owner, org = await _free_org(db)
    event = await _make_event(db, org, slug="free-agenda-event")
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/sessions",
        json={
            "title": "Opening Keynote",
            "start_datetime": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
            "end_datetime": (datetime.now(UTC) + timedelta(days=7, hours=1)).isoformat(),
        },
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 402


async def test_growth_org_cannot_add_sponsors(client: AsyncClient, db):
    """Sponsors are Pro+, not Growth - Growth only unlocks speakers/agenda."""
    owner, org = await _growth_org(db)
    event = await _make_event(db, org, slug="growth-sponsor-event")
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/sponsors",
        json={"name": "Acme Corp"},
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 402


async def test_pro_org_can_add_sponsors(client: AsyncClient, db):
    owner = await _make_user(db, email="pro-owner@example.com")
    org = await _make_org(db, owner, plan="pro", slug="pro-org")
    event = await _make_event(db, org, slug="pro-sponsor-event")
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/sponsors",
        json={"name": "Acme Corp"},
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 201


async def test_growth_org_cannot_create_live_polls(client: AsyncClient, db):
    owner, org = await _growth_org(db)
    event = await _make_event(db, org, slug="growth-poll-event")
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/live/polls",
        json={"question": "How's it going?", "options": ["Great", "Okay"]},
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 402


async def test_free_org_cannot_view_advanced_analytics(client: AsyncClient, db):
    owner, org = await _free_org(db)
    event = await _make_event(db, org, slug="free-analytics-event")
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/analytics/sales-chart",
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 402


async def test_free_org_can_still_view_basic_analytics(client: AsyncClient, db):
    """Basic summary/ticket-breakdown analytics and CSV export are explicitly
    NOT gated - they're "stays free regardless of tier" per the plan."""
    owner, org = await _free_org(db)
    event = await _make_event(db, org, slug="free-basic-analytics-event")
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/analytics/summary",
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 200

    export = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/analytics/export.csv",
        headers=_headers_for(owner.id),
    )
    assert export.status_code == 200


async def test_free_org_can_still_create_events_and_tickets_unlimited(client: AsyncClient, db):
    """Unlimited events/ticketing on Free is a deliberate, explicitly
    disclosed non-gate - must never accidentally get blocked."""
    owner, org = await _free_org(db)
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events",
        json={
            "title": "Free Tier Meetup",
            "format": "in_person",
            "is_free": True,
            "location_name": "Community Hall",
            "start_datetime": "2027-05-01T18:00:00+01:00",
            "end_datetime": "2027-05-01T21:00:00+01:00",
        },
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 201


# ── AI usage quota ───────────────────────────────────────────────────────────


class _FakeRedis:
    def __init__(self):
        self.counts: dict[str, int] = {}

    def get(self, key):
        val = self.counts.get(key)
        return str(val) if val is not None else None

    def incrby(self, key, amount):
        self.counts[key] = self.counts.get(key, 0) + amount
        return self.counts[key]

    def expire(self, key, seconds):
        pass


async def test_ai_quota_blocks_after_free_tier_limit(client: AsyncClient, db, monkeypatch):
    import app.plans as plans_mod

    fake = _FakeRedis()
    monkeypatch.setattr(plans_mod, "_quota_redis", lambda: fake)

    owner, org = await _free_org(db)
    headers = _headers_for(owner.id)
    limit = get_limits("free").ai_generations_per_month

    for _ in range(limit):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/ai/generate-event-description",
            json={"title": "Test Event"},
            headers=headers,
        )
        assert resp.status_code == 200

    over_limit = await client.post(
        f"/api/v1/organizations/{org.slug}/ai/generate-event-description",
        json={"title": "Test Event"},
        headers=headers,
    )
    assert over_limit.status_code == 402


async def test_ai_quota_fails_open_when_redis_unavailable(client: AsyncClient, db, monkeypatch):
    import app.plans as plans_mod

    monkeypatch.setattr(plans_mod, "_quota_redis", lambda: None)
    owner, org = await _free_org(db)

    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/ai/generate-event-description",
        json={"title": "Test Event"},
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 200


async def test_whatsapp_campaign_send_blocked_over_quota(
    client: AsyncClient, db, monkeypatch
):
    import app.plans as plans_mod

    fake = _FakeRedis()
    monkeypatch.setattr(plans_mod, "_quota_redis", lambda: fake)
    # Pre-fill the quota to just under the free limit so a small campaign tips it over.
    limit = get_limits("free").whatsapp_messages_per_month
    owner, org = await _free_org(db)
    key = plans_mod._quota_key("whatsapp", org.id)
    fake.counts[key] = limit - 1

    event = await _make_event(db, org, slug="free-wa-campaign-event")
    from app.models.ticketing import Registration, TicketType

    tt = TicketType(event_id=event.id, name="GA", price=0.0, currency="NGN", quantity=100)
    db.add(tt)
    await db.flush()

    for i in range(3):
        db.add(
            Registration(
                event_id=event.id,
                ticket_type_id=tt.id,
                attendee_name=f"Attendee {i}",
                attendee_email=f"attendee{i}@example.com",
                attendee_phone="+2348012345678",
                qr_code=f"qr-{uuid.uuid4()}",
                status="confirmed",
                referral_token=f"ref-{uuid.uuid4().hex[:12]}",
            )
        )
    await db.flush()

    headers = _headers_for(owner.id)
    create = await client.post(
        f"/api/v1/organizations/{org.slug}/campaigns",
        json={
            "name": "WA Blast",
            "type": "whatsapp",
            "body": "Hey {{name}}, see you soon!",
            "event_id": str(event.id),
            "audience_statuses": ["confirmed"],
        },
        headers=headers,
    )
    assert create.status_code == 201
    campaign_id = create.json()["data"]["id"]

    send = await client.post(
        f"/api/v1/organizations/{org.slug}/campaigns/{campaign_id}/send",
        json={},
        headers=headers,
    )
    assert send.status_code == 402
