"""Sponsor management — event-scoped `sponsors` table, replacing the old
Event.extras.partners JSON blob.
"""

from __future__ import annotations

from httpx import AsyncClient


class TestSponsorCRUD:
    async def test_create_and_list_sponsor(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sponsors",
            json={"name": "Acme Corp", "tier": "gold", "website": "https://acme.example"},
            headers=user_headers,
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["name"] == "Acme Corp"
        assert data["tier"] == "gold"

        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sponsors",
            headers=user_headers,
        )
        assert resp.status_code == 200
        names = [s["name"] for s in resp.json()["data"]]
        assert "Acme Corp" in names

    async def test_update_and_delete_sponsor(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sponsors",
            json={"name": "Beta Inc"},
            headers=user_headers,
        )
        sponsor_id = resp.json()["data"]["id"]
        assert resp.json()["data"]["tier"] == "partner"

        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sponsors/{sponsor_id}",
            json={"tier": "platinum"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["tier"] == "platinum"

        resp = await client.delete(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sponsors/{sponsor_id}",
            headers=user_headers,
        )
        assert resp.status_code == 204

    async def test_checkin_staff_cannot_create_sponsor(
        self, client: AsyncClient, org, published_event, checkin_staff_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sponsors",
            json={"name": "Unauthorized"},
            headers=checkin_staff_headers,
        )
        assert resp.status_code == 403

    async def test_public_sponsors_endpoint(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sponsors",
            json={"name": "Public Sponsor", "tier": "media"},
            headers=user_headers,
        )
        resp = await client.get(f"/api/v1/events/{published_event.slug}/sponsors")
        assert resp.status_code == 200
        names = [s["name"] for s in resp.json()["data"]]
        assert "Public Sponsor" in names

    async def test_sponsor_scoped_to_its_event(
        self, client: AsyncClient, org, event, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sponsors",
            json={"name": "Only On Published Event"},
            headers=user_headers,
        )
        sponsor_id = resp.json()["data"]["id"]

        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{event.id}/sponsors", headers=user_headers
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == []

        resp = await client.delete(
            f"/api/v1/organizations/{org.slug}/events/{event.id}/sponsors/{sponsor_id}",
            headers=user_headers,
        )
        assert resp.status_code == 404
