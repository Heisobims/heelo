"""Agenda builder - real CRUD on EventSession, replacing the old
Event.extras.agenda JSON blob, with speaker_ids wired to real Speaker rows
and drag-and-drop reordering persisted via a bulk reorder endpoint.
"""

from __future__ import annotations

from httpx import AsyncClient


class TestSessionCRUD:
    async def test_create_and_list_session(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sessions",
            json={
                "title": "Opening Keynote",
                "session_type": "talk",
                "start_datetime": "2027-01-01T10:00:00Z",
                "end_datetime": "2027-01-01T10:30:00Z",
            },
            headers=user_headers,
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["title"] == "Opening Keynote"
        assert data["session_type"] == "talk"

        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sessions",
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1

    async def test_end_before_start_rejected(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sessions",
            json={
                "title": "Bad Session",
                "start_datetime": "2027-01-01T10:30:00Z",
                "end_datetime": "2027-01-01T10:00:00Z",
            },
            headers=user_headers,
        )
        assert resp.status_code == 422

    async def test_session_speaker_ids_link_real_speakers(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/speakers",
            json={"name": "Panel Speaker", "role_type": "speaker"},
            headers=user_headers,
        )
        speaker_id = resp.json()["data"]["speaker_id"]

        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sessions",
            json={
                "title": "Fireside Chat",
                "speaker_ids": [speaker_id],
                "start_datetime": "2027-01-01T11:00:00Z",
                "end_datetime": "2027-01-01T11:30:00Z",
            },
            headers=user_headers,
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["speaker_ids"] == [speaker_id]

    async def test_update_and_delete_session(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sessions",
            json={
                "title": "Workshop",
                "start_datetime": "2027-01-01T12:00:00Z",
                "end_datetime": "2027-01-01T13:00:00Z",
            },
            headers=user_headers,
        )
        session_id = resp.json()["data"]["id"]

        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sessions/{session_id}",
            json={"title": "Updated Workshop", "session_type": "workshop"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["title"] == "Updated Workshop"
        assert resp.json()["data"]["session_type"] == "workshop"

        resp = await client.delete(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sessions/{session_id}",
            headers=user_headers,
        )
        assert resp.status_code == 204

    async def test_checkin_staff_cannot_create_session(
        self, client: AsyncClient, org, published_event, checkin_staff_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sessions",
            json={
                "title": "Unauthorized",
                "start_datetime": "2027-01-01T10:00:00Z",
                "end_datetime": "2027-01-01T10:30:00Z",
            },
            headers=checkin_staff_headers,
        )
        assert resp.status_code == 403

    async def test_public_sessions_endpoint(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sessions",
            json={
                "title": "Public Session",
                "start_datetime": "2027-01-01T10:00:00Z",
                "end_datetime": "2027-01-01T10:30:00Z",
            },
            headers=user_headers,
        )
        resp = await client.get(f"/api/v1/events/{published_event.slug}/sessions")
        assert resp.status_code == 200
        titles = [s["title"] for s in resp.json()["data"]]
        assert "Public Session" in titles


class TestSessionReorder:
    async def _create(self, client, org, event_id, headers, title, start, end):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{event_id}/sessions",
            json={"title": title, "start_datetime": start, "end_datetime": end},
            headers=headers,
        )
        return resp.json()["data"]["id"]

    async def test_reorder_persists_new_order(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        id_a = await self._create(
            client,
            org,
            published_event.id,
            user_headers,
            "A",
            "2027-01-01T09:00:00Z",
            "2027-01-01T09:30:00Z",
        )
        id_b = await self._create(
            client,
            org,
            published_event.id,
            user_headers,
            "B",
            "2027-01-01T10:00:00Z",
            "2027-01-01T10:30:00Z",
        )

        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sessions/reorder",
            json={"session_ids": [id_b, id_a]},
            headers=user_headers,
        )
        assert resp.status_code == 200
        ordered_ids = [s["id"] for s in resp.json()["data"]]
        assert ordered_ids == [id_b, id_a]

        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sessions",
            headers=user_headers,
        )
        ordered_ids = [s["id"] for s in resp.json()["data"]]
        assert ordered_ids == [id_b, id_a]

    async def test_reorder_rejects_incomplete_id_set(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        id_a = await self._create(
            client,
            org,
            published_event.id,
            user_headers,
            "A",
            "2027-01-01T09:00:00Z",
            "2027-01-01T09:30:00Z",
        )
        await self._create(
            client,
            org,
            published_event.id,
            user_headers,
            "B",
            "2027-01-01T10:00:00Z",
            "2027-01-01T10:30:00Z",
        )

        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sessions/reorder",
            json={"session_ids": [id_a]},
            headers=user_headers,
        )
        assert resp.status_code == 422
