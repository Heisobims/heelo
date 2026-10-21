"""
Public REST API - authenticated via X-API-Key header.
Org context is derived from the API key's org_id.
Base path: /api/public/v1/
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.api import ApiKey
from app.services import api_key_service as ak_svc

logger = structlog.get_logger()

DBSession = Annotated[AsyncSession, Depends(get_db)]


# ── Rate limiting ─────────────────────────────────────────────────────────────
# 60 requests per minute per API key (sliding window via Redis INCR + EXPIRE)

_RATE_LIMIT = 60
_RATE_WINDOW = 60  # seconds


async def _check_rate_limit(x_api_key: str | None = Header(default=None)) -> None:
    if not x_api_key:
        return  # auth dependency will reject this below
    try:
        import redis.asyncio as aioredis

        from app.config import settings

        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        key = f"rl:pub:{x_api_key[:16]}"
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, _RATE_WINDOW)
        await r.aclose()
        if count > _RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Max {_RATE_LIMIT} requests per {_RATE_WINDOW}s.",
                headers={"Retry-After": str(_RATE_WINDOW)},
            )
    except HTTPException:
        raise
    except Exception as err:
        # Redis unavailable - fail open, but make the outage visible.
        logger.warning("public_api.rate_limit_check_failed", error=str(err))


router_public_api = APIRouter(
    prefix="/api/public/v1",
    tags=["public-api"],
    dependencies=[Depends(_check_rate_limit)],
)


# ── API key auth dependency ───────────────────────────────────────────────────


async def _require_api_key(
    x_api_key: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    if not x_api_key:
        raise HTTPException(401, "Missing X-API-Key header.")
    key = await ak_svc.authenticate_api_key(db, x_api_key)
    if not key:
        raise HTTPException(401, "Invalid or revoked API key.")
    return key


AuthKey = Annotated[ApiKey, Depends(_require_api_key)]


# ── Pagination helpers ────────────────────────────────────────────────────────

import math as _math

from fastapi import Request
from fastapi.responses import JSONResponse


def _paginated(
    request: Request,
    data: list,
    total: int,
    page: int,
    per_page: int,
) -> JSONResponse:
    total_pages = _math.ceil(total / per_page) if total else 1
    base = str(request.url).split("?")[0]
    qs = dict(request.query_params)

    def _url(p: int) -> str:
        qs["page"] = str(p)
        qs["per_page"] = str(per_page)
        return base + "?" + "&".join(f"{k}={v}" for k, v in qs.items())

    links = []
    if page > 1:
        links.append(f'<{_url(1)}>; rel="first"')
        links.append(f'<{_url(page - 1)}>; rel="prev"')
    if page < total_pages:
        links.append(f'<{_url(page + 1)}>; rel="next"')
        links.append(f'<{_url(total_pages)}>; rel="last"')

    headers = {
        "X-Total-Count": str(total),
        "X-Total-Pages": str(total_pages),
        "X-Page": str(page),
        "X-Per-Page": str(per_page),
    }
    if links:
        headers["Link"] = ", ".join(links)

    return JSONResponse(
        content={
            "success": True,
            "meta": {
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
            },
            "data": data,
        },
        headers=headers,
    )


# ── Events ────────────────────────────────────────────────────────────────────


@router_public_api.get("/events")
async def list_events(
    request: Request, db: DBSession, auth: AuthKey, page: int = 1, per_page: int = 20
):
    from sqlalchemy import func

    from app.models.event import Event

    per_page = min(per_page, 100)
    offset = (max(page, 1) - 1) * per_page

    total = await db.scalar(
        select(func.count()).where(
            Event.org_id == auth.org_id,
            Event.status.in_(["published", "ended"]),
        )
    )
    rows = await db.scalars(
        select(Event)
        .where(Event.org_id == auth.org_id, Event.status.in_(["published", "ended"]))
        .order_by(Event.start_datetime.desc())
        .offset(offset)
        .limit(per_page)
    )
    events = list(rows.all())

    return _paginated(request, [_event_dict(e) for e in events], total or 0, page, per_page)


@router_public_api.get("/events/{event_id}")
async def get_event(event_id: str, db: DBSession, auth: AuthKey):
    from app.models.event import Event

    event = await db.scalar(
        select(Event).where(
            Event.id == uuid.UUID(event_id),
            Event.org_id == auth.org_id,
        )
    )
    if not event:
        raise HTTPException(404, "Event not found.")
    return {"success": True, "data": _event_dict(event)}


@router_public_api.get("/events/{event_id}/registrations")
async def list_registrations(
    request: Request,
    event_id: str,
    db: DBSession,
    auth: AuthKey,
    page: int = 1,
    per_page: int = 50,
    status: str | None = None,
):
    from sqlalchemy import func

    from app.models.event import Event
    from app.models.ticketing import Registration

    per_page = min(per_page, 100)
    offset = (max(page, 1) - 1) * per_page

    event = await db.scalar(
        select(Event).where(Event.id == uuid.UUID(event_id), Event.org_id == auth.org_id)
    )
    if not event:
        raise HTTPException(404, "Event not found.")

    q = select(Registration).where(Registration.event_id == event.id)
    if status:
        q = q.where(Registration.status == status)

    total = await db.scalar(select(func.count()).select_from(q.subquery()))
    rows = await db.scalars(
        q.order_by(Registration.created_at.desc()).offset(offset).limit(per_page)
    )
    regs = list(rows.all())

    return _paginated(request, [_reg_dict(r) for r in regs], total or 0, page, per_page)


class CheckInRequest(BaseModel):
    qr_token: str | None = None
    registration_id: str | None = None


@router_public_api.post("/events/{event_id}/check-in")
async def check_in(event_id: str, body: CheckInRequest, db: DBSession, auth: AuthKey):
    from app.models.event import Event
    from app.services import checkin_service as ci_svc

    event = await db.scalar(
        select(Event).where(Event.id == uuid.UUID(event_id), Event.org_id == auth.org_id)
    )
    if not event:
        raise HTTPException(404, "Event not found.")

    try:
        if body.qr_token:
            reg = await ci_svc.check_in_by_qr_token(db, body.qr_token, event.id)
        elif body.registration_id:
            reg = await ci_svc.check_in_by_id(db, uuid.UUID(body.registration_id), event.id)
        else:
            raise HTTPException(422, "Provide qr_token or registration_id.")
    except ci_svc.AlreadyCheckedInError as e:
        return {"success": False, "error": {"code": "ALREADY_CHECKED_IN", "message": str(e)}}
    except ci_svc.CheckInError as e:
        raise HTTPException(400, str(e)) from e

    # Fire webhook
    try:
        from app.services import webhook_service as wh_svc

        await wh_svc.fire_event(
            db,
            org_id=auth.org_id,
            event_type="checkin.completed",
            payload={
                "event": "checkin.completed",
                "registration_id": str(reg.id),
                "attendee_email": reg.attendee_email,
                "attendee_name": reg.attendee_name,
                "event_id": str(event.id),
                "checked_in_at": reg.checked_in_at.isoformat() if reg.checked_in_at else None,
            },
        )
    except Exception as err:
        logger.warning(
            "public_api.checkin_webhook_failed", registration_id=str(reg.id), error=str(err)
        )

    return {"success": True, "data": _reg_dict(reg)}


@router_public_api.get("/stats")
async def org_stats(db: DBSession, auth: AuthKey):
    from sqlalchemy import func

    from app.models.event import Event
    from app.models.ticketing import REVENUE_STATUSES, Order, Registration

    event_count = await db.scalar(select(func.count()).where(Event.org_id == auth.org_id))
    reg_count = await db.scalar(
        select(func.count())
        .select_from(Registration)
        .join(Event, Event.id == Registration.event_id)
        .where(Event.org_id == auth.org_id, Registration.status == "confirmed")
    )
    revenue = await db.scalar(
        select(func.coalesce(func.sum(Order.net_amount - Order.refunded_amount), 0))
        .join(Event, Event.id == Order.event_id)
        .where(Event.org_id == auth.org_id, Order.payment_status.in_(REVENUE_STATUSES))
    )

    return {
        "success": True,
        "data": {
            "total_events": event_count or 0,
            "total_confirmed_registrations": reg_count or 0,
            "total_net_revenue": float(revenue or 0),
        },
    }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _event_dict(e) -> dict:
    return {
        "id": str(e.id),
        "title": e.title,
        "slug": e.slug,
        "status": e.status,
        "start_datetime": e.start_datetime.isoformat() if e.start_datetime else None,
        "end_datetime": e.end_datetime.isoformat() if e.end_datetime else None,
        "location": ", ".join(filter(None, [e.venue_name, e.venue_city])) or None,
        "format": e.format,
        "is_virtual": e.format == "virtual",
        "cover_image_url": e.cover_image_url,
    }


def _reg_dict(r) -> dict:
    return {
        "id": str(r.id),
        "attendee_name": r.attendee_name,
        "attendee_email": r.attendee_email,
        "status": r.status,
        "checked_in_at": r.checked_in_at.isoformat() if r.checked_in_at else None,
        "created_at": r.created_at.isoformat(),
    }
