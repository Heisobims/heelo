"""Public REST API — API key auth, events, registrations, check-in, stats."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def test_public_api_requires_api_key(client: AsyncClient):
    resp = await client.get("/api/public/v1/events")
    assert resp.status_code == 401


async def test_public_api_rejects_invalid_key(client: AsyncClient):
    resp = await client.get(
        "/api/public/v1/events",
        headers={"X-API-Key": "hlo_live_notarealkey00000000000000000000000000000000000000000000"},
    )
    assert resp.status_code == 401


async def test_public_list_events(client: AsyncClient, api_key, published_event):
    raw, key = api_key
    resp = await client.get("/api/public/v1/events", headers={"X-API-Key": raw})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert any(e["id"] == str(published_event.id) for e in data)


async def test_public_get_event(client: AsyncClient, api_key, published_event):
    raw, _ = api_key
    resp = await client.get(
        f"/api/public/v1/events/{published_event.id}",
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == published_event.title


async def test_public_get_event_not_in_org_returns_404(
    client: AsyncClient, api_key, db
):
    """An API key from org A cannot see events from org B."""
    import uuid
    raw, _ = api_key
    resp = await client.get(
        f"/api/public/v1/events/{uuid.uuid4()}",
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 404


async def test_public_list_registrations(client: AsyncClient, api_key, published_event, registration):
    raw, _ = api_key
    resp = await client.get(
        f"/api/public/v1/events/{published_event.id}/registrations",
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert any(r["attendee_email"] == "jane@example.com" for r in data)


async def test_public_check_in(client: AsyncClient, api_key, published_event, registration):
    raw, _ = api_key
    resp = await client.post(
        f"/api/public/v1/events/{published_event.id}/check-in",
        json={"registration_id": str(registration.id)},
        headers={"X-API-Key": raw},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "checked_in"


async def test_public_stats(client: AsyncClient, api_key, published_event):
    raw, _ = api_key
    resp = await client.get("/api/public/v1/stats", headers={"X-API-Key": raw})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "total_events" in data
    assert "total_confirmed_registrations" in data
    assert "total_net_revenue" in data


async def test_revoked_api_key_returns_401(client: AsyncClient, org, api_key, user_headers):
    raw, key = api_key

    # Revoke it
    await client.delete(
        f"/api/v1/organizations/{org.slug}/api-keys/{key.id}",
        headers=user_headers,
    )

    # Try to use it
    resp = await client.get("/api/public/v1/events", headers={"X-API-Key": raw})
    assert resp.status_code == 401
