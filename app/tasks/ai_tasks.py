"""
AI-powered async tasks — runs via Celery worker.
Uses the sync Anthropic client (same pattern as email/whatsapp tasks).
"""

from __future__ import annotations

import structlog
from celery import shared_task

from app.config import settings
from app.services import ai_service as ai_svc

log = structlog.get_logger()

_engine = None
_SyncSession = None


def _db():
    global _engine, _SyncSession
    if _engine is None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        _engine = create_engine(
            settings.DATABASE_URL_SYNC,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=4,
        )
        _SyncSession = sessionmaker(bind=_engine)
    return _SyncSession()


@shared_task(name="app.tasks.ai.suggest_whatsapp_reply", max_retries=0)
def suggest_whatsapp_reply(from_phone: str, message_text: str) -> None:
    """
    Generate an AI-powered WhatsApp reply for an inbound attendee message.
    Looks up the attendee's registration context, generates a reply,
    and sends it via WhatsApp.
    """
    if not settings.ANTHROPIC_API_KEY:
        log.info("ai.whatsapp_reply.skipped", reason="no_api_key")
        return

    from app.models.event import Event
    from app.models.organization import Organization
    from app.models.ticketing import Registration
    from app.services import whatsapp_service as wa

    phone_digits = wa.format_phone(from_phone)
    phone_last10 = phone_digits[-10:] if phone_digits else None

    attendee_name = ""
    org_name = ""
    event_context = ""

    with _db() as db:
        if phone_last10:
            regs = (
                db.query(Registration)
                .filter(
                    Registration.attendee_phone.like(f"%{phone_last10}"),
                    Registration.status.in_(["confirmed", "checked_in"]),
                )
                .order_by(Registration.created_at.desc())
                .limit(3)
                .all()
            )
            if regs:
                attendee_name = regs[0].attendee_name
                event_ids = [r.event_id for r in regs]
                events = db.query(Event).filter(Event.id.in_(event_ids)).all()
                if events:
                    ev = events[0]
                    org = db.query(Organization).filter(Organization.id == ev.org_id).first()
                    org_name = org.name if org else "Heelo"
                    event_context = ev.title + (
                        f" on {ev.start_datetime.strftime('%b %d, %Y')}"
                        if ev.start_datetime
                        else ""
                    )

        try:
            reply = ai_svc.suggest_whatsapp_reply_sync(
                message_text=message_text,
                attendee_name=attendee_name,
                org_name=org_name,
                event_context=event_context,
            )
            if reply:
                wa.send_text_sync(from_phone, reply)
                log.info("ai.whatsapp_reply.sent", phone=from_phone[:6] + "****")
            else:
                wa.send_text_sync(from_phone, wa.HELP_TEXT)
        except Exception as exc:
            log.warning("ai.whatsapp_reply.failed", error=str(exc))
            try:
                wa.send_text_sync(from_phone, wa.HELP_TEXT)
            except Exception as fallback_exc:
                log.error("ai.whatsapp_fallback_reply.failed", error=str(fallback_exc))
