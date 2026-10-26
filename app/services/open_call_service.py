from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from slugify import slugify
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.event import Event
from app.models.open_call import OpenCall, OpenCallSubmission
from app.models.speaker import EventSpeaker, Speaker, Sponsor
from app.schemas.open_call import (
    OpenCallCreateRequest,
    OpenCallSubmissionCreateRequest,
    OpenCallSubmissionPromoteRequest,
    OpenCallSubmissionReviewRequest,
    OpenCallUpdateRequest,
)


def _slugify_unique(title: str, existing_slugs: set[str]) -> str:
    base = slugify(title, max_length=200) or "call"
    slug = base
    counter = 1
    while slug in existing_slugs:
        slug = f"{base}-{counter}"
        counter += 1
    return slug


async def list_open_calls_for_event(
    db: AsyncSession,
    event_id: uuid.UUID,
    *,
    org_id: uuid.UUID | None = None,
    public_only: bool = False,
) -> list[OpenCall]:
    query = select(OpenCall).where(OpenCall.event_id == event_id)
    if org_id:
        query = query.where(OpenCall.org_id == org_id)
    if public_only:
        query = query.where(OpenCall.status == "open")

    query = query.order_by(desc(OpenCall.created_at))
    result = await db.scalars(query)
    return list(result.all())


async def get_open_call(
    db: AsyncSession,
    call_id: uuid.UUID,
    *,
    org_id: uuid.UUID | None = None,
) -> OpenCall:
    query = select(OpenCall).where(OpenCall.id == call_id)
    if org_id:
        query = query.where(OpenCall.org_id == org_id)

    call = await db.scalar(query)
    if not call:
        raise HTTPException(404, "Open call not found.")
    return call


async def get_open_call_by_slug(
    db: AsyncSession,
    event_id: uuid.UUID,
    call_identifier: str,
) -> OpenCall:
    # Try by UUID first
    try:
        call_uuid = uuid.UUID(call_identifier)
        query = select(OpenCall).where(OpenCall.event_id == event_id, OpenCall.id == call_uuid)
    except ValueError:
        query = select(OpenCall).where(
            OpenCall.event_id == event_id, OpenCall.slug == call_identifier
        )

    call = await db.scalar(query)
    if not call:
        raise HTTPException(404, "Open call not found.")
    return call


async def create_open_call(
    db: AsyncSession,
    org_id: uuid.UUID,
    event_id: uuid.UUID,
    data: OpenCallCreateRequest,
    *,
    user_id: uuid.UUID | None = None,
) -> OpenCall:
    # Verify event belongs to org
    event = await db.scalar(select(Event).where(Event.id == event_id, Event.org_id == org_id))
    if not event:
        raise HTTPException(404, "Event not found for this organization.")

    # Determine unique slug within event
    existing_slugs = set(
        await db.scalars(select(OpenCall.slug).where(OpenCall.event_id == event_id))
    )
    slug = _slugify_unique(data.slug or data.title, existing_slugs)

    open_call = OpenCall(
        org_id=org_id,
        event_id=event_id,
        created_by=user_id,
        title=data.title.strip(),
        slug=slug,
        call_type=data.call_type,
        description=data.description,
        guidelines=data.guidelines,
        perks=data.perks,
        status=data.status,
        start_date=data.start_date,
        end_date=data.end_date,
        custom_fields=data.custom_fields,
        auto_response_message=data.auto_response_message,
        max_submissions=data.max_submissions,
        allow_anonymous=data.allow_anonymous,
        submission_count=0,
    )
    db.add(open_call)
    await db.commit()
    await db.refresh(open_call)
    return open_call


async def update_open_call(
    db: AsyncSession,
    call_id: uuid.UUID,
    org_id: uuid.UUID,
    data: OpenCallUpdateRequest,
) -> OpenCall:
    call = await get_open_call(db, call_id, org_id=org_id)

    payload = data.model_dump(exclude_unset=True)
    if "title" in payload and payload["title"]:
        call.title = payload["title"].strip()
    if "slug" in payload and payload["slug"]:
        # verify uniqueness
        existing = await db.scalar(
            select(OpenCall.id).where(
                OpenCall.event_id == call.event_id,
                OpenCall.slug == payload["slug"],
                OpenCall.id != call.id,
            )
        )
        if existing:
            raise HTTPException(400, f"Slug '{payload['slug']}' is already in use for this event.")
        call.slug = payload["slug"]

    for field in (
        "call_type",
        "description",
        "guidelines",
        "perks",
        "status",
        "start_date",
        "end_date",
        "custom_fields",
        "auto_response_message",
        "max_submissions",
        "allow_anonymous",
    ):
        if field in payload:
            setattr(call, field, payload[field])

    await db.commit()
    await db.refresh(call)
    return call


async def delete_open_call(
    db: AsyncSession,
    call_id: uuid.UUID,
    org_id: uuid.UUID,
) -> None:
    call = await get_open_call(db, call_id, org_id=org_id)
    await db.delete(call)
    await db.commit()


async def submit_application(
    db: AsyncSession,
    call_id: uuid.UUID,
    data: OpenCallSubmissionCreateRequest,
    *,
    user_id: uuid.UUID | None = None,
) -> OpenCallSubmission:
    call = await get_open_call(db, call_id)

    # Validate call is open
    if call.status != "open":
        raise HTTPException(400, "This open call is currently closed to new submissions.")

    now = datetime.now(UTC)
    if call.start_date and now < call.start_date:
        raise HTTPException(400, "Submissions for this open call have not opened yet.")
    if call.end_date and now > call.end_date:
        raise HTTPException(400, "The deadline for this open call has passed.")

    if call.max_submissions and call.submission_count >= call.max_submissions:
        raise HTTPException(
            400, "The maximum number of submissions for this call has been reached."
        )

    # Validate required custom fields if any
    for field_spec in call.custom_fields:
        fid = field_spec.get("id") or field_spec.get("label")
        if field_spec.get("required") and not data.custom_answers.get(fid):
            raise HTTPException(422, f"Missing required response for: {field_spec.get('label')}")

    submission = OpenCallSubmission(
        call_id=call.id,
        event_id=call.event_id,
        org_id=call.org_id,
        user_id=user_id,
        name=data.name.strip(),
        email=data.email.strip().lower(),
        phone=data.phone.strip() if data.phone else None,
        organization_name=data.organization_name.strip() if data.organization_name else None,
        job_title=data.job_title.strip() if data.job_title else None,
        bio=data.bio.strip() if data.bio else None,
        photo_url=data.photo_url.strip() if data.photo_url else None,
        social_links=data.social_links or {},
        title=data.title.strip(),
        proposal_summary=data.proposal_summary.strip(),
        details=data.details.strip() if data.details else None,
        category_or_track=data.category_or_track.strip() if data.category_or_track else None,
        attachment_url=data.attachment_url.strip() if data.attachment_url else None,
        custom_answers=data.custom_answers or {},
        status="submitted",
    )
    db.add(submission)
    call.submission_count += 1
    await db.commit()
    await db.refresh(submission)
    return submission


async def get_submission(
    db: AsyncSession,
    submission_id: uuid.UUID,
    *,
    org_id: uuid.UUID | None = None,
) -> OpenCallSubmission:
    query = (
        select(OpenCallSubmission)
        .where(OpenCallSubmission.id == submission_id)
        .options(
            selectinload(OpenCallSubmission.open_call),
            selectinload(OpenCallSubmission.promoted_speaker),
            selectinload(OpenCallSubmission.promoted_sponsor),
        )
    )
    if org_id:
        query = query.where(OpenCallSubmission.org_id == org_id)

    sub = await db.scalar(query)
    if not sub:
        raise HTTPException(404, "Submission not found.")
    return sub


async def list_submissions_for_call(
    db: AsyncSession,
    call_id: uuid.UUID,
    org_id: uuid.UUID,
    *,
    status: str | None = None,
    track: str | None = None,
    search: str | None = None,
) -> list[OpenCallSubmission]:
    # Ensure call belongs to org
    await get_open_call(db, call_id, org_id=org_id)

    query = select(OpenCallSubmission).where(
        OpenCallSubmission.call_id == call_id,
        OpenCallSubmission.org_id == org_id,
    )
    if status and status != "all":
        query = query.where(OpenCallSubmission.status == status)
    if track and track != "all":
        query = query.where(OpenCallSubmission.category_or_track == track)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(
                OpenCallSubmission.name.ilike(pattern),
                OpenCallSubmission.email.ilike(pattern),
                OpenCallSubmission.title.ilike(pattern),
                OpenCallSubmission.organization_name.ilike(pattern),
            )
        )

    query = query.order_by(desc(OpenCallSubmission.created_at))
    result = await db.scalars(query)
    return list(result.all())


async def review_submission(
    db: AsyncSession,
    submission_id: uuid.UUID,
    org_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    data: OpenCallSubmissionReviewRequest,
) -> OpenCallSubmission:
    sub = await get_submission(db, submission_id, org_id=org_id)

    sub.status = data.status
    if data.rating is not None:
        sub.rating = data.rating
    if data.organizer_notes is not None:
        sub.organizer_notes = data.organizer_notes
    if data.feedback_to_applicant is not None:
        sub.feedback_to_applicant = data.feedback_to_applicant

    sub.reviewed_by = reviewer_id
    sub.reviewed_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(sub)
    return sub


async def promote_submission(
    db: AsyncSession,
    submission_id: uuid.UUID,
    org_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    data: OpenCallSubmissionPromoteRequest,
) -> tuple[OpenCallSubmission, Any]:
    """Promotes an accepted proposal to a live platform entity:
    - Speakers/Papers -> Creates or links Speaker & EventSpeaker on the event
    - Sponsors -> Creates Sponsor row on the event
    """
    sub = await get_submission(db, submission_id, org_id=org_id)
    call = sub.open_call

    promoted_entity: Any = None

    if call.call_type in ("speaker", "papers", "custom"):
        if sub.promoted_to_speaker_id:
            raise HTTPException(400, "This proposal has already been promoted to an event speaker.")

        # 1. Look up existing speaker by email or name in this org
        speaker = await db.scalar(
            select(Speaker).where(
                Speaker.org_id == org_id,
                or_(
                    Speaker.invite_email == sub.email,
                    Speaker.name.ilike(sub.name),
                ),
            )
        )

        if not speaker:
            # Generate speaker slug
            base_slug = slugify(sub.name, max_length=200) or "speaker"
            slug = base_slug
            cnt = 1
            while await db.scalar(select(Speaker.id).where(Speaker.slug == slug)):
                slug = f"{base_slug}-{cnt}"
                cnt += 1

            speaker = Speaker(
                org_id=org_id,
                slug=slug,
                name=sub.name,
                title=sub.job_title,
                company=sub.organization_name,
                bio=sub.bio or sub.proposal_summary,
                photo_url=sub.photo_url,
                social_links=sub.social_links or {},
                invite_email=sub.email,
                user_id=sub.user_id,
            )
            db.add(speaker)
            await db.flush()

        # 2. Check if already linked as EventSpeaker
        ev_speaker = await db.scalar(
            select(EventSpeaker).where(
                EventSpeaker.event_id == sub.event_id,
                EventSpeaker.speaker_id == speaker.id,
            )
        )
        if not ev_speaker:
            ev_speaker = EventSpeaker(
                event_id=sub.event_id,
                speaker_id=speaker.id,
                role_type=data.role_type,
            )
            db.add(ev_speaker)

        sub.promoted_to_speaker_id = speaker.id
        sub.status = "accepted"
        promoted_entity = speaker

    elif call.call_type == "sponsor":
        if sub.promoted_to_sponsor_id:
            raise HTTPException(400, "This proposal has already been promoted to an event sponsor.")

        sponsor_name = sub.organization_name or sub.title
        sponsor = Sponsor(
            event_id=sub.event_id,
            name=sponsor_name,
            tier=data.tier,
            description=sub.proposal_summary,
            website=sub.social_links.get("website") if sub.social_links else sub.attachment_url,
            logo_url=sub.photo_url,
            contact_email=sub.email,
            user_id=sub.user_id,
        )
        db.add(sponsor)
        await db.flush()

        sub.promoted_to_sponsor_id = sponsor.id
        sub.status = "accepted"
        promoted_entity = sponsor
    else:
        # Just accept other types like volunteers
        sub.status = "accepted"

    sub.reviewed_by = reviewer_id
    sub.reviewed_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(sub)
    return sub, promoted_entity
