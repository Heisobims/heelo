"""Event vibe tags - free-form organizer-typed tags, replacing rigid categories."""

from __future__ import annotations

from httpx import AsyncClient


async def test_create_event_with_vibe_tags(client: AsyncClient, org, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events",
        json={
            "title": "Rooftop Sundowner",
            "format": "in_person",
            "venue_city": "Lagos",
            "start_datetime": "2027-03-15T19:00:00+01:00",
            "end_datetime": "2027-03-15T23:00:00+01:00",
            "vibe_tags": ["chill", "networking-heavy"],
        },
        headers=user_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["vibe_tags"] == ["chill", "networking-heavy"]


async def test_vibe_tags_are_deduped_and_normalized(client: AsyncClient, org, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events",
        json={
            "title": "Rooftop Sundowner",
            "format": "in_person",
            "venue_city": "Lagos",
            "start_datetime": "2027-03-15T19:00:00+01:00",
            "end_datetime": "2027-03-15T23:00:00+01:00",
            "vibe_tags": ["Chill", "chill", "  Dress To Impress  "],
        },
        headers=user_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["vibe_tags"] == ["chill", "dress to impress"]


async def test_vibe_tags_over_limit_rejected(client: AsyncClient, org, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events",
        json={
            "title": "Rooftop Sundowner",
            "format": "in_person",
            "venue_city": "Lagos",
            "start_datetime": "2027-03-15T19:00:00+01:00",
            "end_datetime": "2027-03-15T23:00:00+01:00",
            "vibe_tags": [f"tag{i}" for i in range(9)],
        },
        headers=user_headers,
    )
    assert resp.status_code == 422


async def test_update_event_vibe_tags(client: AsyncClient, org, published_event, user_headers):
    resp = await client.patch(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}",
        json={"vibe_tags": ["outdoors", "family-friendly"]},
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["vibe_tags"] == ["outdoors", "family-friendly"]


async def test_new_event_defaults_to_no_vibe_tags(client: AsyncClient, org, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events",
        json={
            "title": "No Vibes Yet",
            "format": "in_person",
            "venue_city": "Lagos",
            "start_datetime": "2027-03-15T19:00:00+01:00",
            "end_datetime": "2027-03-15T23:00:00+01:00",
        },
        headers=user_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["vibe_tags"] == []
