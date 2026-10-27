from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.speaker import Sponsor
from app.schemas.sponsor import (
    SponsorCreateRequest,
    SponsorPortalUpdateRequest,
    SponsorUpdateRequest,
)
from app.utils.email import send_smtp

logger = structlog.get_logger()

_INVITE_TOKEN_TYPE = "sponsor_invite"
_INVITE_EXPIRE_DAYS = 14


async def list_sponsors(db: AsyncSession, event_id: uuid.UUID) -> list[Sponsor]:
    stmt = (
        select(Sponsor)
        .where(Sponsor.event_id == event_id)
        .order_by(Sponsor.sort_order, Sponsor.created_at)
    )
    result = await db.scalars(stmt)
    return list(result.all())


async def get_sponsor(db: AsyncSession, event_id: uuid.UUID, sponsor_id: uuid.UUID) -> Sponsor:
    sponsor = await db.scalar(
        select(Sponsor).where(Sponsor.id == sponsor_id, Sponsor.event_id == event_id)
    )
    if not sponsor:
        raise HTTPException(404, "Sponsor not found.")
    return sponsor


async def create_sponsor(
    db: AsyncSession, event_id: uuid.UUID, data: SponsorCreateRequest
) -> Sponsor:
    sponsor = Sponsor(
        event_id=event_id,
        name=data.name,
        logo_url=data.logo_url,
        website=data.website,
        description=data.description,
        tier=data.tier,
        sort_order=data.sort_order,
        is_exhibitor=data.is_exhibitor,
        booth_number=data.booth_number,
        category=data.category,
        contact_email=data.contact_email,
    )
    db.add(sponsor)
    await db.commit()
    await db.refresh(sponsor)
    return sponsor


async def update_sponsor(db: AsyncSession, sponsor: Sponsor, data: SponsorUpdateRequest) -> Sponsor:
    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(sponsor, field, value)
    await db.commit()
    await db.refresh(sponsor)
    return sponsor


async def delete_sponsor(db: AsyncSession, sponsor: Sponsor) -> None:
    await db.delete(sponsor)
    await db.commit()


# ── Sponsor portal: invite, claim, self-service edit ────────────────────────


def _make_sponsor_invite_token(sponsor_id: uuid.UUID) -> str:
    payload = {
        "type": _INVITE_TOKEN_TYPE,
        "sponsor_id": str(sponsor_id),
        "exp": datetime.now(UTC) + timedelta(days=_INVITE_EXPIRE_DAYS),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_sponsor_invite_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as err:
        raise HTTPException(400, "This invite link is invalid or has expired.") from err
    if payload.get("type") != _INVITE_TOKEN_TYPE:
        raise HTTPException(400, "This invite link is invalid or has expired.")
    return payload


def _send_sponsor_invite_email(
    email: str, sponsor_name: str, event_title: str, invite_url: str
) -> None:
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: Arial, sans-serif; background: #fff; color: #0A0A0A; max-width: 520px; margin: 0 auto; padding: 40px 24px;">
      <p style="font-size: 24px; font-weight: 700; margin: 0 0 8px;">tixdoo</p>
      <h1 style="font-size: 28px; font-weight: 700; margin: 32px 0 8px;">You&rsquo;ve been added as a sponsor</h1>
      <p style="font-size: 15px; color: #6B6B6B; margin: 0 0 32px;"><strong>{sponsor_name}</strong> has been listed as a sponsor of <strong>{event_title}</strong> on Tixdoo. Claim this listing to manage your logo, website, and description yourself.</p>
      <a href="{invite_url}" style="display: inline-block; background: #E85938; color: #FFFFFF; font-weight: 600; font-size: 15px; text-decoration: none; padding: 14px 28px; border-radius: 100px; margin-bottom: 32px;">Claim sponsorship</a>
      <p style="font-size: 13px; color: #ADADAD;">This invitation expires in 14 days.</p>
    </body>
    </html>
    """
    send_smtp(email, f"You've been added as a sponsor of {event_title}", html)


async def send_sponsor_invite(
    db: AsyncSession, sponsor: Sponsor, email: str, event_title: str
) -> str:
    sponsor.contact_email = email
    await db.commit()

    token = _make_sponsor_invite_token(sponsor.id)
    invite_url = f"{settings.FRONTEND_URL}/sponsor-invite/{token}"
    try:
        _send_sponsor_invite_email(email, sponsor.name, event_title, invite_url)
    except Exception as exc:
        logger.error("sponsor.invite_email_failed", exc=str(exc), email=email)
    logger.info("sponsor.invited", sponsor_id=str(sponsor.id), email=email)
    return token


async def get_sponsor_by_id(db: AsyncSession, sponsor_id: uuid.UUID) -> Sponsor | None:
    return await db.get(Sponsor, sponsor_id)


async def claim_sponsor(db: AsyncSession, sponsor: Sponsor, user_id: uuid.UUID) -> Sponsor:
    sponsor.user_id = user_id
    sponsor.invite_accepted = True
    await db.commit()
    await db.refresh(sponsor)
    return sponsor


async def list_my_sponsorships(db: AsyncSession, user_id: uuid.UUID) -> list[Sponsor]:
    stmt = select(Sponsor).where(Sponsor.user_id == user_id).order_by(Sponsor.created_at.desc())
    result = await db.scalars(stmt)
    return list(result.all())


async def get_my_sponsor(db: AsyncSession, user_id: uuid.UUID, sponsor_id: uuid.UUID) -> Sponsor:
    sponsor = await db.scalar(
        select(Sponsor).where(Sponsor.id == sponsor_id, Sponsor.user_id == user_id)
    )
    if not sponsor:
        raise HTTPException(404, "Sponsor not found.")
    return sponsor


async def update_my_sponsor_profile(
    db: AsyncSession, sponsor: Sponsor, data: SponsorPortalUpdateRequest
) -> Sponsor:
    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(sponsor, field, value)
    await db.commit()
    await db.refresh(sponsor)
    return sponsor
