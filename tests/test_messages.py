"""Attendee-to-attendee direct messages - gated behind an accepted
Connection, built on top of the existing connections system.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_accepted_connection(db: AsyncSession, user_a, user_b):
    from datetime import UTC, datetime

    from app.models.community import Connection

    conn = Connection(
        user_id=user_a.id,
        connected_user_id=user_b.id,
        status="accepted",
        responded_at=datetime.now(UTC),
    )
    db.add(conn)
    await db.flush()
    return conn


class TestSendMessage:
    async def test_cannot_message_unconnected_user(
        self, client: AsyncClient, user_headers, other_user
    ):
        resp = await client.post(
            f"/api/v1/messages/{other_user.id}",
            json={"body": "hey!"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    async def test_can_message_accepted_connection(
        self, client: AsyncClient, db: AsyncSession, user, user_headers, other_user
    ):
        await _make_accepted_connection(db, user, other_user)

        resp = await client.post(
            f"/api/v1/messages/{other_user.id}",
            json={"body": "Great meeting you at the event!"},
            headers=user_headers,
        )
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["body"] == "Great meeting you at the event!"
        assert data["sender_id"] == str(user.id)
        assert data["recipient_id"] == str(other_user.id)

    async def test_cannot_message_self(self, client: AsyncClient, user_headers, user):
        resp = await client.post(
            f"/api/v1/messages/{user.id}",
            json={"body": "hi me"},
            headers=user_headers,
        )
        assert resp.status_code == 400

    async def test_empty_message_rejected(
        self, client: AsyncClient, db: AsyncSession, user, user_headers, other_user
    ):
        await _make_accepted_connection(db, user, other_user)
        resp = await client.post(
            f"/api/v1/messages/{other_user.id}",
            json={"body": "   "},
            headers=user_headers,
        )
        assert resp.status_code == 422

    async def test_sending_creates_notification_for_recipient(
        self, client: AsyncClient, db: AsyncSession, user, user_headers, other_user
    ):
        from sqlalchemy import select

        from app.models.notification import Notification

        await _make_accepted_connection(db, user, other_user)
        await client.post(
            f"/api/v1/messages/{other_user.id}",
            json={"body": "hello there"},
            headers=user_headers,
        )
        notif = await db.scalar(
            select(Notification).where(
                Notification.user_id == other_user.id, Notification.type == "direct_message"
            )
        )
        assert notif is not None
        assert "hello there" in (notif.body or "")


class TestThreadsAndReadState:
    async def test_thread_messages_ordered_and_marks_read(
        self, client: AsyncClient, db: AsyncSession, user, user_headers, other_user, other_headers
    ):
        await _make_accepted_connection(db, user, other_user)
        await client.post(
            f"/api/v1/messages/{other_user.id}", json={"body": "first"}, headers=user_headers
        )
        await client.post(
            f"/api/v1/messages/{user.id}", json={"body": "second"}, headers=other_headers
        )

        resp = await client.get(f"/api/v1/messages/{other_user.id}", headers=user_headers)
        assert resp.status_code == 200
        bodies = [m["body"] for m in resp.json()["data"]]
        assert bodies == ["first", "second"]

        # fetching the thread marks the other person's messages as read
        resp = await client.get("/api/v1/messages", headers=user_headers)
        thread = next(t for t in resp.json()["data"] if t["other_user_id"] == str(other_user.id))
        assert thread["unread_count"] == 0

    async def test_list_threads_shows_unread_count(
        self, client: AsyncClient, db: AsyncSession, user, user_headers, other_user, other_headers
    ):
        await _make_accepted_connection(db, user, other_user)
        await client.post(
            f"/api/v1/messages/{user.id}", json={"body": "unread ping"}, headers=other_headers
        )

        resp = await client.get("/api/v1/messages", headers=user_headers)
        thread = next(t for t in resp.json()["data"] if t["other_user_id"] == str(other_user.id))
        assert thread["unread_count"] == 1
        assert thread["last_message"]["body"] == "unread ping"


class TestMessagePages:
    async def test_messages_list_redirects_when_signed_out(self, client: AsyncClient):
        resp = await client.get("/messages", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"].startswith("/login")

    async def test_thread_page_403s_when_not_connected(self, client: AsyncClient, user, other_user):
        from tests.conftest import _make_token

        client.cookies.set("heelo_access", _make_token(str(user.id)))
        resp = await client.get(f"/messages/{other_user.id}")
        assert resp.status_code == 403

    async def test_thread_page_renders_for_accepted_connection(
        self, client: AsyncClient, db: AsyncSession, user, other_user
    ):
        from tests.conftest import _make_token

        await _make_accepted_connection(db, user, other_user)
        client.cookies.set("heelo_access", _make_token(str(user.id)))
        resp = await client.get(f"/messages/{other_user.id}")
        assert resp.status_code == 200
        assert other_user.full_name in resp.text

    async def test_message_button_shown_on_profile_for_accepted_connection(
        self, client: AsyncClient, db: AsyncSession, user, other_user
    ):
        from tests.conftest import _make_token

        other_user.username = "otheruser"
        await db.flush()
        await _make_accepted_connection(db, user, other_user)

        client.cookies.set("heelo_access", _make_token(str(user.id)))
        resp = await client.get(f"/p/{other_user.username}")
        assert resp.status_code == 200
        assert f"/messages/{other_user.id}" in resp.text
