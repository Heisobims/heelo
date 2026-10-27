from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, status
from jose import jwt
from sqlalchemy import select

from app.config import settings
from app.dependencies import DBSession, OrgAccess
from app.models.event import Event
from app.permissions import Permission, require_permission
from app.schemas.open_call import (
    OpenCallCreateRequest,
    OpenCallOut,
    OpenCallPublicOut,
    OpenCallSubmissionCreateRequest,
    OpenCallSubmissionOut,
    OpenCallSubmissionPromoteRequest,
    OpenCallSubmissionPublicOut,
    OpenCallSubmissionReviewRequest,
    OpenCallUpdateRequest,
)
from app.services import open_call_service as call_svc

OpenCallsManageAccess = Annotated[tuple, Depends(require_permission(Permission.OPEN_CALLS_MANAGE))]

router_org = APIRouter(
    prefix="/api/v1/organizations/{slug}/events/{event_id}/calls",
    tags=["open_calls"],
)

router_public = APIRouter(
    prefix="/api/v1/events/{event_id_or_slug}/calls",
    tags=["open_calls"],
)

router_applicant = APIRouter(
    prefix="/api/v1/open-calls",
    tags=["open_calls"],
)


async def _resolve_optional_user_id(
    authorization: str | None = Header(default=None),
    tixdoo_access: str | None = Cookie(default=None),
) -> uuid.UUID | None:
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    elif tixdoo_access:
        token = tixdoo_access
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        uid = payload.get("sub")
        return uuid.UUID(uid) if uid else None
    except Exception:
        return None


async def _get_event_by_id_or_slug(db: DBSession, event_id_or_slug: str) -> Event:
    try:
        eid = uuid.UUID(event_id_or_slug)
        event = await db.scalar(select(Event).where(Event.id == eid))
    except ValueError:
        event = await db.scalar(select(Event).where(Event.slug == event_id_or_slug))

    if not event:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found.")
    return event


# ── Organizer Endpoints ───────────────────────────────────────────────────────


@router_org.get("", response_model=dict)
async def list_event_calls(
    slug: str,
    event_id: str,
    db: DBSession,
    org_access: OrgAccess,
):
    org, _, _ = org_access
    try:
        eid = uuid.UUID(event_id)
    except ValueError as err:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid event ID.") from err

    calls = await call_svc.list_open_calls_for_event(db, eid, org_id=org.id)
    return {
        "success": True,
        "data": [OpenCallOut.model_validate(c).model_dump(mode="json") for c in calls],
    }


@router_org.post("", status_code=status.HTTP_201_CREATED, response_model=dict)
async def create_event_call(
    slug: str,
    event_id: str,
    data: OpenCallCreateRequest,
    db: DBSession,
    org_access: OpenCallsManageAccess,
    user_id: uuid.UUID | None = Depends(_resolve_optional_user_id),
):
    org, _, _ = org_access
    try:
        eid = uuid.UUID(event_id)
    except ValueError as err:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid event ID.") from err

    call = await call_svc.create_open_call(db, org.id, eid, data, user_id=user_id)
    return {
        "success": True,
        "data": OpenCallOut.model_validate(call).model_dump(mode="json"),
    }


@router_org.get("/{call_id}", response_model=dict)
async def get_event_call(
    slug: str,
    event_id: str,
    call_id: uuid.UUID,
    db: DBSession,
    org_access: OrgAccess,
):
    org, _, _ = org_access
    call = await call_svc.get_open_call(db, call_id, org_id=org.id)
    return {
        "success": True,
        "data": OpenCallOut.model_validate(call).model_dump(mode="json"),
    }


@router_org.patch("/{call_id}", response_model=dict)
async def update_event_call(
    slug: str,
    event_id: str,
    call_id: uuid.UUID,
    data: OpenCallUpdateRequest,
    db: DBSession,
    org_access: OpenCallsManageAccess,
):
    org, _, _ = org_access
    call = await call_svc.update_open_call(db, call_id, org.id, data)
    return {
        "success": True,
        "data": OpenCallOut.model_validate(call).model_dump(mode="json"),
    }


@router_org.delete("/{call_id}")
async def delete_event_call(
    slug: str,
    event_id: str,
    call_id: uuid.UUID,
    db: DBSession,
    org_access: OpenCallsManageAccess,
):
    org, _, _ = org_access
    await call_svc.delete_open_call(db, call_id, org.id)
    return {"success": True, "message": "Open call deleted successfully."}


@router_org.get("/{call_id}/submissions", response_model=dict)
async def list_call_submissions(
    slug: str,
    event_id: str,
    call_id: uuid.UUID,
    db: DBSession,
    org_access: OrgAccess,
    status_filter: str | None = Query(default=None, alias="status"),
    track: str | None = Query(default=None),
    q: str | None = Query(default=None),
):
    org, _, _ = org_access
    submissions = await call_svc.list_submissions_for_call(
        db,
        call_id,
        org.id,
        status=status_filter,
        track=track,
        search=q,
    )
    return {
        "success": True,
        "data": [
            OpenCallSubmissionOut.model_validate(s).model_dump(mode="json") for s in submissions
        ],
    }


@router_org.get("/{call_id}/submissions/{submission_id}", response_model=dict)
async def get_call_submission(
    slug: str,
    event_id: str,
    call_id: uuid.UUID,
    submission_id: uuid.UUID,
    db: DBSession,
    org_access: OrgAccess,
):
    org, _, _ = org_access
    sub = await call_svc.get_submission(db, submission_id, org_id=org.id)
    return {
        "success": True,
        "data": OpenCallSubmissionOut.model_validate(sub).model_dump(mode="json"),
    }


@router_org.patch("/{call_id}/submissions/{submission_id}/review", response_model=dict)
async def review_call_submission(
    slug: str,
    event_id: str,
    call_id: uuid.UUID,
    submission_id: uuid.UUID,
    data: OpenCallSubmissionReviewRequest,
    db: DBSession,
    org_access: OpenCallsManageAccess,
    user_id: uuid.UUID | None = Depends(_resolve_optional_user_id),
):
    org, _, _ = org_access
    reviewer = user_id or org.owner_id
    sub = await call_svc.review_submission(db, submission_id, org.id, reviewer, data)
    return {
        "success": True,
        "data": OpenCallSubmissionOut.model_validate(sub).model_dump(mode="json"),
    }


@router_org.post("/{call_id}/submissions/{submission_id}/promote", response_model=dict)
async def promote_call_submission(
    slug: str,
    event_id: str,
    call_id: uuid.UUID,
    submission_id: uuid.UUID,
    data: OpenCallSubmissionPromoteRequest,
    db: DBSession,
    org_access: OpenCallsManageAccess,
    user_id: uuid.UUID | None = Depends(_resolve_optional_user_id),
):
    org, _, _ = org_access
    reviewer = user_id or org.owner_id
    sub, entity = await call_svc.promote_submission(db, submission_id, org.id, reviewer, data)
    msg = f"Submission successfully accepted and promoted to event {sub.open_call.call_type}."
    return {
        "success": True,
        "message": msg,
        "data": OpenCallSubmissionOut.model_validate(sub).model_dump(mode="json"),
    }


# ── Public Endpoints ──────────────────────────────────────────────────────────


@router_public.get("", response_model=dict)
async def list_public_calls(
    event_id_or_slug: str,
    db: DBSession,
):
    event = await _get_event_by_id_or_slug(db, event_id_or_slug)
    calls = await call_svc.list_open_calls_for_event(db, event.id, public_only=True)
    return {
        "success": True,
        "data": [OpenCallPublicOut.model_validate(c).model_dump(mode="json") for c in calls],
    }


@router_public.get("/{call_id_or_slug}", response_model=dict)
async def get_public_call(
    event_id_or_slug: str,
    call_id_or_slug: str,
    db: DBSession,
):
    event = await _get_event_by_id_or_slug(db, event_id_or_slug)
    call = await call_svc.get_open_call_by_slug(db, event.id, call_id_or_slug)
    if call.status != "open":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This call is not currently open.")

    return {
        "success": True,
        "data": OpenCallPublicOut.model_validate(call).model_dump(mode="json"),
    }


@router_public.post(
    "/{call_id_or_slug}/apply", status_code=status.HTTP_201_CREATED, response_model=dict
)
async def apply_to_open_call(
    event_id_or_slug: str,
    call_id_or_slug: str,
    data: OpenCallSubmissionCreateRequest,
    db: DBSession,
    user_id: uuid.UUID | None = Depends(_resolve_optional_user_id),
):
    event = await _get_event_by_id_or_slug(db, event_id_or_slug)
    call = await call_svc.get_open_call_by_slug(db, event.id, call_id_or_slug)

    submission = await call_svc.submit_application(db, call.id, data, user_id=user_id)
    return {
        "success": True,
        "message": call.auto_response_message
        or "Thank you! Your proposal has been submitted successfully.",
        "data": OpenCallSubmissionPublicOut.model_validate(submission).model_dump(mode="json"),
    }


# ── Applicant Status Check ────────────────────────────────────────────────────


@router_applicant.get("/submissions/{submission_id}/status", response_model=dict)
async def check_submission_status(
    submission_id: uuid.UUID,
    db: DBSession,
):
    sub = await call_svc.get_submission(db, submission_id)
    return {
        "success": True,
        "data": OpenCallSubmissionPublicOut.model_validate(sub).model_dump(mode="json"),
    }
