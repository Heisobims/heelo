"""Live pulse — mid-event glanceable check-in rate, capacity fill, ticket tier breakdown."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import checkin_service as ci_svc


async def test_get_live_pulse_reflects_checkins(
    db: AsyncSession, published_event, ticket_type, registration
):
    stats = await ci_svc.get_live_pulse(db, published_event)

    assert stats["total"] == 1
    assert stats["checked_in"] == 0
    assert stats["ticket_tiers"][0]["name"] == "General Admission"
    assert stats["ticket_tiers"][0]["quantity"] == 100


async def test_get_live_pulse_capacity_percent_none_when_unlimited(
    db: AsyncSession, published_event, ticket_type, registration
):
    # published_event fixture doesn't set max_capacity — should stay None, not divide-by-zero.
    stats = await ci_svc.get_live_pulse(db, published_event)
    assert stats["capacity"] is None
    assert stats["percent_of_capacity"] is None


async def test_checkin_pulse_endpoint(
    client: AsyncClient, org, published_event, ticket_type, registration, user_headers
):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in/pulse",
        headers=user_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "ticket_tiers" in data
    assert data["total"] == 1


async def test_checkin_pulse_requires_org_membership(
    client: AsyncClient, org, published_event, ticket_type, registration, other_headers
):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in/pulse",
        headers=other_headers,
    )
    assert resp.status_code == 403


async def test_pulse_reflects_checked_in_registration(
    client: AsyncClient,
    db: AsyncSession,
    org,
    published_event,
    ticket_type,
    registration,
    user_headers,
):
    await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
        json={"registration_id": str(registration.id)},
        headers=user_headers,
    )

    stats = await ci_svc.get_live_pulse(db, published_event)
    assert stats["checked_in"] == 1
    assert stats["ticket_tiers"][0]["checked_in"] == 1
