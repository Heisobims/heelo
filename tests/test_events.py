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
    events = resp.json()["data"]
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
