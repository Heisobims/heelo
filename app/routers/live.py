from __future__ import annotations

import asyncio
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.database import AsyncSessionLocal
from app.dependencies import DBSession, OrgAccess
from app.permissions import Permission, require_permission
from app.schemas.live import (
    PollCreateRequest,
    PollVoteRequest,
    QuestionCreateRequest,
    QuestionUpdateRequest,
)
from app.services import live_service as live_svc

LiveEngagementManageAccess = Annotated[
    tuple, Depends(require_permission(Permission.LIVE_ENGAGEMENT_MANAGE))
]


def _poll_out(poll) -> dict:
    return {
        "id": str(poll.id),
        "question": poll.question,
        "status": poll.status,
        "options": [
            {"id": str(o.id), "text": o.text, "vote_count": o.vote_count} for o in poll.options
        ],
        "created_at": poll.created_at.isoformat(),
    }


def _question_out(q) -> dict:
    return {
        "id": str(q.id),
        "body": q.body,
        "author_name": q.author_name,
        "upvotes": q.upvotes,
        "is_answered": q.is_answered,
        "is_hidden": q.is_hidden,
        "created_at": q.created_at.isoformat(),
    }


# ── Organizer API ────────────────────────────────────────────────────────────

router_org = APIRouter(
    prefix="/api/v1/organizations/{slug}/events/{event_id}/live", tags=["live-organizer"]
)


async def _get_event_for_org(db, event_id_str: str, org_id: uuid.UUID):
    from sqlalchemy import select

    from app.models.event import Event

    try:
        eid = uuid.UUID(event_id_str)
    except ValueError as err:
        raise HTTPException(422, "Invalid event ID.") from err
    event = await db.scalar(select(Event).where(Event.id == eid, Event.org_id == org_id))
    if not event:
        raise HTTPException(404, "Event not found.")
    return event


@router_org.get("/polls")
async def list_polls(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    polls = await live_svc.list_polls(db, event.id)
    return {"success": True, "data": [_poll_out(p) for p in polls]}


@router_org.post("/polls", status_code=201)
async def create_poll(
    slug: str,
    event_id: str,
    data: PollCreateRequest,
    db: DBSession,
    org_access: LiveEngagementManageAccess,
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    poll = await live_svc.create_poll(db, event.id, data)
    return {"success": True, "data": _poll_out(poll)}


@router_org.post("/polls/{poll_id}/open")
async def open_poll(
    slug: str, event_id: str, poll_id: str, db: DBSession, org_access: LiveEngagementManageAccess
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    try:
        pid = uuid.UUID(poll_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid poll ID.") from err
    poll = await live_svc.set_poll_status(db, event.id, pid, "open")
    return {"success": True, "data": _poll_out(poll)}


@router_org.post("/polls/{poll_id}/close")
async def close_poll(
    slug: str, event_id: str, poll_id: str, db: DBSession, org_access: LiveEngagementManageAccess
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    try:
        pid = uuid.UUID(poll_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid poll ID.") from err
    poll = await live_svc.set_poll_status(db, event.id, pid, "closed")
    return {"success": True, "data": _poll_out(poll)}


@router_org.delete("/polls/{poll_id}", status_code=204)
async def delete_poll(
    slug: str, event_id: str, poll_id: str, db: DBSession, org_access: LiveEngagementManageAccess
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    try:
        pid = uuid.UUID(poll_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid poll ID.") from err
    poll = await live_svc.get_poll(db, event.id, pid)
    await live_svc.delete_poll(db, poll)


@router_org.get("/questions")
async def list_questions_organizer(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    questions = await live_svc.list_questions(db, event.id, include_hidden=True)
    return {"success": True, "data": [_question_out(q) for q in questions]}


@router_org.patch("/questions/{question_id}")
async def update_question(
    slug: str,
    event_id: str,
    question_id: str,
    data: QuestionUpdateRequest,
    db: DBSession,
    org_access: LiveEngagementManageAccess,
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    try:
        qid = uuid.UUID(question_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid question ID.") from err
    question = await live_svc.get_question(db, event.id, qid)
    question = await live_svc.update_question(db, question, data)
    return {"success": True, "data": _question_out(question)}


@router_org.delete("/questions/{question_id}", status_code=204)
async def delete_question(
    slug: str,
    event_id: str,
    question_id: str,
    db: DBSession,
    org_access: LiveEngagementManageAccess,
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    try:
        qid = uuid.UUID(question_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid question ID.") from err
    question = await live_svc.get_question(db, event.id, qid)
    await live_svc.delete_question(db, question)


# ── Public API (anonymous — no login required) ───────────────────────────────

router_public = APIRouter(prefix="/api/v1/events/{slug}/live", tags=["live-public"])


async def _get_public_event(db, event_slug: str):
    from sqlalchemy import select

    from app.models.event import Event

    event = await db.scalar(
        select(Event).where(Event.slug == event_slug, Event.deleted_at.is_(None))
    )
    if not event or event.status == "draft":
        raise HTTPException(404, "Event not found.")
    return event


async def _live_snapshot(db, event_id: uuid.UUID) -> dict:
    poll = await live_svc.get_open_poll(db, event_id)
    questions = await live_svc.list_questions(db, event_id)
    return {
        "poll": _poll_out(poll) if poll else None,
        "questions": [_question_out(q) for q in questions],
    }


@router_public.get("/poll")
async def public_open_poll(slug: str, db: DBSession):
    event = await _get_public_event(db, slug)
    poll = await live_svc.get_open_poll(db, event.id)
    return {"success": True, "data": _poll_out(poll) if poll else None}


@router_public.post("/polls/{poll_id}/vote")
async def public_vote_poll(slug: str, poll_id: str, data: PollVoteRequest, db: DBSession):
    event = await _get_public_event(db, slug)
    try:
        pid = uuid.UUID(poll_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid poll ID.") from err
    poll = await live_svc.vote_poll(db, event.id, pid, data.option_id)
    return {"success": True, "data": _poll_out(poll)}


@router_public.get("/questions")
async def public_list_questions(slug: str, db: DBSession):
    event = await _get_public_event(db, slug)
    questions = await live_svc.list_questions(db, event.id)
    return {"success": True, "data": [_question_out(q) for q in questions]}


@router_public.post("/questions", status_code=201)
async def public_submit_question(slug: str, data: QuestionCreateRequest, db: DBSession):
    event = await _get_public_event(db, slug)
    question = await live_svc.create_question(db, event.id, data)
    return {"success": True, "data": _question_out(question)}


@router_public.post("/questions/{question_id}/upvote")
async def public_upvote_question(slug: str, question_id: str, db: DBSession):
    event = await _get_public_event(db, slug)
    try:
        qid = uuid.UUID(question_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid question ID.") from err
    question = await live_svc.upvote_question(db, event.id, qid)
    return {"success": True, "data": _question_out(question)}


@router_public.get("/stream")
async def live_stream(slug: str, db: DBSession):
    """SSE endpoint — pushes the open poll + question list every 3s, same
    pattern as the check-in kiosk's live-pulse stream."""
    event = await _get_public_event(db, slug)

    async def _generate():
        try:
            while True:
                async with AsyncSessionLocal() as session:
                    snapshot = await _live_snapshot(session, event.id)
                yield f"data: {json.dumps(snapshot)}\n\n"
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
