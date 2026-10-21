"""
Attendee-to-attendee direct messages. No separate conversation table - a
thread is just every DirectMessage row between two user ids, grouped
in Python (mirrors inbox_service's phone-keyed threads, but the "other
party" here depends on which side of sender/recipient the current user is
on, so it isn't a single GROUP BY column the way phone number is).

Sending requires an accepted Connection between the two users - DMs are
gated behind mutual connection, not open to any two attendees.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.community import DirectMessage
from app.services import connection_service as conn_svc


async def send_message(
    db: AsyncSession, sender_id: uuid.UUID, recipient_id: uuid.UUID, body: str
) -> DirectMessage:
    if sender_id == recipient_id:
        raise HTTPException(400, "You can't message yourself.")

    status = await conn_svc.connection_status(db, sender_id, recipient_id)
    if status != "accepted":
        raise HTTPException(403, "You can only message people you're connected with.")

    body = body.strip()
    if not body:
        raise HTTPException(422, "Message cannot be empty.")

    msg = DirectMessage(sender_id=sender_id, recipient_id=recipient_id, body=body)
    db.add(msg)
    await db.flush()

    from app.models.notification import Notification
    from app.models.user import User

    sender = await db.scalar(select(User).where(User.id == sender_id))
    sender_name = sender.full_name if sender else "Someone"
    db.add(
        Notification(
            user_id=recipient_id,
            type="direct_message",
            title=f"New message from {sender_name}",
            body=body[:200],
            action_url=f"/messages/{sender_id}",
            icon="mail",
            extra_data={"sender_id": str(sender_id)},
        )
    )
    await db.commit()
    await db.refresh(msg)
    return msg


async def list_threads(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    """One entry per person this user has exchanged messages with - last
    message + unread count, most recent thread first."""
    rows = await db.scalars(
        select(DirectMessage)
        .where(or_(DirectMessage.sender_id == user_id, DirectMessage.recipient_id == user_id))
        .order_by(DirectMessage.created_at.desc())
    )

    threads: dict[uuid.UUID, dict] = {}
    for m in rows.all():
        other_id = m.recipient_id if m.sender_id == user_id else m.sender_id
        if other_id not in threads:
            threads[other_id] = {"other_user_id": other_id, "last_message": m, "unread_count": 0}
        if m.recipient_id == user_id and not m.is_read:
            threads[other_id]["unread_count"] += 1
    return list(threads.values())


async def get_thread_messages(
    db: AsyncSession, user_id: uuid.UUID, other_user_id: uuid.UUID, limit: int = 200
) -> list[DirectMessage]:
    rows = await db.scalars(
        select(DirectMessage)
        .where(
            or_(
                (DirectMessage.sender_id == user_id)
                & (DirectMessage.recipient_id == other_user_id),
                (DirectMessage.sender_id == other_user_id)
                & (DirectMessage.recipient_id == user_id),
            )
        )
        .order_by(DirectMessage.created_at.asc())
        .limit(limit)
    )
    return list(rows.all())


async def mark_thread_read(db: AsyncSession, user_id: uuid.UUID, other_user_id: uuid.UUID) -> None:
    await db.execute(
        update(DirectMessage)
        .where(
            DirectMessage.recipient_id == user_id,
            DirectMessage.sender_id == other_user_id,
            DirectMessage.is_read.is_(False),
        )
        .values(is_read=True)
    )
    await db.commit()
