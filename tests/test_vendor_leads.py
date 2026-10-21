"""Vendor lead capture - POST /vendors/{slug}/contact and GET /vendors/me/leads.
The vendor marketplace's core monetization path had zero test coverage."""

from __future__ import annotations

from httpx import AsyncClient


def _vendor_payload(**overrides) -> dict:
    payload = {
        "business_name": "Lagos Lens Co.",
        "category": "photography",
        "cover_image_url": "https://example.com/cover.jpg",
    }
    payload.update(overrides)
    return payload


async def _create_vendor(client: AsyncClient, headers: dict) -> dict:
    resp = await client.post("/api/v1/vendors", json=_vendor_payload(), headers=headers)
    assert resp.status_code == 201
    return resp.json()["data"]


async def test_contact_vendor_creates_a_lead(client: AsyncClient, user_headers):
    vendor = await _create_vendor(client, user_headers)

    resp = await client.post(
        f"/api/v1/vendors/{vendor['slug']}/contact",
        json={
            "requester_name": "Ada Organizer",
            "requester_email": "ada@example.com",
            "event_name": "Lagos Tech Summit",
            "message": "Are you available on the 15th?",
        },
    )
    assert resp.status_code == 201
    assert "id" in resp.json()["data"]


async def test_contact_vendor_requires_name_and_email(client: AsyncClient, user_headers):
    vendor = await _create_vendor(client, user_headers)

    resp = await client.post(
        f"/api/v1/vendors/{vendor['slug']}/contact",
        json={"event_name": "No name or email"},
    )
    assert resp.status_code == 422


async def test_contact_unknown_vendor_returns_404(client: AsyncClient):
    resp = await client.post(
        "/api/v1/vendors/not-a-real-vendor/contact",
        json={"requester_name": "Ada", "requester_email": "ada@example.com"},
    )
    assert resp.status_code == 404


async def test_contact_inactive_vendor_returns_404(client: AsyncClient, db, user_headers):
    vendor_data = await _create_vendor(client, user_headers)

    from sqlalchemy import select

    from app.models.vendor import Vendor

    vendor = await db.scalar(select(Vendor).where(Vendor.slug == vendor_data["slug"]))
    vendor.status = "pending"
    await db.commit()

    resp = await client.post(
        f"/api/v1/vendors/{vendor_data['slug']}/contact",
        json={"requester_name": "Ada", "requester_email": "ada@example.com"},
    )
    assert resp.status_code == 404


async def test_contact_vendor_dispatches_notification_via_celery(
    client: AsyncClient, user_headers, monkeypatch
):
    """The vendor notification email is sent via a Celery task (.delay()),
    not inline in the request - a slow/down email provider must not block
    this public, unauthenticated endpoint."""
    vendor = await _create_vendor(client, user_headers)

    from unittest.mock import MagicMock

    import app.tasks.email as email_tasks

    fake_delay = MagicMock()
    monkeypatch.setattr(email_tasks.send_vendor_lead_notification, "delay", fake_delay)

    resp = await client.post(
        f"/api/v1/vendors/{vendor['slug']}/contact",
        json={"requester_name": "Ada", "requester_email": "ada@example.com"},
    )
    assert resp.status_code == 201
    fake_delay.assert_called_once()


async def test_contact_vendor_survives_notification_enqueue_failure(
    client: AsyncClient, user_headers, monkeypatch
):
    """The lead must still be recorded even if dispatching the notification
    task fails (e.g. broker unreachable) - losing the lead entirely would be
    worse than a missed email, and the router already wraps the dispatch in
    try/except."""
    vendor = await _create_vendor(client, user_headers)

    import app.tasks.email as email_tasks

    def _boom(*a, **k):
        raise RuntimeError("broker down")

    monkeypatch.setattr(email_tasks.send_vendor_lead_notification, "delay", _boom)

    resp = await client.post(
        f"/api/v1/vendors/{vendor['slug']}/contact",
        json={"requester_name": "Ada", "requester_email": "ada@example.com"},
    )
    assert resp.status_code == 201


async def test_contact_vendor_rate_limited_per_ip(client: AsyncClient, user_headers, monkeypatch):
    import app.routers.vendor as vendor_router
    from app.utils import rate_limit as rl

    class _FakeRedis:
        def __init__(self):
            self.counts: dict[str, int] = {}

        def incr(self, key):
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

        def expire(self, key, seconds):
            pass

    fake = _FakeRedis()
    monkeypatch.setattr(rl, "_redis", lambda: fake)

    vendor = await _create_vendor(client, user_headers)

    for _ in range(vendor_router._CONTACT_MAX_PER_IP):
        resp = await client.post(
            f"/api/v1/vendors/{vendor['slug']}/contact",
            json={"requester_name": "Ada", "requester_email": "ada@example.com"},
        )
        assert resp.status_code == 201

    resp = await client.post(
        f"/api/v1/vendors/{vendor['slug']}/contact",
        json={"requester_name": "Ada", "requester_email": "ada@example.com"},
    )
    assert resp.status_code == 429


async def test_get_my_leads_returns_leads_for_vendor_owner(client: AsyncClient, user_headers):
    vendor = await _create_vendor(client, user_headers)
    await client.post(
        f"/api/v1/vendors/{vendor['slug']}/contact",
        json={
            "requester_name": "Ada Organizer",
            "requester_email": "ada@example.com",
            "event_name": "Lagos Tech Summit",
        },
    )

    resp = await client.get("/api/v1/vendors/me/leads", headers=user_headers)
    assert resp.status_code == 200
    leads = resp.json()["data"]
    assert len(leads) == 1
    assert leads[0]["requester_email"] == "ada@example.com"
    assert leads[0]["status"] == "new"


async def test_get_my_leads_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/vendors/me/leads")
    assert resp.status_code == 401


async def test_get_my_leads_404_without_a_vendor_profile(client: AsyncClient, other_headers):
    resp = await client.get("/api/v1/vendors/me/leads", headers=other_headers)
    assert resp.status_code == 404


async def test_leads_are_isolated_per_vendor(client: AsyncClient, user_headers, other_headers):
    vendor_a = await _create_vendor(client, user_headers)
    await _create_vendor(client, other_headers)

    await client.post(
        f"/api/v1/vendors/{vendor_a['slug']}/contact",
        json={"requester_name": "Ada", "requester_email": "ada@example.com"},
    )

    resp_a = await client.get("/api/v1/vendors/me/leads", headers=user_headers)
    resp_b = await client.get("/api/v1/vendors/me/leads", headers=other_headers)
    assert len(resp_a.json()["data"]) == 1
    assert len(resp_b.json()["data"]) == 0
