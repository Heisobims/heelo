from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import EventSession
from app.schemas.agenda import SessionCreateRequest, SessionUpdateRequest


async def list_sessions(db: AsyncSession, event_id: uuid.UUID) -> list[EventSession]:
    stmt = (
        select(EventSession)
        .where(EventSession.event_id == event_id)
        .order_by(EventSession.sort_order, EventSession.start_datetime)
    )
    result = await db.scalars(stmt)
    return list(result.all())


async def get_session(db: AsyncSession, event_id: uuid.UUID, session_id: uuid.UUID) -> EventSession:
    session = await db.scalar(
        select(EventSession).where(EventSession.id == session_id, EventSession.event_id == event_id)
    )
    if not session:
        raise HTTPException(404, "Session not found.")
    return session


async def create_session(
    db: AsyncSession, event_id: uuid.UUID, data: SessionCreateRequest
) -> EventSession:
    if data.end_datetime <= data.start_datetime:
        raise HTTPException(422, "Session end time must be after start time.")
    session = EventSession(
        event_id=event_id,
        title=data.title,
        description=data.description,
        session_type=data.session_type,
        speaker_ids=[str(sid) for sid in data.speaker_ids],
        start_datetime=data.start_datetime,
        end_datetime=data.end_datetime,
        location_or_stream_url=data.location_or_stream_url,
        track=data.track,
        track_color=data.track_color,
        sort_order=data.sort_order,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def update_session(
    db: AsyncSession, session: EventSession, data: SessionUpdateRequest
) -> EventSession:
    updates = data.model_dump(exclude_unset=True)
    if "speaker_ids" in updates and updates["speaker_ids"] is not None:
        updates["speaker_ids"] = [str(sid) for sid in updates["speaker_ids"]]
    start = updates.get("start_datetime", session.start_datetime)
    end = updates.get("end_datetime", session.end_datetime)
    if end <= start:
        raise HTTPException(422, "Session end time must be after start time.")
    for field, value in updates.items():
        setattr(session, field, value)
    await db.commit()
    await db.refresh(session)
    return session


async def delete_session(db: AsyncSession, session: EventSession) -> None:
    await db.delete(session)
    await db.commit()


async def reorder_sessions(
    db: AsyncSession, event_id: uuid.UUID, session_ids: list[uuid.UUID]
) -> list[EventSession]:
    sessions = await list_sessions(db, event_id)
    by_id = {s.id: s for s in sessions}
    if set(session_ids) != set(by_id.keys()):
        raise HTTPException(
            422, "session_ids must include every session on this event exactly once."
        )
    for idx, sid in enumerate(session_ids):
        by_id[sid].sort_order = idx
    await db.commit()
    return await list_sessions(db, event_id)


async def toggle_session_bookmark(
    db: AsyncSession, *, session_id: uuid.UUID, user_id: uuid.UUID
) -> bool:
    from app.models.event import EventSessionBookmark

    existing = await db.scalar(
        select(EventSessionBookmark).where(
            EventSessionBookmark.session_id == session_id,
            EventSessionBookmark.user_id == user_id,
        )
    )
    if existing:
        await db.delete(existing)
        await db.commit()
        return False
    else:
        bm = EventSessionBookmark(session_id=session_id, user_id=user_id)
        db.add(bm)
        await db.commit()
        return True


async def get_user_bookmarked_session_ids(
    db: AsyncSession, *, event_id: uuid.UUID, user_id: uuid.UUID
) -> set[uuid.UUID]:
    from app.models.event import EventSession, EventSessionBookmark

    stmt = (
        select(EventSessionBookmark.session_id)
        .join(EventSession, EventSessionBookmark.session_id == EventSession.id)
        .where(
            EventSession.event_id == event_id,
            EventSessionBookmark.user_id == user_id,
        )
    )
    res = await db.scalars(stmt)
    return set(res.all())

