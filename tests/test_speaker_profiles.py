"""Public speaker profile pages (GET /speakers/{slug}) - unlocked now that
Speaker is a real, slug-addressable record instead of a JSON blob entry.
"""

from __future__ import annotations

from httpx import AsyncClient


class TestSpeakerSlugs:
    async def test_speaker_gets_a_slug_on_create(self, client: AsyncClient, org, user_headers):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/speakers",
            json={"name": "Ada Lovelace"},
            headers=user_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["slug"] == "ada-lovelace"

    async def test_duplicate_names_get_unique_slugs(self, client: AsyncClient, org, user_headers):
        resp1 = await client.post(
            f"/api/v1/organizations/{org.slug}/speakers",
            json={"name": "John Doe"},
            headers=user_headers,
        )
        resp2 = await client.post(
            f"/api/v1/organizations/{org.slug}/speakers",
            json={"name": "John Doe"},
            headers=user_headers,
        )
        assert resp1.json()["data"]["slug"] == "john-doe"
        assert resp2.json()["data"]["slug"] == "john-doe-2"

    async def test_inline_event_speaker_also_gets_a_slug(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/speakers",
            json={"name": "Grace Hopper"},
            headers=user_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["speaker_slug"] == "grace-hopper"


class TestSpeakerProfilePage:
    async def test_profile_page_renders_for_speaker_on_published_event(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/speakers",
            json={"name": "Reshma Saujani", "role_type": "speaker"},
            headers=user_headers,
        )
        slug = resp.json()["data"]["speaker_slug"]

        resp = await client.get(f"/speakers/{slug}")
        assert resp.status_code == 200
        assert "Reshma Saujani" in resp.text
        assert published_event.title in resp.text

    async def test_profile_page_404_for_unknown_slug(self, client: AsyncClient):
        resp = await client.get("/speakers/does-not-exist")
        assert resp.status_code == 404

    async def test_profile_page_hides_draft_events(
        self, client: AsyncClient, org, event, user_headers
    ):
        # `event` fixture is status="draft"
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{event.id}/speakers",
            json={"name": "Draft-Only Speaker"},
            headers=user_headers,
        )
        slug = resp.json()["data"]["speaker_slug"]

        resp = await client.get(f"/speakers/{slug}")
        assert resp.status_code == 200
        assert "Draft-Only Speaker" in resp.text
        assert event.title not in resp.text
        assert "No public events yet" in resp.text
