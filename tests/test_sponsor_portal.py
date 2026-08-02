"""Sponsor self-service portal — organizer invites a sponsor's contact email,
they claim the listing with a real Heelo account, and can then edit their own
logo/website/description. Also covers exhibitor fields, which reuse the
Sponsor model instead of a separate table.
"""

from __future__ import annotations

from httpx import AsyncClient


class TestExhibitorFields:
    async def test_create_exhibitor_sponsor(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sponsors",
            json={
                "name": "Booth Co",
                "is_exhibitor": True,
                "booth_number": "A12",
                "category": "hardware",
            },
            headers=user_headers,
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["is_exhibitor"] is True
        assert data["booth_number"] == "A12"
        assert data["category"] == "hardware"


class TestSponsorInviteAndClaim:
    async def _create_sponsor(self, client, org, event_id, headers):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{event_id}/sponsors",
            json={"name": "Acme Corp"},
            headers=headers,
        )
        return resp.json()["data"]["id"]

    async def _invite(self, client, org, event_id, sponsor_id, headers, email="sponsor@acme.com"):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{event_id}/sponsors/{sponsor_id}/invite",
            json={"email": email},
            headers=headers,
        )
        assert resp.status_code == 201
        return email

    def _extract_token(self, sponsor_service_module, sponsor_id):
        return sponsor_service_module._make_sponsor_invite_token(sponsor_id)

    async def test_invite_sets_contact_email(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        sponsor_id = await self._create_sponsor(client, org, published_event.id, user_headers)
        await self._invite(client, org, published_event.id, sponsor_id, user_headers)

        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sponsors",
            headers=user_headers,
        )
        sponsor = next(s for s in resp.json()["data"] if s["id"] == sponsor_id)
        assert sponsor["contact_email"] == "sponsor@acme.com"
        assert sponsor["user_id"] is None

    async def test_checkin_staff_cannot_invite_sponsor(
        self, client: AsyncClient, org, published_event, user_headers, checkin_staff_headers
    ):
        sponsor_id = await self._create_sponsor(client, org, published_event.id, user_headers)
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}"
            f"/sponsors/{sponsor_id}/invite",
            json={"email": "x@example.com"},
            headers=checkin_staff_headers,
        )
        assert resp.status_code == 403

    async def test_preview_invite_token(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        import uuid

        sponsor_id = await self._create_sponsor(client, org, published_event.id, user_headers)
        from app.services import sponsor_service as sp_svc

        token = sp_svc._make_sponsor_invite_token(uuid.UUID(sponsor_id))

        resp = await client.get(f"/api/v1/sponsor-portal/invite/{token}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["sponsor_name"] == "Acme Corp"
        assert data["event_title"] == published_event.title
        assert data["already_claimed"] is False

    async def test_invalid_token_rejected(self, client: AsyncClient):
        resp = await client.get("/api/v1/sponsor-portal/invite/not-a-real-token")
        assert resp.status_code == 400

    async def test_claim_requires_auth(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        import uuid

        sponsor_id = await self._create_sponsor(client, org, published_event.id, user_headers)
        from app.services import sponsor_service as sp_svc

        token = sp_svc._make_sponsor_invite_token(uuid.UUID(sponsor_id))

        resp = await client.post(f"/api/v1/sponsor-portal/invite/{token}/claim")
        assert resp.status_code == 401

    async def test_claim_links_user_and_appears_in_my_sponsorships(
        self, client: AsyncClient, org, published_event, user_headers, other_headers, other_user
    ):
        import uuid

        sponsor_id = await self._create_sponsor(client, org, published_event.id, user_headers)
        from app.services import sponsor_service as sp_svc

        token = sp_svc._make_sponsor_invite_token(uuid.UUID(sponsor_id))

        resp = await client.post(
            f"/api/v1/sponsor-portal/invite/{token}/claim", headers=other_headers
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["user_id"] == str(other_user.id)

        resp = await client.get("/api/v1/sponsor-portal/me", headers=other_headers)
        ids = [s["id"] for s in resp.json()["data"]]
        assert sponsor_id in ids

    async def test_non_owner_cannot_edit_claimed_sponsor(
        self, client: AsyncClient, org, published_event, user_headers, other_headers, user
    ):
        import uuid

        sponsor_id = await self._create_sponsor(client, org, published_event.id, user_headers)
        from app.services import sponsor_service as sp_svc

        token = sp_svc._make_sponsor_invite_token(uuid.UUID(sponsor_id))
        await client.post(f"/api/v1/sponsor-portal/invite/{token}/claim", headers=user_headers)

        resp = await client.patch(
            f"/api/v1/sponsor-portal/me/{sponsor_id}",
            json={"description": "hijacked"},
            headers=other_headers,
        )
        assert resp.status_code == 404

    async def test_owner_can_edit_claimed_sponsor(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        import uuid

        sponsor_id = await self._create_sponsor(client, org, published_event.id, user_headers)
        from app.services import sponsor_service as sp_svc

        token = sp_svc._make_sponsor_invite_token(uuid.UUID(sponsor_id))
        await client.post(f"/api/v1/sponsor-portal/invite/{token}/claim", headers=user_headers)

        resp = await client.patch(
            f"/api/v1/sponsor-portal/me/{sponsor_id}",
            json={"description": "We build things.", "website": "https://acme.example"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["description"] == "We build things."
        assert resp.json()["data"]["website"] == "https://acme.example"


class TestSponsorPortalPages:
    async def test_claim_page_renders_signed_out(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        import uuid

        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sponsors",
            json={"name": "Page Test Sponsor"},
            headers=user_headers,
        )
        sponsor_id = resp.json()["data"]["id"]
        from app.services import sponsor_service as sp_svc

        token = sp_svc._make_sponsor_invite_token(uuid.UUID(sponsor_id))

        resp = await client.get(f"/sponsor-invite/{token}")
        assert resp.status_code == 200
        assert "Page Test Sponsor" in resp.text
        assert "Sign in" in resp.text

    async def test_my_sponsorships_redirects_when_signed_out(self, client: AsyncClient):
        resp = await client.get("/my-sponsorships", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"].startswith("/login")
