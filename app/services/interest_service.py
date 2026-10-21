"""Save-and-remind: lightweight 'interested' state, short of buying a ticket."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.community import EventInterest


async def mark_interested(db: AsyncSession, user_id: uuid.UUID, event_id: uuid.UUID) -> None:
    """Idempotent - marking twice is a no-op, not an error."""
    stmt = (
        pg_insert(EventInterest)
        .values(id=uuid.uuid4(), user_id=user_id, event_id=event_id)
        .on_conflict_do_nothing(constraint="uq_event_interest_user_event")
    )
    await db.execute(stmt)
    await db.commit()


async def unmark_interested(db: AsyncSession, user_id: uuid.UUID, event_id: uuid.UUID) -> None:
    row = await db.scalar(
        select(EventInterest).where(
            EventInterest.user_id == user_id, EventInterest.event_id == event_id
        )
    )
    if row:
        await db.delete(row)
        await db.commit()


async def is_interested(db: AsyncSession, user_id: uuid.UUID, event_id: uuid.UUID) -> bool:
    row = await db.scalar(
        select(EventInterest.id).where(
            EventInterest.user_id == user_id, EventInterest.event_id == event_id
        )
    )
    return row is not None


async def interested_event_ids_for_user(
    db: AsyncSession, user_id: uuid.UUID, event_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Batch check - which of these event_ids has the user marked interested? For card badges."""
    if not event_ids:
        return set()
    rows = await db.scalars(
        select(EventInterest.event_id).where(
            EventInterest.user_id == user_id, EventInterest.event_id.in_(event_ids)
        )
    )
    return set(rows.all())


async def get_interest_count(db: AsyncSession, event_id: uuid.UUID) -> int:
    from sqlalchemy import func

    return (
        await db.scalar(
            select(func.count(EventInterest.id)).where(EventInterest.event_id == event_id)
        )
        or 0
    )
