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


def _send_campaign_recipients(db: Session, campaign) -> tuple[int, int]:
    """Send to every pending recipient of `campaign`. Returns (sent, failed)."""
    from app.models.campaign import CampaignRecipient
    from app.models.event import Event
    from app.models.organization import Organization

    org: Organization | None = db.scalar(
        select(Organization).where(Organization.id == campaign.org_id)
    )
    event: Event | None = (
        db.scalar(select(Event).where(Event.id == campaign.event_id)) if campaign.event_id else None
    )

    recipients = list(
        db.scalars(
            select(CampaignRecipient).where(
                CampaignRecipient.campaign_id == campaign.id,
                CampaignRecipient.status == "pending",
            )
        )
    )

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
        from app.services import email_service as em
        from app.utils.auth import create_unsubscribe_token

        for rec in recipients:
            if not rec.email:
                rec.status = "failed"
                rec.error_message = "No email address"
                failed += 1
                continue
            rec_ctx = {**ctx, "name": rec.name or "there"}
            subject = _render(campaign.subject or campaign.name, rec_ctx)
            body_html = _render(campaign.body or "", rec_ctx)
            token = create_unsubscribe_token(str(campaign.org_id), rec.email)
            html = em.render(
                "campaign_branded.html",
                org=org,
                subject=subject,
                body_html=body_html,
                unsubscribe_url=f"{settings.FRONTEND_URL}/unsubscribe/{token}",
            )
            try:
                em.send_sync(rec.email, subject, html)
                rec.status = "sent"
                rec.sent_at = now
                sent += 1
            except Exception as exc:
                rec.status = "failed"
                rec.error_message = str(exc)[:255]
                failed += 1

    elif campaign.type == "whatsapp":
        from app.services.whatsapp_service import format_phone as _fmt_phone
        from app.services.whatsapp_service import send_text_sync as _send_wa

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

    elif campaign.type == "sms":
        from app.utils.sms import send_sms_sync

        for rec in recipients:
            phone_target = rec.phone or rec.whatsapp_number
            if not phone_target:
                rec.status = "failed"
                rec.error_message = "No phone number"
                failed += 1
                continue
            rec_ctx = {**ctx, "name": rec.name or "there"}
            text = _render(campaign.body or "", rec_ctx)
            try:
                res = send_sms_sync(phone_target, text)
                rec.status = "sent"
                rec.sent_at = now
                rec.provider_message_id = res.get("message_id")
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

    return sent, failed


@shared_task(name="app.tasks.campaign.send_campaign", max_retries=0)
def send_campaign(campaign_id: str) -> None:
    from app.models.campaign import Campaign

    with _get_session() as db:
        cid = uuid.UUID(campaign_id)
        campaign: Campaign | None = db.scalar(select(Campaign).where(Campaign.id == cid))
        if not campaign:
            return

        campaign.status = "sending"
        db.commit()

        try:
            sent, failed = _send_campaign_recipients(db, campaign)
            campaign.sent_count = sent
            campaign.failed_count = failed
            campaign.sent_at = datetime.now(UTC)
            campaign.status = "sent" if sent > 0 else "failed"
            db.commit()
        except Exception:
            # A partial per-recipient failure is tracked per-row above and never
            # reaches here - this only catches catastrophic failures (e.g. a
            # dropped DB connection). Without this, `status` would stay stuck on
            # "sending" forever since this task has max_retries=0.
            db.rollback()
            campaign.status = "failed"
            db.commit()
            raise


@shared_task(name="app.tasks.campaign.send_scheduled_campaigns")
def send_scheduled_campaigns() -> None:
    from app.models.campaign import Campaign

    now = datetime.now(UTC)
    with _get_session() as db:
        due = list(
            db.scalars(
                select(Campaign).where(
                    Campaign.status == "scheduled",
                    Campaign.scheduled_at <= now,
                )
            )
        )
        for c in due:
            send_campaign.delay(str(c.id))
