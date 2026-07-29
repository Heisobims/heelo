"""Campaign — create, schedule, send, recipient tracking."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient


_CAMPAIGN_PAYLOAD = {
    "name": "Pre-event Hype",
    "channel": "email",
    "subject": "You're going to love this",
    "body": "Doors open at 7 PM. Bring energy!",
    "audience": "all_confirmed",
}


async def test_create_draft_campaign(client: AsyncClient, org, published_event, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/campaigns",
        json={**_CAMPAIGN_PAYLOAD, "event_id": str(published_event.id)},
        headers=user_headers,
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["status"] == "draft"
    assert data["name"] == "Pre-event Hype"


async def test_schedule_campaign(client: AsyncClient, org, published_event, user_headers):
    create = await client.post(
        f"/api/v1/organizations/{org.slug}/campaigns",
        json={**_CAMPAIGN_PAYLOAD, "event_id": str(published_event.id)},
        headers=user_headers,
    )
    campaign_id = create.json()["data"]["id"]
    send_at = (datetime.now(UTC) + timedelta(hours=2)).isoformat()

    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/campaigns/{campaign_id}/schedule",
        json={"send_at": send_at},
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "scheduled"


async def test_send_campaign_immediately(
    client: AsyncClient, org, published_event, registration, user_headers
):
    create = await client.post(
        f"/api/v1/organizations/{org.slug}/campaigns",
        json={**_CAMPAIGN_PAYLOAD, "event_id": str(published_event.id)},
        headers=user_headers,
    )
    campaign_id = create.json()["data"]["id"]

    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/campaigns/{campaign_id}/send-now",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "sent"


async def test_list_campaigns(client: AsyncClient, org, published_event, user_headers):
    await client.post(
        f"/api/v1/organizations/{org.slug}/campaigns",
        json={**_CAMPAIGN_PAYLOAD, "event_id": str(published_event.id)},
        headers=user_headers,
    )
    resp = await client.get(f"/api/v1/organizations/{org.slug}/campaigns", headers=user_headers)
    assert resp.status_code == 200
    assert len(resp.json()["data"]) >= 1


async def test_campaign_requires_org_membership(
    client: AsyncClient, org, published_event, other_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/campaigns",
        json=_CAMPAIGN_PAYLOAD,
        headers=other_headers,
    )
    assert resp.status_code == 403


async def test_cannot_edit_sent_campaign(
    client: AsyncClient, org, published_event, registration, user_headers
):
    create = await client.post(
        f"/api/v1/organizations/{org.slug}/campaigns",
        json={**_CAMPAIGN_PAYLOAD, "event_id": str(published_event.id)},
        headers=user_headers,
    )
    campaign_id = create.json()["data"]["id"]

    await client.post(
        f"/api/v1/organizations/{org.slug}/campaigns/{campaign_id}/send-now",
        headers=user_headers,
    )

    resp = await client.patch(
        f"/api/v1/organizations/{org.slug}/campaigns/{campaign_id}",
        json={"subject": "Updated subject"},
        headers=user_headers,
    )
    assert resp.status_code == 400
