from __future__ import annotations

import asyncio
import json
import uuid

import csv
import io as _io

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.database import AsyncSessionLocal
from app.dependencies import DBSession, OrgAccess
from app.services import analytics_service as an_svc

router_analytics = APIRouter(
    prefix="/api/v1/organizations/{slug}/events/{event_id}",
    tags=["analytics"],
)


async def _get_event(db, event_id_str: str, org_id: uuid.UUID):
    from app.models.event import Event
    from sqlalchemy import select

    try:
        eid = uuid.UUID(event_id_str)
    except ValueError:
        raise HTTPException(422, "Invalid event ID.")
    event = await db.scalar(
        select(Event).where(Event.id == eid, Event.org_id == org_id)
    )
    if not event:
        raise HTTPException(404, "Event not found.")
    return event


@router_analytics.get("/analytics/summary")
async def analytics_summary(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    event = await _get_event(db, event_id, org.id)
    data = await an_svc.get_event_summary(db, event.id)
    return {"success": True, "data": data}


@router_analytics.get("/analytics/ticket-breakdown")
async def analytics_ticket_breakdown(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    event = await _get_event(db, event_id, org.id)
    data = await an_svc.get_ticket_breakdown(db, event.id)
    return {"success": True, "data": data}


@router_analytics.get("/analytics/sales-chart")
async def analytics_sales_chart(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    event = await _get_event(db, event_id, org.id)
    sales = await an_svc.get_sales_over_time(db, event.id)
    registrations = await an_svc.get_registration_over_time(db, event.id)
    return {"success": True, "data": {"sales": sales, "registrations": registrations}}


@router_analytics.get("/analytics/utm-breakdown")
async def analytics_utm_breakdown(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    event = await _get_event(db, event_id, org.id)
    data = await an_svc.get_utm_breakdown(db, event.id)
    return {"success": True, "data": data}


@router_analytics.get("/analytics/promos")
async def analytics_promos(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    event = await _get_event(db, event_id, org.id)
    data = await an_svc.get_promo_breakdown(db, event.id)
    return {"success": True, "data": data}


@router_analytics.get("/analytics/stream")
async def analytics_stream(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    """SSE endpoint — pushes live stats every 10 s. Nginx must have proxy_buffering off."""
    org, role, is_owner = org_access
    event = await _get_event(db, event_id, org.id)
    eid = event.id

    async def _generate():
        try:
            while True:
                async with AsyncSessionLocal() as session:
                    stats = await an_svc.get_live_stats(session, eid)
                yield f"data: {json.dumps(stats)}\n\n"
                await asyncio.sleep(10)
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


@router_analytics.get("/analytics/export.csv")
async def analytics_export_csv(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    """Download all registrations for this event as a CSV file."""
    from app.models.ticketing import Registration, TicketType
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    org, role, is_owner = org_access
    event = await _get_event(db, event_id, org.id)

    rows = await db.scalars(
        select(Registration)
        .where(Registration.event_id == event.id)
        .options(selectinload(Registration.ticket_type))
        .order_by(Registration.created_at.asc())
    )
    regs = list(rows.all())

    buf = _io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "registration_id", "status", "attendee_name", "attendee_email",
        "attendee_phone", "ticket_type", "ticket_price", "currency",
        "checked_in_at", "created_at", "utm_source", "utm_medium", "utm_campaign",
    ])
    for r in regs:
        writer.writerow([
            str(r.id),
            r.status,
            r.attendee_name,
            r.attendee_email,
            r.attendee_phone or "",
            r.ticket_type.name if r.ticket_type else "",
            r.ticket_type.price if r.ticket_type else "",
            r.ticket_type.currency if r.ticket_type else "",
            r.checked_in_at.isoformat() if r.checked_in_at else "",
            r.created_at.isoformat() if r.created_at else "",
            getattr(r, "utm_source", "") or "",
            getattr(r, "utm_medium", "") or "",
            getattr(r, "utm_campaign", "") or "",
        ])

    fname = f"{event.slug}-registrations.csv"
    return StreamingResponse(
        _io.BytesIO(buf.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
