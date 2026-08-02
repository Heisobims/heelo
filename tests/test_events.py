"""Event CRUD — create, update, publish, list, delete."""

from __future__ import annotations

from httpx import AsyncClient

_EVENT_PAYLOAD = {
    "title": "Afrobeats Night Lagos",
    "format": "in_person",
    "is_free": False,
    "currency": "NGN",
    "location_name": "Eko Hotel, Lagos",
    "start_datetime": "2027-03-15T19:00:00+01:00",
    "end_datetime": "2027-03-15T23:00:00+01:00",
}


async def test_create_event(client: AsyncClient, org, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events",
        json=_EVENT_PAYLOAD,
        headers=user_headers,
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["title"] == "Afrobeats Night Lagos"
    assert data["status"] == "draft"


async def test_create_event_requires_auth(client: AsyncClient, org):
    resp = await client.post(f"/api/v1/organizations/{org.slug}/events", json=_EVENT_PAYLOAD)
    assert resp.status_code == 401


async def test_create_event_wrong_org_returns_403(client: AsyncClient, org, other_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events",
        json=_EVENT_PAYLOAD,
        headers=other_headers,
    )
    assert resp.status_code == 403


async def test_list_events(client: AsyncClient, org, event, user_headers):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events",
        headers=user_headers,
    )
    assert resp.status_code == 200
    events = resp.json()["data"]["items"]
    assert any(e["id"] == str(event.id) for e in events)


async def test_get_event_by_id(client: AsyncClient, org, event, user_headers):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{event.id}",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == event.title


async def test_update_event(client: AsyncClient, org, event, user_headers):
    resp = await client.patch(
        f"/api/v1/organizations/{org.slug}/events/{event.id}",
        json={"title": "Updated Title"},
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "Updated Title"


async def test_publish_draft_event(client: AsyncClient, org, event, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/publish",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "published"


async def test_publish_already_published_returns_400(
    client: AsyncClient, org, published_event, user_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/publish",
        headers=user_headers,
    )
    assert resp.status_code == 400


async def test_get_nonexistent_event_returns_404(client: AsyncClient, org, user_headers):
    import uuid

    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{uuid.uuid4()}",
        headers=user_headers,
    )
    assert resp.status_code == 404


async def test_public_event_page_returns_html(client: AsyncClient, published_event):
    resp = await client.get(f"/e/{published_event.slug}")
    assert resp.status_code == 200
    assert b"html" in resp.content.lower()


async def test_draft_event_not_visible_publicly(client: AsyncClient, event):
    resp = await client.get(f"/e/{event.slug}")
    assert resp.status_code in (404, 403)


# ── Duplicate / templates ────────────────────────────────────────────────────


async def test_duplicate_event_copies_ticket_types(
    client: AsyncClient, org, published_event, ticket_type, user_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/duplicate",
        headers=user_headers,
    )
    assert resp.status_code == 201
    clone_id = resp.json()["data"]["id"]

    tt_resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{clone_id}/ticket-types",
        headers=user_headers,
    )
    assert tt_resp.status_code == 200
    cloned_types = tt_resp.json()
    assert len(cloned_types) == 1
    assert cloned_types[0]["name"] == ticket_type.name
    assert float(cloned_types[0]["price"]) == float(ticket_type.price)
    # Sales counters must never carry over to the clone.
    assert cloned_types[0]["quantity_sold"] == 0


async def test_duplicate_event_is_a_draft_regardless_of_source_status(
    client: AsyncClient, org, published_event, user_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/duplicate",
        headers=user_headers,
    )
    assert resp.status_code == 201
    clone_id = resp.json()["data"]["id"]

    get_resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{clone_id}", headers=user_headers
    )
    assert get_resp.json()["data"]["status"] == "draft"


async def test_mark_event_as_template_and_list_it(client: AsyncClient, org, event, user_headers):
    list_resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/templates", headers=user_headers
    )
    assert list_resp.json()["data"] == []

    patch_resp = await client.patch(
        f"/api/v1/organizations/{org.slug}/events/{event.id}",
        json={"is_template": True},
        headers=user_headers,
    )
    assert patch_resp.status_code == 200

    list_resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/templates", headers=user_headers
    )
    templates = list_resp.json()["data"]
    assert len(templates) == 1
    assert templates[0]["id"] == str(event.id)


async def test_unmark_event_as_template_removes_it_from_the_list(
    client: AsyncClient, org, event, user_headers
):
    await client.patch(
        f"/api/v1/organizations/{org.slug}/events/{event.id}",
        json={"is_template": True},
        headers=user_headers,
    )
    await client.patch(
        f"/api/v1/organizations/{org.slug}/events/{event.id}",
        json={"is_template": False},
        headers=user_headers,
    )

    list_resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/templates", headers=user_headers
    )
    assert list_resp.json()["data"] == []


# ── Recurring series ──────────────────────────────────────────────────────────


async def test_generate_weekly_series_creates_drafts(
    client: AsyncClient, db, org, event, user_headers
):
    from datetime import timedelta

    from app.models.ticketing import TicketType

    db.add(TicketType(event_id=event.id, name="General", price=1000.0, currency="NGN", quantity=50))
    await db.flush()

    end_date = (event.start_datetime + timedelta(weeks=3)).isoformat()
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/recurrence/generate",
        json={"rule": "weekly", "end_date": end_date},
        headers=user_headers,
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["count"] == 3

    children_resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/recurrence/children",
        headers=user_headers,
    )
    children = children_resp.json()["data"]
    assert len(children) == 3
    assert all(c["status"] == "draft" for c in children)

    # Each occurrence gets its own copy of the parent's ticket types.
    tt_resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{children[0]['id']}/ticket-types",
        headers=user_headers,
    )
    assert len(tt_resp.json()) == 1


async def test_generate_series_rejects_end_date_before_start(
    client: AsyncClient, org, event, user_headers
):
    from datetime import timedelta

    end_date = (event.start_datetime - timedelta(days=1)).isoformat()
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/recurrence/generate",
        json={"rule": "weekly", "end_date": end_date},
        headers=user_headers,
    )
    assert resp.status_code == 400


async def test_generate_series_caps_instance_count(client: AsyncClient, org, event, user_headers):
    from datetime import timedelta

    from app.services.event_service import MAX_RECURRING_INSTANCES

    # 200 weeks out is way more than the safety cap for a daily series.
    end_date = (event.start_datetime + timedelta(weeks=200)).isoformat()
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/recurrence/generate",
        json={"rule": "daily", "end_date": end_date},
        headers=user_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["count"] == MAX_RECURRING_INSTANCES
