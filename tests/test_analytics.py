"""Analytics - event summary, ticket breakdown, sales over time, UTM."""

from __future__ import annotations

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


async def test_event_summary_is_cached(db, published_event, monkeypatch):
    """The dashboard summary query is hit on every page load - briefly
    cached (app/utils/cache.py) so it doesn't re-run two aggregate queries
    every time. Redis isn't running by default in tests (fail-open, so the
    live-query path above already exercises that); this specifically
    verifies the cache-hit round-trip with a fake Redis."""
    from app.services import analytics_service as an_svc
    from app.utils import cache as cache_mod

    class _FakeRedis:
        def __init__(self):
            self.store: dict[str, str] = {}

        def get(self, key):
            return self.store.get(key)

        def set(self, key, value, ex=None):
            self.store[key] = value

    fake = _FakeRedis()
    monkeypatch.setattr(cache_mod, "_redis", lambda: fake)

    first = await an_svc.get_event_summary(db, published_event.id)
    assert fake.store  # cache populated

    # Monkeypatch the real computation to prove the second call is served
    # from cache, not by hitting Postgres again.
    async def _boom(*a, **k):
        raise AssertionError("should have been served from cache")

    monkeypatch.setattr(an_svc, "_compute_event_summary", _boom)

    second = await an_svc.get_event_summary(db, published_event.id)
    assert second == first


async def test_analytics_ticket_breakdown(client: AsyncClient, org, published_event, user_headers):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/analytics/ticket-breakdown",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


async def test_analytics_sales_over_time(client: AsyncClient, org, published_event, user_headers):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/analytics/sales-chart",
        headers=user_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data["sales"], list)
    assert isinstance(data["registrations"], list)


async def test_analytics_utm_breakdown(client: AsyncClient, org, published_event, user_headers):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/analytics/utm-breakdown",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)


async def test_analytics_requires_org_membership(
    client: AsyncClient, org, published_event, other_headers
):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/analytics/summary",
        headers=other_headers,
    )
    assert resp.status_code == 403


async def test_analytics_nonexistent_event_returns_404(client: AsyncClient, org, user_headers):
    import uuid

    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{uuid.uuid4()}/analytics/summary",
        headers=user_headers,
    )
    assert resp.status_code == 404


async def test_analytics_summary_rejects_checkin_staff(
    client: AsyncClient, org, published_event, checkin_staff_headers
):
    """Regression test: analytics endpoints used to accept any org member,
    letting a low-trust checkin_staff login (meant only to scan tickets at the
    door) pull full revenue data. Now gated on FINANCE_VIEW."""
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/analytics/summary",
        headers=checkin_staff_headers,
    )
    assert resp.status_code == 403


async def test_analytics_export_csv_rejects_checkin_staff(
    client: AsyncClient, org, published_event, checkin_staff_headers
):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/analytics/export.csv",
        headers=checkin_staff_headers,
    )
    assert resp.status_code == 403


async def test_analytics_summary_allows_finance_role(
    client: AsyncClient, org, published_event, finance_headers
):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/analytics/summary",
        headers=finance_headers,
    )
    assert resp.status_code == 200
