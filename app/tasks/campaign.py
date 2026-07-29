from __future__ import annotations

import uuid
from datetime import UTC, datetime

from celery import shared_task
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

_engine = None
_SyncSession: sessionmaker | None = None


def _get_session() -> Session:
    global _engine, _SyncSession
    if _SyncSession is None:
        _engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
        _SyncSession = sessionmaker(bind=_engine, expire_on_commit=False)
    return _SyncSession()


def _render(template: str, ctx: dict) -> str:
    for key, value in ctx.items():
        template = template.replace("{{" + key + "}}", str(value or ""))
    return template


@shared_task(name="app.tasks.campaign.send_campaign", max_retries=0)
def send_campaign(campaign_id: str) -> None:
    from app.models.campaign import Campaign, CampaignRecipient
    from app.models.event import Event
    from app.models.organization import Organization

    with _get_session() as db:
        cid = uuid.UUID(campaign_id)
        campaign: Campaign | None = db.scalar(select(Campaign).where(Campaign.id == cid))
        if not campaign:
            return

        campaign.status = "sending"
        db.commit()

        org: Organization | None = db.scalar(select(Organization).where(Organization.id == campaign.org_id))
        event: Event | None = (
            db.scalar(select(Event).where(Event.id == campaign.event_id))
            if campaign.event_id else None
        )

        recipients = list(db.scalars(
            select(CampaignRecipient).where(
                CampaignRecipient.campaign_id == cid,
                CampaignRecipient.status == "pending",
            )
        ))

        ctx = {
            "org_name": org.name if org else "",
            "event_name": event.title if event else "",
            "event_date": (
                event.start_datetime.strftime("%B %d, %Y") if event and event.start_datetime else ""
            ),
        }

        sent = 0
        failed = 0
        now = datetime.now(UTC)

        if campaign.type == "email":
            from app.services.email_service import send_sync as _send_email
            for rec in recipients:
                if not rec.email:
                    rec.status = "failed"
                    rec.error_message = "No email address"
                    failed += 1
                    continue
                rec_ctx = {**ctx, "name": rec.name or "there"}
                subject = _render(campaign.subject or campaign.name, rec_ctx)
                html = _render(campaign.body or "", rec_ctx)
                try:
                    _send_email(rec.email, subject, html)
                    rec.status = "sent"
                    rec.sent_at = now
                    sent += 1
                except Exception as exc:
                    rec.status = "failed"
                    rec.error_message = str(exc)[:255]
                    failed += 1

        elif campaign.type == "whatsapp":
            from app.services.whatsapp_service import send_text_sync as _send_wa, format_phone as _fmt_phone
            # Load global opt-out set from Redis
            try:
                from redis import Redis as _Redis
                _r = _Redis.from_url(settings.REDIS_URL, decode_responses=True)
                _optout = _r.smembers("wa:optout")
            except Exception:
                _optout = set()
            for rec in recipients:
                if not rec.whatsapp_number:
                    rec.status = "failed"
                    rec.error_message = "No WhatsApp number"
                    failed += 1
                    continue
                _phone_norm = _fmt_phone(rec.whatsapp_number) or rec.whatsapp_number
                if _phone_norm in _optout:
                    rec.status = "failed"
                    rec.error_message = "Unsubscribed"
                    failed += 1
                    continue
                rec_ctx = {**ctx, "name": rec.name or "there"}
                text = _render(campaign.body or "", rec_ctx)
                try:
                    _send_wa(rec.whatsapp_number, text)
                    rec.status = "sent"
                    rec.sent_at = now
                    sent += 1
                except Exception as exc:
                    rec.status = "failed"
                    rec.error_message = str(exc)[:255]
                    failed += 1

        else:
            for rec in recipients:
                rec.status = "failed"
                rec.error_message = f"Channel '{campaign.type}' not yet implemented"
                failed += 1

        campaign.sent_count = sent
        campaign.failed_count = failed
        campaign.sent_at = now
        campaign.status = "sent" if sent > 0 else "failed"
        db.commit()


@shared_task(name="app.tasks.campaign.send_scheduled_campaigns")
def send_scheduled_campaigns() -> None:
    from app.models.campaign import Campaign

    now = datetime.now(UTC)
    with _get_session() as db:
        due = list(db.scalars(
            select(Campaign).where(
                Campaign.status == "scheduled",
                Campaign.scheduled_at <= now,
            )
        ))
        for c in due:
            send_campaign.delay(str(c.id))
