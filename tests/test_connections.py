"""Attendee-to-attendee connections ('mutuals') - activating the dormant Connection table."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import connection_service as conn_svc


async def test_send_request_creates_pending_connection(db: AsyncSession, user, other_user):
    conn = await conn_svc.send_request(db, user.id, other_user.id)
    assert conn.status == "pending"
    assert conn.user_id == user.id
    assert conn.connected_user_id == other_user.id


async def test_cannot_connect_to_self(db: AsyncSession, user):
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await conn_svc.send_request(db, user.id, user.id)


async def test_respond_request_accept(db: AsyncSession, user, other_user):
    conn = await conn_svc.send_request(db, user.id, other_user.id)
    accepted = await conn_svc.respond_request(db, conn.id, other_user.id, accept=True)
    assert accepted.status == "accepted"


async def test_respond_request_decline(db: AsyncSession, user, other_user):
    conn = await conn_svc.send_request(db, user.id, other_user.id)
    declined = await conn_svc.respond_request(db, conn.id, other_user.id, accept=False)
    assert declined.status == "declined"


async def test_only_the_target_can_respond(db: AsyncSession, user, other_user, admin_user):
    conn = await conn_svc.send_request(db, user.id, other_user.id)
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await conn_svc.respond_request(db, conn.id, admin_user.id, accept=True)


async def test_duplicate_pending_request_returns_existing_not_a_new_row(
    db: AsyncSession, user, other_user
):
    first = await conn_svc.send_request(db, user.id, other_user.id)
    second = await conn_svc.send_request(db, user.id, other_user.id)
    assert first.id == second.id


async def test_reverse_request_auto_accepts_instead_of_duplicating(
    db: AsyncSession, user, other_user
):
    """If B already asked A, A asking B back should accept - not create a duplicate."""
    original = await conn_svc.send_request(db, user.id, other_user.id)
    reverse = await conn_svc.send_request(db, other_user.id, user.id)

    assert reverse.id == original.id
    assert reverse.status == "accepted"


async def test_connection_status_reflects_both_sides(db: AsyncSession, user, other_user):
    await conn_svc.send_request(db, user.id, other_user.id)

    assert await conn_svc.connection_status(db, user.id, other_user.id) == "pending_sent"
    assert await conn_svc.connection_status(db, other_user.id, user.id) == "pending_received"


async def test_accepted_connection_user_ids(db: AsyncSession, user, other_user, admin_user):
    conn = await conn_svc.send_request(db, user.id, other_user.id)
    await conn_svc.respond_request(db, conn.id, other_user.id, accept=True)
    await conn_svc.send_request(db, user.id, admin_user.id)  # left pending, not accepted

    ids = await conn_svc.accepted_connection_user_ids(db, user.id)
    assert ids == {other_user.id}


async def test_list_pending_requests(db: AsyncSession, user, other_user):
    await conn_svc.send_request(db, user.id, other_user.id)
    pending = await conn_svc.list_pending_requests(db, other_user.id)
    assert len(pending) == 1
    assert pending[0].user_id == user.id


# ── API ──────────────────────────────────────────────────────────────────────


async def test_send_connection_request_endpoint(client: AsyncClient, other_user, user_headers):
    resp = await client.post(
        "/api/v1/connections",
        json={"target_user_id": str(other_user.id)},
        headers=user_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["status"] == "pending"


async def test_accept_connection_request_endpoint(
    client: AsyncClient, db: AsyncSession, user, other_user, user_headers, other_headers
):
    conn = await conn_svc.send_request(db, user.id, other_user.id)
    resp = await client.post(f"/api/v1/connections/{conn.id}/accept", headers=other_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "accepted"


async def test_creates_notification_for_target(
    client: AsyncClient, db: AsyncSession, user, other_user, user_headers
):
    from sqlalchemy import select

    from app.models.notification import Notification

    await client.post(
        "/api/v1/connections",
        json={"target_user_id": str(other_user.id)},
        headers=user_headers,
    )

    notif = await db.scalar(
        select(Notification).where(
            Notification.user_id == other_user.id, Notification.type == "connection_request"
        )
    )
    assert notif is not None
    assert user.full_name in notif.title
