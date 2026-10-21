"""Tests for multi-track agenda sessions and attendee personal itinerary bookmarking."""

from __future__ import annotations

import uuid
from httpx import AsyncClient


class TestAgendaBookmarks:
    async def test_session_with_track_color_and_room(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        res = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sessions",
            json={
                "title": "Scaling Distributed Databases",
                "session_type": "workshop",
                "track": "Engineering",
                "track_color": "#10b981",
                "location_or_stream_url": "Breakout Room 3B",
                "description": "Deep dive into sharding and replication topologies",
                "start_datetime": "2027-02-15T14:00:00Z",
                "end_datetime": "2027-02-15T15:30:00Z",
            },
            headers=user_headers,
        )
        assert res.status_code == 201
        data = res.json()["data"]
        assert data["title"] == "Scaling Distributed Databases"
        assert data["track"] == "Engineering"
        assert data["track_color"] == "#10b981"
        assert data["location_or_stream_url"] == "Breakout Room 3B"

    async def test_session_bookmark_toggle(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        # Create a session
        res_s = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sessions",
            json={
                "title": "Opening Keynote",
                "session_type": "talk",
                "track": "Main Stage",
                "track_color": "#3b82f6",
                "start_datetime": "2027-02-15T09:00:00Z",
                "end_datetime": "2027-02-15T10:00:00Z",
            },
            headers=user_headers,
        )
        assert res_s.status_code == 201
        session_id = res_s.json()["data"]["id"]

        # 1. Bookmark session
        res_bm = await client.post(
            f"/api/v1/events/{published_event.slug}/sessions/{session_id}/bookmark",
            headers=user_headers,
        )
        assert res_bm.status_code == 200
        assert res_bm.json()["is_bookmarked"] is True

        # 2. Check bookmarks list endpoint
        res_list = await client.get(
            f"/api/v1/events/{published_event.slug}/sessions/bookmarks",
            headers=user_headers,
        )
        assert res_list.status_code == 200
        bms = res_list.json()["bookmarked_session_ids"]
        assert session_id in bms

        # 3. Toggle bookmark off
        res_unbm = await client.post(
            f"/api/v1/events/{published_event.slug}/sessions/{session_id}/bookmark",
            headers=user_headers,
        )
        assert res_unbm.status_code == 200
        assert res_unbm.json()["is_bookmarked"] is False

        # 4. Verify no longer in bookmarks
        res_list2 = await client.get(
            f"/api/v1/events/{published_event.slug}/sessions/bookmarks",
            headers=user_headers,
        )
        assert res_list2.status_code == 200
        assert session_id not in res_list2.json()["bookmarked_session_ids"]

