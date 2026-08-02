"""Speaker management — org-level speaker roster (real `speakers` table) plus
the event <-> speaker link (`event_speakers`) that replaced the old
Event.extras.people.* JSON blob.
"""

from __future__ import annotations

from httpx import AsyncClient


class TestOrgSpeakerRoster:
    async def test_create_and_list_speaker(self, client: AsyncClient, org, user_headers):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/speakers",
            json={"name": "Ada Lovelace", "title": "Engineer", "company": "Acme"},
            headers=user_headers,
        )
        assert resp.status_code == 201
        body = resp.json()["data"]
        assert body["name"] == "Ada Lovelace"

        resp = await client.get(f"/api/v1/organizations/{org.slug}/speakers", headers=user_headers)
        assert resp.status_code == 200
        names = [s["name"] for s in resp.json()["data"]]
        assert "Ada Lovelace" in names

    async def test_update_and_delete_speaker(self, client: AsyncClient, org, user_headers):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/speakers",
            json={"name": "Grace Hopper"},
            headers=user_headers,
        )
        speaker_id = resp.json()["data"]["id"]

        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}/speakers/{speaker_id}",
            json={"title": "Rear Admiral"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["title"] == "Rear Admiral"

        resp = await client.delete(
            f"/api/v1/organizations/{org.slug}/speakers/{speaker_id}", headers=user_headers
        )
        assert resp.status_code == 204

    async def test_checkin_staff_cannot_create_speaker(
        self, client: AsyncClient, org, checkin_staff_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/speakers",
            json={"name": "Unauthorized Person"},
            headers=checkin_staff_headers,
        )
        assert resp.status_code == 403


class TestEventSpeakerLinks:
    async def test_add_event_speaker_inline_creates_and_links(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/speakers",
            json={"name": "Reshma Saujani", "title": "Founder", "role_type": "speaker"},
            headers=user_headers,
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["name"] == "Reshma Saujani"
        assert data["role_type"] == "speaker"

        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/speakers",
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1

    async def test_add_event_speaker_links_existing_roster_speaker(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/speakers",
            json={"name": "Existing Speaker"},
            headers=user_headers,
        )
        speaker_id = resp.json()["data"]["id"]

        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/speakers",
            json={"speaker_id": speaker_id, "role_type": "panelist"},
            headers=user_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["speaker_id"] == speaker_id
        assert resp.json()["data"]["role_type"] == "panelist"

    async def test_add_event_speaker_requires_speaker_id_or_name(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/speakers",
            json={"role_type": "speaker"},
            headers=user_headers,
        )
        assert resp.status_code == 422

    async def test_remove_event_speaker_deletes_orphaned_roster_entry(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/speakers",
            json={"name": "One-Event Person"},
            headers=user_headers,
        )
        link_id = resp.json()["data"]["id"]
        speaker_id = resp.json()["data"]["speaker_id"]

        resp = await client.delete(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/speakers/{link_id}",
            headers=user_headers,
        )
        assert resp.status_code == 204

        resp = await client.get(f"/api/v1/organizations/{org.slug}/speakers", headers=user_headers)
        ids = [s["id"] for s in resp.json()["data"]]
        assert speaker_id not in ids

    async def test_remove_event_speaker_keeps_roster_entry_used_elsewhere(
        self, client: AsyncClient, org, event, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/speakers",
            json={"name": "Multi-Event Speaker"},
            headers=user_headers,
        )
        speaker_id = resp.json()["data"]["id"]

        resp1 = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{event.id}/speakers",
            json={"speaker_id": speaker_id},
            headers=user_headers,
        )
        link1_id = resp1.json()["data"]["id"]

        await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/speakers",
            json={"speaker_id": speaker_id},
            headers=user_headers,
        )

        resp = await client.delete(
            f"/api/v1/organizations/{org.slug}/events/{event.id}/speakers/{link1_id}",
            headers=user_headers,
        )
        assert resp.status_code == 204

        resp = await client.get(f"/api/v1/organizations/{org.slug}/speakers", headers=user_headers)
        ids = [s["id"] for s in resp.json()["data"]]
        assert speaker_id in ids

    async def test_checkin_staff_cannot_add_event_speaker(
        self, client: AsyncClient, org, published_event, checkin_staff_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/speakers",
            json={"name": "Unauthorized"},
            headers=checkin_staff_headers,
        )
        assert resp.status_code == 403

    async def test_public_event_speakers_endpoint(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/speakers",
            json={"name": "Public Speaker"},
            headers=user_headers,
        )
        resp = await client.get(f"/api/v1/events/{published_event.slug}/speakers")
        assert resp.status_code == 200
        names = [s["name"] for s in resp.json()["data"]]
        assert "Public Speaker" in names
