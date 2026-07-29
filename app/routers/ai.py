from __future__ import annotations

import json
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.dependencies import DBSession, OrgAccess
from app.services import ai_service as ai_svc

router_ai = APIRouter(
    prefix="/api/v1/organizations/{slug}",
    tags=["ai"],
)


# ── Request bodies ────────────────────────────────────────────────────────────

class EventDescriptionRequest(BaseModel):
    title: str = Field(..., min_length=1)
    format: str = "in_person"
    location: str = ""
    tags: list[str] = []
    existing: str = ""


class CampaignCopyRequest(BaseModel):
    channel: Literal["email", "whatsapp", "sms"]
    event_title: str = ""
    event_date: str = ""
    event_description: str = ""
    goal: str = "reminder"
    org_name: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sse_stream(gen):
    """Wrap an async generator of text chunks into an SSE StreamingResponse."""
    async def _emit():
        try:
            async for chunk in gen:
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception:
            yield f"data: {json.dumps({'error': 'AI generation failed'})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _emit(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _require_editor(role: str) -> None:
    if role not in ("admin", "organizer"):
        raise HTTPException(403, "Insufficient permissions.")


# ── Event description generator ───────────────────────────────────────────────

@router_ai.post("/ai/generate-event-description")
async def generate_event_description(
    slug: str,
    body: EventDescriptionRequest,
    db: DBSession,
    org_access: OrgAccess,
):
    org, role, _ = org_access
    _require_editor(role)

    gen = ai_svc.stream_event_description(
        title=body.title,
        format=body.format,
        location=body.location,
        tags=body.tags,
        existing=body.existing,
    )
    return _sse_stream(gen)


# ── Campaign copy generator ───────────────────────────────────────────────────

@router_ai.post("/ai/generate-campaign-copy")
async def generate_campaign_copy(
    slug: str,
    body: CampaignCopyRequest,
    db: DBSession,
    org_access: OrgAccess,
):
    org, role, _ = org_access
    _require_editor(role)

    gen = ai_svc.stream_campaign_copy(
        channel=body.channel,
        event_title=body.event_title,
        event_date=body.event_date,
        event_description=body.event_description,
        goal=body.goal,
        org_name=body.org_name or org.name,
    )
    return _sse_stream(gen)


# ── Analytics insights ────────────────────────────────────────────────────────

@router_ai.post("/events/{event_id}/ai/insights")
async def analytics_insights(
    slug: str,
    event_id: str,
    db: DBSession,
    org_access: OrgAccess,
):
    org, role, _ = org_access
    _require_editor(role)

    try:
        eid = uuid.UUID(event_id)
    except ValueError:
        raise HTTPException(422, "Invalid event ID.")

    from app.models.event import Event
    from sqlalchemy import select

    event = await db.scalar(select(Event).where(Event.id == eid, Event.org_id == org.id))
    if not event:
        raise HTTPException(404, "Event not found.")

    from app.services import analytics_service as an_svc
    summary = await an_svc.get_event_summary(db, eid)
    ticket_breakdown = await an_svc.get_ticket_breakdown(db, eid)

    insights = await ai_svc.generate_analytics_insights(summary, ticket_breakdown)
    return {"success": True, "data": {"insights": insights}}
