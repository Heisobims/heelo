from __future__ import annotations

import uuid
from io import BytesIO

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from PIL import Image

from app.dependencies import CurrentUser, DBSession, OrgAccess
from app.schemas.event import (
    EventCreateRequest,
    EventListItem,
    EventOut,
    EventSearchQuery,
    EventUpdateRequest,
    PublicEventOut,
)
from app.services import event_service as svc

router_org = APIRouter(prefix="/api/v1/organizations/{slug}/events", tags=["events"])
router_public = APIRouter(prefix="/api/v1/events", tags=["events-public"])

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB


def _ok(data) -> dict:
    return {"success": True, "data": data}


# ── Org-scoped event endpoints ────────────────────────────────────────────────

@router_org.post("", status_code=status.HTTP_201_CREATED)
async def create_event(
    body: EventCreateRequest,
    access: OrgAccess,
    current_user: CurrentUser,
    db: DBSession,
):
    org, role, _ = access
    if role not in ("admin", "organizer"):
        raise HTTPException(403, "Only admins and organizers can create events.")
    event = await svc.create_event(db, org, current_user.id, body)
    return _ok(EventOut.model_validate(event))


@router_org.get("")
async def list_events(
    access: OrgAccess,
    db: DBSession,
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    org, _, _ = access
    items, total = await svc.list_org_events(
        db, org.id, status=status_filter, page=page, per_page=per_page
    )
    data = []
    for entry in items:
        ev = entry["event"]
        data.append(EventListItem(
            id=ev.id,
            title=ev.title,
            slug=ev.slug,
            cover_image_url=ev.cover_image_url,
            status=ev.status,
            format=ev.format,
            start_datetime=ev.start_datetime,
            end_datetime=ev.end_datetime,
            venue_city=ev.venue_city,
            max_capacity=ev.max_capacity,
            is_private=ev.is_private,
            created_at=ev.created_at,
            registration_count=entry["registration_count"],
            total_revenue=entry["total_revenue"],
        ))
    return _ok({
        "items": [d.model_dump() for d in data],
        "meta": {"total": total, "page": page, "per_page": per_page},
    })


@router_org.get("/{event_id}")
async def get_event(
    event_id: uuid.UUID,
    access: OrgAccess,
    db: DBSession,
):
    org, _, _ = access
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")
    stats = await svc.get_event_stats(db, event.id)
    out = EventOut.model_validate(event).model_dump()
    out["stats"] = stats
    return _ok(out)


@router_org.patch("/{event_id}")
async def update_event(
    event_id: uuid.UUID,
    body: EventUpdateRequest,
    access: OrgAccess,
    db: DBSession,
):
    org, role, _ = access
    if role not in ("admin", "organizer"):
        raise HTTPException(403, "Insufficient permissions.")
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")
    if event.status == "cancelled":
        raise HTTPException(400, "Cannot edit a cancelled event.")

    # Detect key changes that warrant notifying attendees
    _NOTIFY_FIELDS = {
        "start_datetime": "Date/Time",
        "end_datetime": "End Time",
        "venue_name": "Venue",
        "venue_address": "Address",
        "venue_city": "City",
    }
    changes = []
    for attr, label in _NOTIFY_FIELDS.items():
        new_val = getattr(body, attr, None)
        if new_val is not None:
            old_val = getattr(event, attr, None)
            if str(old_val or "") != str(new_val):
                changes.append({
                    "field": label,
                    "old": str(old_val) if old_val else "—",
                    "new": str(new_val),
                })

    updated = await svc.update_event(db, event, body)

    if changes and event.status in ("published", "live"):
        from app.tasks.email import send_event_update
        send_event_update.delay(str(event.id), changes)

    return _ok(EventOut.model_validate(updated))


@router_org.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: uuid.UUID,
    access: OrgAccess,
    db: DBSession,
):
    org, role, is_owner = access
    if role not in ("admin",) and not is_owner:
        raise HTTPException(403, "Only admins can delete events.")
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")
    await svc.soft_delete_event(db, event)


@router_org.post("/{event_id}/publish")
async def publish_event(
    event_id: uuid.UUID,
    access: OrgAccess,
    db: DBSession,
):
    org, role, _ = access
    if role not in ("admin", "organizer"):
        raise HTTPException(403, "Insufficient permissions.")
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")
    try:
        updated = await svc.publish_event(db, event)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _ok({"status": updated.status, "slug": updated.slug})


@router_org.post("/{event_id}/cancel")
async def cancel_event(
    event_id: uuid.UUID,
    access: OrgAccess,
    db: DBSession,
):
    org, role, _ = access
    if role not in ("admin", "organizer"):
        raise HTTPException(403, "Insufficient permissions.")
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")
    try:
        updated = await svc.cancel_event(db, event)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    from app.tasks.email import send_event_cancellation
    send_event_cancellation.delay(str(event.id))

    return _ok({"status": updated.status})


@router_org.post("/{event_id}/go-live")
async def go_live(
    event_id: uuid.UUID,
    access: OrgAccess,
    db: DBSession,
):
    org, role, _ = access
    if role not in ("admin", "organizer"):
        raise HTTPException(403, "Insufficient permissions.")
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")
    try:
        updated = await svc.go_live(db, event)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _ok({"status": updated.status})


@router_org.post("/{event_id}/end")
async def end_event(
    event_id: uuid.UUID,
    access: OrgAccess,
    db: DBSession,
):
    org, role, _ = access
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")
    try:
        updated = await svc.end_event(db, event)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _ok({"status": updated.status})


@router_org.post("/{event_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_event(
    event_id: uuid.UUID,
    access: OrgAccess,
    current_user: CurrentUser,
    db: DBSession,
):
    org, role, _ = access
    if role not in ("admin", "organizer"):
        raise HTTPException(403, "Insufficient permissions.")
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")
    clone = await svc.duplicate_event(db, event, org, current_user.id)
    return _ok({"id": str(clone.id), "slug": clone.slug})


@router_org.post("/{event_id}/cover")
async def upload_cover(
    event_id: uuid.UUID,
    access: OrgAccess,
    db: DBSession,
    cover: UploadFile = File(...),
):
    org, role, _ = access
    if role not in ("admin", "organizer"):
        raise HTTPException(403, "Insufficient permissions.")
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")

    if cover.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, f"Unsupported image type. Accepted: JPEG, PNG, WebP.")

    image_bytes = await cover.read()
    if len(image_bytes) > _MAX_UPLOAD_SIZE:
        raise HTTPException(413, "Image must be under 10 MB.")

    # Validate it's actually an image
    try:
        Image.open(BytesIO(image_bytes)).verify()
    except Exception:
        raise HTTPException(400, "File does not appear to be a valid image.")

    updated = await svc.update_cover_image(db, event, image_bytes)
    return _ok({"cover_image_url": updated.cover_image_url})


@router_org.post("/{event_id}/gallery/{slot}")
async def upload_gallery_image(
    event_id: uuid.UUID,
    slot: int,
    access: OrgAccess,
    db: DBSession,
    image: UploadFile = File(...),
):
    if slot not in (1, 2):
        raise HTTPException(400, "Slot must be 1 or 2.")
    org, role, _ = access
    if role not in ("admin", "organizer"):
        raise HTTPException(403, "Insufficient permissions.")
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")

    if image.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, "Unsupported image type. Accepted: JPEG, PNG, WebP.")

    image_bytes = await image.read()
    if len(image_bytes) > _MAX_UPLOAD_SIZE:
        raise HTTPException(413, "Image must be under 10 MB.")

    try:
        Image.open(BytesIO(image_bytes)).verify()
    except Exception:
        raise HTTPException(400, "File does not appear to be a valid image.")

    updated = await svc.update_gallery_image(db, event, image_bytes, slot)
    field = "gallery_1_url" if slot == 1 else "gallery_2_url"
    return _ok({field: getattr(updated, field)})


# ── Public event endpoints ────────────────────────────────────────────────────

@router_public.get("")
async def search_events(
    db: DBSession,
    q: str | None = Query(None),
    format: str | None = Query(None),
    city: str | None = Query(None),
    country: str | None = Query(None),
    category: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
):
    from datetime import UTC, datetime
    events, total = await svc.search_public_events(
        db,
        q=q,
        format=format,
        city=city,
        country=country,
        category_slug=category,
        page=page,
        per_page=per_page,
    )
    return _ok({
        "items": [PublicEventOut.model_validate(e).model_dump() for e in events],
        "meta": {"total": total, "page": page, "per_page": per_page},
    })


@router_public.get("/{event_slug}/og.png", include_in_schema=False)
async def event_og_image(event_slug: str, db: DBSession):
    """Serve the OG image for an event (generated on first request)."""
    from app.utils.og_image import generate_event_og_image

    event = await svc.get_event_by_slug(db, event_slug)
    if not event or event.status not in ("published", "live", "ended"):
        raise HTTPException(404)

    date_str = event.start_datetime.strftime("%a %d %b %Y") if event.start_datetime else None
    location_str = event.venue_city or ("Online" if event.format == "virtual" else None)

    png_bytes = generate_event_og_image(
        title=event.title,
        date_str=date_str,
        location_str=location_str,
        format_label=event.format,
    )
    return Response(content=png_bytes, media_type="image/png", headers={
        "Cache-Control": "public, max-age=3600",
    })


@router_public.get("/{event_slug}")
async def get_public_event(event_slug: str, db: DBSession):
    event = await svc.get_event_by_slug(db, event_slug)
    if not event or event.deleted_at is not None:
        raise HTTPException(404, "Event not found.")
    if event.status == "draft":
        raise HTTPException(404, "Event not found.")  # draft = not publicly visible
    return _ok(PublicEventOut.model_validate(event))
