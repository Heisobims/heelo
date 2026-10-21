from __future__ import annotations

import uuid

from fastapi import HTTPException
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.speaker import EventSpeaker, Speaker
from app.schemas.speaker import (
    EventSpeakerLinkRequest,
    EventSpeakerOut,
    EventSpeakerUpdateRequest,
    SpeakerCreateRequest,
    SpeakerUpdateRequest,
)


async def _unique_speaker_slug(db: AsyncSession, base: str) -> str:
    slug = base or "speaker"
    counter = 2
    while await db.scalar(select(Speaker.id).where(Speaker.slug == slug)):
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def event_speaker_to_dict(link: EventSpeaker) -> dict:
    return EventSpeakerOut(
        id=link.id,
        speaker_id=link.speaker_id,
        speaker_slug=link.speaker.slug,
        role_type=link.role_type,
        sort_order=link.sort_order,
        name=link.speaker.name,
        title=link.speaker.title,
        company=link.speaker.company,
        bio=link.speaker.bio,
        photo_url=link.speaker.photo_url,
        social_links=link.speaker.social_links,
    ).model_dump(mode="json")


# ── Org-level speaker roster ────────────────────────────────────────────────


async def list_org_speakers(db: AsyncSession, org_id: uuid.UUID) -> list[Speaker]:
    stmt = select(Speaker).where(Speaker.org_id == org_id).order_by(Speaker.name)
    result = await db.scalars(stmt)
    return list(result.all())


async def get_org_speaker(db: AsyncSession, org_id: uuid.UUID, speaker_id: uuid.UUID) -> Speaker:
    speaker = await db.scalar(
        select(Speaker).where(Speaker.id == speaker_id, Speaker.org_id == org_id)
    )
    if not speaker:
        raise HTTPException(404, "Speaker not found.")
    return speaker


async def get_speaker_by_slug(db: AsyncSession, slug: str) -> Speaker | None:
    return await db.scalar(select(Speaker).where(Speaker.slug == slug))


async def list_public_events_for_speaker(db: AsyncSession, speaker_id: uuid.UUID) -> list[tuple]:
    """Returns (Event, role_type) pairs for every public event this speaker
    is linked to, newest first."""
    from app.models.event import Event

    stmt = (
        select(Event, EventSpeaker.role_type)
        .join(EventSpeaker, EventSpeaker.event_id == Event.id)
        .where(
            EventSpeaker.speaker_id == speaker_id,
            Event.status.in_(["published", "live", "ended"]),
            Event.deleted_at.is_(None),
        )
        .order_by(Event.start_datetime.desc())
    )
    result = await db.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def create_speaker(
    db: AsyncSession, org_id: uuid.UUID, data: SpeakerCreateRequest
) -> Speaker:
    slug = await _unique_speaker_slug(
        db, slugify(data.name, max_length=200, word_boundary=True, separator="-")
    )
    speaker = Speaker(
        org_id=org_id,
        slug=slug,
        name=data.name,
        title=data.title,
        company=data.company,
        bio=data.bio,
        photo_url=data.photo_url,
        social_links=data.social_links,
    )
    db.add(speaker)
    await db.commit()
    await db.refresh(speaker)
    return speaker


async def update_speaker(db: AsyncSession, speaker: Speaker, data: SpeakerUpdateRequest) -> Speaker:
    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(speaker, field, value)
    await db.commit()
    await db.refresh(speaker)
    return speaker


async def delete_speaker(db: AsyncSession, speaker: Speaker) -> None:
    await db.delete(speaker)
    await db.commit()


# ── Event People roster (event <-> speaker links) ───────────────────────────


async def list_event_speakers(db: AsyncSession, event_id: uuid.UUID) -> list[EventSpeaker]:
    stmt = (
        select(EventSpeaker)
        .where(EventSpeaker.event_id == event_id)
        .options(selectinload(EventSpeaker.speaker))
        .order_by(EventSpeaker.sort_order, EventSpeaker.created_at)
    )
    result = await db.scalars(stmt)
    return list(result.all())


async def get_event_speaker_link(
    db: AsyncSession, event_id: uuid.UUID, link_id: uuid.UUID
) -> EventSpeaker:
    link = await db.scalar(
        select(EventSpeaker)
        .where(EventSpeaker.id == link_id, EventSpeaker.event_id == event_id)
        .options(selectinload(EventSpeaker.speaker))
    )
    if not link:
        raise HTTPException(404, "Speaker not found on this event.")
    return link


async def add_event_speaker(
    db: AsyncSession,
    org_id: uuid.UUID,
    event_id: uuid.UUID,
    data: EventSpeakerLinkRequest,
) -> EventSpeaker:
    if data.speaker_id:
        speaker = await get_org_speaker(db, org_id, data.speaker_id)
    else:
        slug = await _unique_speaker_slug(
            db, slugify(data.name, max_length=200, word_boundary=True, separator="-")
        )
        speaker = Speaker(
            org_id=org_id,
            slug=slug,
            name=data.name,
            title=data.title,
            company=data.company,
            bio=data.bio,
            photo_url=data.photo_url,
            social_links=data.social_links,
        )
        db.add(speaker)
        await db.flush()

    link = EventSpeaker(
        event_id=event_id,
        speaker_id=speaker.id,
        role_type=data.role_type,
        sort_order=data.sort_order,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    link.speaker = speaker
    return link


async def update_event_speaker(
    db: AsyncSession, link: EventSpeaker, data: EventSpeakerUpdateRequest
) -> EventSpeaker:
    updates = data.model_dump(exclude_unset=True)
    speaker_fields = {"name", "title", "company", "bio", "photo_url", "social_links"}
    for field, value in updates.items():
        if field in speaker_fields:
            setattr(link.speaker, field, value)
        else:
            setattr(link, field, value)
    await db.commit()
    await db.refresh(link)
    return link


async def remove_event_speaker(db: AsyncSession, link: EventSpeaker) -> None:
    """Unlink the person from this event. Since the current UI has no
    "reuse an existing speaker across events" picker, every link is created
    from a freshly-typed person - so if this was their only event, drop the
    underlying Speaker row too rather than leaving an orphaned roster entry."""
    speaker_id = link.speaker_id
    await db.delete(link)
    await db.flush()
    remaining = await db.scalar(
        select(EventSpeaker.id).where(EventSpeaker.speaker_id == speaker_id).limit(1)
    )
    if not remaining:
        speaker = await db.get(Speaker, speaker_id)
        if speaker:
            await db.delete(speaker)
    await db.commit()
