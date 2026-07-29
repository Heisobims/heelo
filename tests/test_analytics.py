"""Analytics — event summary, ticket breakdown, sales over time, UTM."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def test_analytics_summary(client: AsyncClient, org, published_event, user_headers):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/analytics/summary",
        headers=user_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "total_registrations" in data
    assert "net_revenue" in data
    assert "checkin_rate" in data


async def test_analytics_ticket_breakdown(client: AsyncClient, org, published_event, user_headers):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/analytics/tickets",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


async def test_analytics_sales_over_time(client: AsyncClient, org, published_event, user_headers):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/analytics/sales",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


async def test_analytics_utm_breakdown(client: AsyncClient, org, published_event, user_headers):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/analytics/utm",
        headers=user_headers,
    )
    assert resp.status_code == 200


async def test_analytics_requires_org_membership(
    client: AsyncClient, org, published_event, other_headers
):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/analytics/summary",
        headers=other_headers,
    )
    assert resp.status_code == 403


async def test_analytics_nonexistent_event_returns_404(
    client: AsyncClient, org, user_headers
):
    import uuid
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{uuid.uuid4()}/analytics/summary",
        headers=user_headers,
    )
    assert resp.status_code == 404
