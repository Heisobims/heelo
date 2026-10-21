from __future__ import annotations

import uuid
from io import BytesIO
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from PIL import Image

from app import plans
from app.dependencies import CurrentUser, CurrentUserID, DBSession, OrgAccess
from app.permissions import Permission, require_permission
from app.plans import PlanFeature
from app.schemas.event import (
    EventCreateRequest,
    EventListItem,
    EventOut,
    EventUpdateRequest,
    PublicEventOut,
    RecurrenceGenerateRequest,
)
from app.services import event_service as svc
from app.utils.qr_code import generate_qr_png

router_org = APIRouter(prefix="/api/v1/organizations/{slug}/events", tags=["events"])
router_public = APIRouter(prefix="/api/v1/events", tags=["events-public"])

EventsManageAccess = Annotated[tuple, Depends(require_permission(Permission.EVENTS_MANAGE))]
EventsDeleteAccess = Annotated[tuple, Depends(require_permission(Permission.EVENTS_DELETE))]

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB


def _ok(data) -> dict:
    return {"success": True, "data": data}


# ── Org-scoped event endpoints ────────────────────────────────────────────────


@router_org.post("", status_code=status.HTTP_201_CREATED)
async def create_event(
    body: EventCreateRequest,
    access: EventsManageAccess,
    current_user: CurrentUser,
    db: DBSession,
):
    org, role, _ = access
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
        data.append(
            EventListItem(
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
            )
        )
    return _ok(
        {
            "items": [d.model_dump() for d in data],
            "meta": {"total": total, "page": page, "per_page": per_page},
        }
    )


@router_org.get("/templates")
async def list_templates(access: OrgAccess, db: DBSession):
    """
    Registered before GET /{event_id} - FastAPI matches routes in registration
    order, and "/templates" would otherwise be captured by the {event_id} path
    parameter, fail UUID parsing, and 422.
    """
    org, _, _ = access
    templates = await svc.list_org_templates(db, org.id)
    return _ok(
        [
            {
                "id": str(t.id),
                "title": t.title,
                "format": t.format,
                "venue_city": t.venue_city,
            }
            for t in templates
        ]
    )


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


@router_org.get("/{event_id}/qr.png", include_in_schema=False)
async def event_qr_image(
    event_id: uuid.UUID,
    access: OrgAccess,
    db: DBSession,
    request: Request,
):
    """QR code encoding the event's public page URL - same info already
    shown via the "Copy link" button, so any org member who can view the
    event can also fetch this, no extra permission needed."""
    org, _, _ = access
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")

    url = f"{str(request.base_url).rstrip('/')}/e/{event.slug}"
    qr_bytes = generate_qr_png(url)
    return Response(
        content=qr_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router_org.patch("/{event_id}")
async def update_event(
    event_id: uuid.UUID,
    body: EventUpdateRequest,
    access: EventsManageAccess,
    db: DBSession,
):
    org, role, _ = access
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
                changes.append(
                    {
                        "field": label,
                        "old": str(old_val) if old_val else "-",
                        "new": str(new_val),
                    }
                )

    updated = await svc.update_event(db, event, body)

    if changes and event.status in ("published", "live"):
        from app.tasks.email import send_event_update

        send_event_update.delay(str(event.id), changes)

    return _ok(EventOut.model_validate(updated))


@router_org.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: uuid.UUID,
    access: EventsDeleteAccess,
    db: DBSession,
):
    org, role, is_owner = access
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")
    await svc.soft_delete_event(db, event)


@router_org.post("/{event_id}/publish")
async def publish_event(
    event_id: uuid.UUID,
    access: EventsManageAccess,
    db: DBSession,
):
    org, role, _ = access
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")
    try:
        updated = await svc.publish_event(db, event)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _ok({"status": updated.status, "slug": updated.slug})


@router_org.post("/{event_id}/cancel")
async def cancel_event(
    event_id: uuid.UUID,
    access: EventsManageAccess,
    db: DBSession,
):
    org, role, _ = access
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")
    try:
        updated = await svc.cancel_event(db, event)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    from app.tasks.email import send_event_cancellation

    send_event_cancellation.delay(str(event.id))

    return _ok({"status": updated.status})


@router_org.post("/{event_id}/go-live")
async def go_live(
    event_id: uuid.UUID,
    access: EventsManageAccess,
    db: DBSession,
):
    org, role, _ = access
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")
    try:
        updated = await svc.go_live(db, event)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _ok({"status": updated.status})


@router_org.post("/{event_id}/end")
async def end_event(
    event_id: uuid.UUID,
    access: EventsManageAccess,
    db: DBSession,
):
    org, role, _ = access
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")
    try:
        updated = await svc.end_event(db, event)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _ok({"status": updated.status})


@router_org.post("/{event_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_event(
    event_id: uuid.UUID,
    access: EventsManageAccess,
    current_user: CurrentUser,
    db: DBSession,
):
    org, role, _ = access
    plans.require_feature(org.plan, PlanFeature.RECURRING_EVENTS)
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")
    clone = await svc.duplicate_event(db, event, org, current_user.id)
    return _ok({"id": str(clone.id), "slug": clone.slug})


@router_org.post("/{event_id}/recurrence/generate", status_code=status.HTTP_201_CREATED)
async def generate_recurring_series(
    event_id: uuid.UUID,
    body: RecurrenceGenerateRequest,
    access: EventsManageAccess,
    current_user: CurrentUser,
    db: DBSession,
):
    org, role, _ = access
    plans.require_feature(org.plan, PlanFeature.RECURRING_EVENTS)
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")
    try:
        children = await svc.generate_recurring_series(
            db, event, org, current_user.id, rule=body.rule, end_date=body.end_date
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _ok(
        {
            "count": len(children),
            "events": [
                {"id": str(c.id), "slug": c.slug, "start_datetime": c.start_datetime}
                for c in children
            ],
        }
    )


@router_org.get("/{event_id}/recurrence/children")
async def list_recurring_children(event_id: uuid.UUID, access: OrgAccess, db: DBSession):
    org, _, _ = access
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")
    children = await svc.list_recurring_children(db, event.id)
    return _ok(
        [
            {
                "id": str(c.id),
                "slug": c.slug,
                "status": c.status,
                "start_datetime": c.start_datetime,
            }
            for c in children
        ]
    )


@router_org.post("/{event_id}/cover")
async def upload_cover(
    event_id: uuid.UUID,
    access: EventsManageAccess,
    db: DBSession,
    cover: UploadFile = File(...),
):
    org, role, _ = access
    event = await svc.get_event_by_id(db, event_id)
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")

    if cover.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, "Unsupported image type. Accepted: JPEG, PNG, WebP.")

    image_bytes = await cover.read()
    if len(image_bytes) > _MAX_UPLOAD_SIZE:
        raise HTTPException(413, "Image must be under 10 MB.")

    # Validate it's actually an image
    try:
        Image.open(BytesIO(image_bytes)).verify()
    except Exception as err:
        raise HTTPException(400, "File does not appear to be a valid image.") from err

    updated = await svc.update_cover_image(db, event, image_bytes)
    return _ok({"cover_image_url": updated.cover_image_url})


@router_org.post("/{event_id}/gallery/{slot}")
async def upload_gallery_image(
    event_id: uuid.UUID,
    slot: int,
    access: EventsManageAccess,
    db: DBSession,
    image: UploadFile = File(...),
):
    if slot not in (1, 2):
        raise HTTPException(400, "Slot must be 1 or 2.")
    org, role, _ = access
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
    except Exception as err:
        raise HTTPException(400, "File does not appear to be a valid image.") from err

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
    return _ok(
        {
            "items": [PublicEventOut.model_validate(e).model_dump() for e in events],
            "meta": {"total": total, "page": page, "per_page": per_page},
        }
    )


# ── Save-and-remind ("interested") ─────────────────────────────────────────────


async def _get_public_event_or_404(db: DBSession, slug: str):
    event = await svc.get_event_by_slug(db, slug)
    if not event or event.status not in ("published", "live"):
        raise HTTPException(404, "Event not found.")
    return event


@router_public.post("/{slug}/interested", status_code=status.HTTP_204_NO_CONTENT)
async def mark_interested(slug: str, db: DBSession, current_user_id: CurrentUserID):
    from app.services import interest_service as int_svc

    event = await _get_public_event_or_404(db, slug)
    await int_svc.mark_interested(db, uuid.UUID(current_user_id), event.id)


@router_public.delete("/{slug}/interested", status_code=status.HTTP_204_NO_CONTENT)
async def unmark_interested(slug: str, db: DBSession, current_user_id: CurrentUserID):
    from app.services import interest_service as int_svc

    event = await _get_public_event_or_404(db, slug)
    await int_svc.unmark_interested(db, uuid.UUID(current_user_id), event.id)


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
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=3600",
        },
    )


@router_public.get("/{event_slug}")
async def get_public_event(event_slug: str, db: DBSession):
    event = await svc.get_event_by_slug(db, event_slug)
    if not event or event.deleted_at is not None:
        raise HTTPException(404, "Event not found.")
    if event.status == "draft":
        raise HTTPException(404, "Event not found.")  # draft = not publicly visible
    return _ok(PublicEventOut.model_validate(event))
