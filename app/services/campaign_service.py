from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.campaign import Campaign, CampaignRecipient
from app.models.ticketing import Registration
from app.schemas.campaign import CampaignCreateRequest, CampaignUpdateRequest

_VALID_STATUSES = {"confirmed", "checked_in", "pending", "cancelled"}
_VALID_TYPES = {"email", "whatsapp", "sms"}


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def create_campaign(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    data: CampaignCreateRequest,
) -> Campaign:
    if data.type not in _VALID_TYPES:
        raise HTTPException(400, f"Invalid campaign type: {data.type}")
    if data.type == "email" and not data.subject:
        raise HTTPException(400, "Email campaigns require a subject.")

    statuses = [s for s in (data.audience_statuses or []) if s in _VALID_STATUSES]
    if not statuses:
        statuses = ["confirmed", "checked_in"]

    c = Campaign(
        org_id=org_id,
        event_id=data.event_id,
        created_by=user_id,
        type=data.type,
        name=data.name,
        subject=data.subject,
        body=data.body,
        status="draft",
        audience_filter={"statuses": statuses},
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def get_campaign(db: AsyncSession, campaign_id: uuid.UUID) -> Campaign | None:
    return await db.scalar(
        select(Campaign).where(Campaign.id == campaign_id)
    )


async def list_campaigns(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[Campaign], int]:
    stmt = select(Campaign).where(Campaign.org_id == org_id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    result = await db.scalars(
        stmt.order_by(Campaign.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return list(result.all()), total


async def update_campaign(
    db: AsyncSession,
    campaign: Campaign,
    data: CampaignUpdateRequest,
) -> Campaign:
    if campaign.status not in ("draft",):
        raise HTTPException(400, "Only draft campaigns can be edited.")

    updates = data.model_dump(exclude_none=True)
    for field, value in updates.items():
        if field == "audience_statuses":
            statuses = [s for s in value if s in _VALID_STATUSES] or ["confirmed", "checked_in"]
            campaign.audience_filter = {**(campaign.audience_filter or {}), "statuses": statuses}
        else:
            setattr(campaign, field, value)

    await db.commit()
    await db.refresh(campaign)
    return campaign


async def delete_campaign(db: AsyncSession, campaign: Campaign) -> None:
    if campaign.status == "sending":
        raise HTTPException(400, "Cannot delete a campaign that is currently sending.")
    await db.delete(campaign)
    await db.commit()


# ── Audience ──────────────────────────────────────────────────────────────────

async def preview_audience_count(
    db: AsyncSession,
    org_id: uuid.UUID,
    event_id: uuid.UUID | None,
    statuses: list[str],
) -> int:
    valid = [s for s in statuses if s in _VALID_STATUSES] or ["confirmed", "checked_in"]

    if event_id:
        stmt = select(func.count(Registration.id)).where(
            Registration.event_id == event_id,
            Registration.status.in_(valid),
        )
    else:
        from app.models.event import Event
        stmt = (
            select(func.count(Registration.id))
            .join(Event, Event.id == Registration.event_id)
            .where(Event.org_id == org_id, Registration.status.in_(valid))
        )
    return await db.scalar(stmt) or 0


async def _build_recipients(db: AsyncSession, campaign: Campaign) -> int:
    statuses = (campaign.audience_filter or {}).get("statuses", ["confirmed", "checked_in"])

    await db.execute(
        delete(CampaignRecipient).where(CampaignRecipient.campaign_id == campaign.id)
    )

    if campaign.event_id:
        stmt = select(Registration).where(
            Registration.event_id == campaign.event_id,
            Registration.status.in_(statuses),
        )
    else:
        from app.models.event import Event
        stmt = (
            select(Registration)
            .join(Event, Event.id == Registration.event_id)
            .where(Event.org_id == campaign.org_id, Registration.status.in_(statuses))
        )

    rows = await db.scalars(stmt)
    recs = [
        CampaignRecipient(
            campaign_id=campaign.id,
            registration_id=reg.id,
            email=reg.attendee_email,
            whatsapp_number=reg.attendee_phone,
            phone=reg.attendee_phone,
            name=reg.attendee_name,
            status="pending",
        )
        for reg in rows.all()
    ]
    if recs:
        db.add_all(recs)
    campaign.recipient_count = len(recs)
    return len(recs)


# ── Send / schedule ───────────────────────────────────────────────────────────

async def send_now(db: AsyncSession, campaign: Campaign) -> Campaign:
    if campaign.status not in ("draft", "scheduled"):
        raise HTTPException(400, f"Cannot send a campaign with status '{campaign.status}'.")

    await _build_recipients(db, campaign)
    if campaign.recipient_count == 0:
        raise HTTPException(400, "No recipients match the audience filter. Add attendees first.")

    campaign.status = "sending"
    campaign.scheduled_at = None
    await db.commit()

    from app.tasks.campaign import send_campaign as _task
    _task.delay(str(campaign.id))
    return campaign


async def schedule_campaign(
    db: AsyncSession,
    campaign: Campaign,
    scheduled_at: datetime,
) -> Campaign:
    if campaign.status not in ("draft", "scheduled"):
        raise HTTPException(400, f"Cannot schedule a campaign with status '{campaign.status}'.")

    await _build_recipients(db, campaign)
    if campaign.recipient_count == 0:
        raise HTTPException(400, "No recipients match the audience filter.")

    campaign.status = "scheduled"
    campaign.scheduled_at = scheduled_at
    await db.commit()
    return campaign


# ── Stats ─────────────────────────────────────────────────────────────────────

async def get_recipient_stats(db: AsyncSession, campaign_id: uuid.UUID) -> dict:
    """Return {status: count} for every distinct recipient status in the campaign."""
    rows = await db.execute(
        select(CampaignRecipient.status, func.count(CampaignRecipient.id).label("n"))
        .where(CampaignRecipient.campaign_id == campaign_id)
        .group_by(CampaignRecipient.status)
    )
    return {row.status: row.n for row in rows}


async def cancel_campaign(db: AsyncSession, campaign: Campaign) -> Campaign:
    """Revert a scheduled campaign back to draft and clear the scheduled_at time."""
    if campaign.status != "scheduled":
        raise HTTPException(400, f"Only scheduled campaigns can be cancelled (current status: '{campaign.status}').")
    campaign.status = "draft"
    campaign.scheduled_at = None
    await db.commit()
    await db.refresh(campaign)
    return campaign


async def get_recent_recipients(
    db: AsyncSession,
    campaign_id: uuid.UUID,
    limit: int = 100,
) -> list[CampaignRecipient]:
    result = await db.scalars(
        select(CampaignRecipient)
        .where(CampaignRecipient.campaign_id == campaign_id)
        .order_by(CampaignRecipient.sent_at.desc().nullslast(), CampaignRecipient.created_at.desc())
        .limit(limit)
    )
    return list(result.all())
