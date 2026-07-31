"""Check-in — QR token, manual, undo, stats."""

from __future__ import annotations

import uuid

from httpx import AsyncClient


async def test_check_in_by_registration_id(
    client: AsyncClient, org, published_event, registration, user_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
        json={"registration_id": str(registration.id)},
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "checked_in"


async def test_check_in_already_checked_in_returns_409(
    client: AsyncClient, org, published_event, registration, user_headers
):
    # First check-in
    await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
        json={"registration_id": str(registration.id)},
        headers=user_headers,
    )
    # Second check-in — should be 409
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
        json={"registration_id": str(registration.id)},
        headers=user_headers,
    )
    assert resp.status_code == 409


async def test_check_in_nonexistent_registration(
    client: AsyncClient, org, published_event, user_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
        json={"registration_id": str(uuid.uuid4())},
        headers=user_headers,
    )
    assert resp.status_code == 404


async def test_undo_check_in(client: AsyncClient, org, published_event, registration, user_headers):
    # Check in first
    await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
        json={"registration_id": str(registration.id)},
        headers=user_headers,
    )
    # Undo
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in/{registration.id}/undo",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "confirmed"


async def test_checkin_stats(client: AsyncClient, org, published_event, registration, user_headers):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in/stats",
        headers=user_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "checked_in" in data
    assert "total" in data


async def test_checkin_search(
    client: AsyncClient, org, published_event, registration, user_headers
):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in/search",
        params={"q": "Jane"},
        headers=user_headers,
    )
    assert resp.status_code == 200
    results = resp.json()["data"]
    assert any(r["attendee_name"] == "Jane Doe" for r in results)


async def test_check_in_requires_org_membership(
    client: AsyncClient, org, published_event, registration, other_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
        json={"registration_id": str(registration.id)},
        headers=other_headers,
    )
    assert resp.status_code == 403
