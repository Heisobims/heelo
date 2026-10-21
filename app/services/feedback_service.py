from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.feedback import EventFeedback
from app.models.ticketing import Registration


async def submit_feedback(
    db: AsyncSession,
    registration_id: uuid.UUID,
    *,
    rating: int,
    comment: str | None,
) -> EventFeedback:
    """
    Record an attendee's post-event rating. Idempotent - resubmitting (e.g. the
    attendee changes their mind) updates the existing row rather than erroring,
    since one registration can only ever have one feedback entry.
    """
    reg = await db.scalar(
        select(Registration)
        .where(Registration.id == registration_id)
        .options(selectinload(Registration.event))
    )
    if not reg or not reg.event:
        raise HTTPException(404, "Registration not found.")
    if reg.status not in ("confirmed", "checked_in"):
        raise HTTPException(400, "This ticket isn't eligible to leave feedback.")
    if reg.event.start_datetime and datetime.now(UTC) < reg.event.start_datetime:
        raise HTTPException(400, "Feedback opens once the event has started.")

    existing = await db.scalar(
        select(EventFeedback).where(EventFeedback.registration_id == registration_id)
    )
    if existing:
        existing.rating = rating
        existing.comment = comment
        await db.commit()
        await db.refresh(existing)
        return existing

    feedback = EventFeedback(
        event_id=reg.event_id,
        registration_id=registration_id,
        rating=rating,
        comment=comment,
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    return feedback


async def get_event_feedback_summary(db: AsyncSession, event_id: uuid.UUID) -> dict:
    stats = (
        await db.execute(
            select(func.avg(EventFeedback.rating), func.count(EventFeedback.id)).where(
                EventFeedback.event_id == event_id
            )
        )
    ).one()
    avg_rating, count = stats

    recent = await db.scalars(
        select(EventFeedback)
        .where(EventFeedback.event_id == event_id)
        .options(selectinload(EventFeedback.registration))
        .order_by(EventFeedback.created_at.desc())
        .limit(20)
    )

    return {
        "average_rating": round(float(avg_rating), 2) if avg_rating is not None else None,
        "count": count or 0,
        "recent": [
            {
                "rating": f.rating,
                "comment": f.comment,
                "attendee_name": f.registration.attendee_name if f.registration else None,
                "created_at": f.created_at,
            }
            for f in recent.all()
        ],
    }
