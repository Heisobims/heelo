from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.live import Poll, PollOption, Question
from app.schemas.live import PollCreateRequest, QuestionCreateRequest, QuestionUpdateRequest

# ── Polls ────────────────────────────────────────────────────────────────────


async def create_poll(db: AsyncSession, event_id: uuid.UUID, data: PollCreateRequest) -> Poll:
    poll = Poll(event_id=event_id, question=data.question, status="draft")
    poll.options = [PollOption(text=text, sort_order=idx) for idx, text in enumerate(data.options)]
    db.add(poll)
    await db.commit()
    await db.refresh(poll, attribute_names=["options"])
    return poll


async def list_polls(db: AsyncSession, event_id: uuid.UUID) -> list[Poll]:
    result = await db.scalars(
        select(Poll)
        .where(Poll.event_id == event_id)
        .options(selectinload(Poll.options))
        .order_by(Poll.created_at.desc())
    )
    return list(result.all())


async def get_poll(db: AsyncSession, event_id: uuid.UUID, poll_id: uuid.UUID) -> Poll:
    poll = await db.scalar(
        select(Poll)
        .where(Poll.id == poll_id, Poll.event_id == event_id)
        .options(selectinload(Poll.options))
    )
    if not poll:
        raise HTTPException(404, "Poll not found.")
    return poll


async def get_open_poll(db: AsyncSession, event_id: uuid.UUID) -> Poll | None:
    return await db.scalar(
        select(Poll)
        .where(Poll.event_id == event_id, Poll.status == "open")
        .options(selectinload(Poll.options))
        .order_by(Poll.created_at.desc())
        .limit(1)
    )


async def set_poll_status(
    db: AsyncSession, event_id: uuid.UUID, poll_id: uuid.UUID, status: str
) -> Poll:
    poll = await get_poll(db, event_id, poll_id)
    if status == "open":
        # Only one poll open at a time — auto-close any others still open.
        await db.execute(
            update(Poll)
            .where(Poll.event_id == event_id, Poll.status == "open")
            .values(status="closed")
        )
    poll.status = status
    await db.commit()
    await db.refresh(poll, attribute_names=["options"])
    return poll


async def delete_poll(db: AsyncSession, poll: Poll) -> None:
    await db.delete(poll)
    await db.commit()


async def vote_poll(
    db: AsyncSession, event_id: uuid.UUID, poll_id: uuid.UUID, option_id: uuid.UUID
) -> Poll:
    poll = await get_poll(db, event_id, poll_id)
    if poll.status != "open":
        raise HTTPException(400, "This poll isn't open for voting.")
    if not any(o.id == option_id for o in poll.options):
        raise HTTPException(404, "Option not found on this poll.")

    # Atomic row-level increment — safe under concurrent votes.
    await db.execute(
        update(PollOption)
        .where(PollOption.id == option_id)
        .values(vote_count=PollOption.vote_count + 1)
    )
    await db.commit()
    return await get_poll(db, event_id, poll_id)


# ── Q&A ──────────────────────────────────────────────────────────────────────


async def create_question(
    db: AsyncSession, event_id: uuid.UUID, data: QuestionCreateRequest
) -> Question:
    q = Question(
        event_id=event_id,
        body=data.body.strip(),
        author_name=(data.author_name or "").strip() or None,
    )
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return q


async def list_questions(
    db: AsyncSession, event_id: uuid.UUID, *, include_hidden: bool = False
) -> list[Question]:
    stmt = select(Question).where(Question.event_id == event_id)
    if not include_hidden:
        stmt = stmt.where(Question.is_hidden.is_(False))
    stmt = stmt.order_by(Question.upvotes.desc(), Question.created_at.asc())
    result = await db.scalars(stmt)
    return list(result.all())


async def get_question(db: AsyncSession, event_id: uuid.UUID, question_id: uuid.UUID) -> Question:
    q = await db.scalar(
        select(Question).where(Question.id == question_id, Question.event_id == event_id)
    )
    if not q:
        raise HTTPException(404, "Question not found.")
    return q


async def upvote_question(
    db: AsyncSession, event_id: uuid.UUID, question_id: uuid.UUID
) -> Question:
    q = await get_question(db, event_id, question_id)
    await db.execute(
        update(Question).where(Question.id == question_id).values(upvotes=Question.upvotes + 1)
    )
    await db.commit()
    await db.refresh(q)
    return q


async def update_question(
    db: AsyncSession, question: Question, data: QuestionUpdateRequest
) -> Question:
    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(question, field, value)
    await db.commit()
    await db.refresh(question)
    return question


async def delete_question(db: AsyncSession, question: Question) -> None:
    await db.delete(question)
    await db.commit()
