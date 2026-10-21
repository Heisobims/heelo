"""
Attendee-to-attendee connections ('mutuals'). The Connection table has existed
in the schema since the initial migration but was never wired to an API -
this activates it.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.community import Connection


async def send_request(
    db: AsyncSession,
    user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    *,
    event_id: uuid.UUID | None = None,
    message: str | None = None,
) -> Connection:
    if user_id == target_user_id:
        raise HTTPException(400, "You can't connect with yourself.")

    existing = await db.scalar(
        select(Connection).where(
            or_(
                (Connection.user_id == user_id) & (Connection.connected_user_id == target_user_id),
                (Connection.user_id == target_user_id) & (Connection.connected_user_id == user_id),
            )
        )
    )
    if existing:
        if existing.status == "blocked":
            raise HTTPException(403, "Can't send a connection request.")
        if existing.status == "accepted":
            return existing
        if existing.status == "pending" and existing.user_id == target_user_id:
            # They already asked us - accept it instead of creating a duplicate.
            from datetime import UTC, datetime

            existing.status = "accepted"
            existing.responded_at = datetime.now(UTC)
            await db.commit()
            await db.refresh(existing)
            return existing
        # Pending request we already sent - no-op, don't spam a new row.
        return existing

    conn = Connection(
        id=uuid.uuid4(),
        user_id=user_id,
        connected_user_id=target_user_id,
        event_id=event_id,
        message=message,
        status="pending",
    )
    db.add(conn)
    await db.flush()

    from app.models.notification import Notification
    from app.models.user import User

    requester = await db.scalar(select(User).where(User.id == user_id))
    requester_name = requester.full_name if requester else "Someone"
    db.add(
        Notification(
            id=uuid.uuid4(),
            user_id=target_user_id,
            type="connection_request",
            title=f"{requester_name} wants to connect",
            body=message,
            action_url=f"/p/{requester.username}" if requester and requester.username else None,
            icon="person_add",
            extra_data={"connection_id": str(conn.id), "requester_id": str(user_id)},
        )
    )
    await db.commit()
    await db.refresh(conn)
    return conn


async def respond_request(
    db: AsyncSession, connection_id: uuid.UUID, responder_user_id: uuid.UUID, *, accept: bool
) -> Connection:
    from datetime import UTC, datetime

    conn = await db.scalar(select(Connection).where(Connection.id == connection_id))
    if not conn:
        raise HTTPException(404, "Connection request not found.")
    if conn.connected_user_id != responder_user_id:
        raise HTTPException(403, "This request isn't addressed to you.")
    if conn.status != "pending":
        raise HTTPException(400, f"This request is already {conn.status}.")

    conn.status = "accepted" if accept else "declined"
    conn.responded_at = datetime.now(UTC)

    if accept:
        from app.models.notification import Notification
        from app.models.user import User

        responder = await db.scalar(select(User).where(User.id == responder_user_id))
        responder_name = responder.full_name if responder else "Someone"
        db.add(
            Notification(
                id=uuid.uuid4(),
                user_id=conn.user_id,
                type="connection_accepted",
                title=f"{responder_name} accepted your connection request",
                action_url=(
                    f"/p/{responder.username}" if responder and responder.username else None
                ),
                icon="how_to_reg",
                extra_data={"connection_id": str(conn.id)},
            )
        )

    await db.commit()
    await db.refresh(conn)
    return conn


async def connection_status(
    db: AsyncSession, user_id: uuid.UUID, other_user_id: uuid.UUID
) -> str | None:
    """None | 'pending_sent' | 'pending_received' | 'accepted' | 'declined' | 'blocked'."""
    conn = await db.scalar(
        select(Connection).where(
            or_(
                (Connection.user_id == user_id) & (Connection.connected_user_id == other_user_id),
                (Connection.user_id == other_user_id) & (Connection.connected_user_id == user_id),
            )
        )
    )
    if not conn:
        return None
    if conn.status == "pending":
        return "pending_sent" if conn.user_id == user_id else "pending_received"
    return conn.status


async def accepted_connection_user_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Every user_id this person has an accepted, mutual connection with."""
    rows = await db.execute(
        select(Connection.user_id, Connection.connected_user_id).where(
            Connection.status == "accepted",
            or_(Connection.user_id == user_id, Connection.connected_user_id == user_id),
        )
    )
    ids: set[uuid.UUID] = set()
    for a, b in rows.all():
        ids.add(b if a == user_id else a)
    return ids


async def list_pending_requests(db: AsyncSession, user_id: uuid.UUID) -> list[Connection]:
    """Requests received by this user, awaiting a response."""
    rows = await db.scalars(
        select(Connection)
        .where(Connection.connected_user_id == user_id, Connection.status == "pending")
        .order_by(Connection.created_at.desc())
    )
    return list(rows.all())


async def list_connectable_attendees(
    db: AsyncSession,
    event_id: uuid.UUID,
    *,
    exclude_user_id: uuid.UUID | None = None,
    limit: int = 20,
):
    """
    Other confirmed attendees of this event who have an opted-in public profile -
    this is how people actually discover who to connect with (there's no global
    attendee directory, discovery is scoped to a shared event).
    """
    from app.models.community import AttendeeProfile
    from app.models.ticketing import Registration
    from app.models.user import User

    stmt = (
        select(User, AttendeeProfile)
        .join(AttendeeProfile, AttendeeProfile.user_id == User.id)
        .join(Registration, Registration.user_id == User.id)
        .where(
            Registration.event_id == event_id,
            Registration.status.in_(["confirmed", "checked_in"]),
            AttendeeProfile.is_visible_in_directory == True,
            User.username.isnot(None),
        )
        .distinct()
        .limit(limit)
    )
    if exclude_user_id:
        stmt = stmt.where(User.id != exclude_user_id)

    rows = await db.execute(stmt)
    return rows.all()


async def batch_mutuals_going(
    db: AsyncSession, user_id: uuid.UUID, event_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """For a batch of events (e.g. a feed page): how many accepted connections are going to each?"""
    if not event_ids:
        return {}
    accepted_ids = await accepted_connection_user_ids(db, user_id)
    if not accepted_ids:
        return {}

    from sqlalchemy import func

    from app.models.ticketing import Registration

    rows = await db.execute(
        select(Registration.event_id, func.count(func.distinct(Registration.user_id)))
        .where(
            Registration.event_id.in_(event_ids),
            Registration.status.in_(["confirmed", "checked_in"]),
            Registration.user_id.in_(accepted_ids),
        )
        .group_by(Registration.event_id)
    )
    return dict(rows.all())
