"""
Celery WhatsApp tasks.
Uses the same sync DB session pattern as app/tasks/email.py.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from celery import shared_task

from app.config import settings
from app.services import whatsapp_service as wa

log = structlog.get_logger()

# Shared sync engine (same lazy init pattern as email tasks)
_engine = None
_SyncSession = None


def _db():
    global _engine, _SyncSession
    if _engine is None:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        _engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True, pool_size=2, max_overflow=4)
        _SyncSession = sessionmaker(bind=_engine)
    return _SyncSession()


# ── Registration confirmation ─────────────────────────────────────────────────

@shared_task(name="app.tasks.whatsapp.send_registration_confirmation", max_retries=3, default_retry_delay=60)
def send_registration_confirmation(order_id: str) -> None:
    """Send WhatsApp confirmation + QR codes for each ticket in the order."""
    from app.models.event import Event
    from app.models.ticketing import Order, Registration

    with _db() as db:
        from sqlalchemy.orm import joinedload
        order = (
            db.query(Order)
            .options(joinedload(Order.registrations).joinedload(Registration.ticket_type))
            .filter(Order.id == uuid.UUID(order_id))
            .first()
        )
        if not order or not order.buyer_phone or order.payment_status != "paid":
            return

        event = db.query(Event).filter(Event.id == order.event_id).first()
        if not event:
            return

        confirmed = [
            {
                "registration_id": str(r.id),
                "attendee_name": r.attendee_name,
                "ticket_type": r.ticket_type.name if r.ticket_type else "General",
            }
            for r in order.registrations
            if r.status in ("confirmed", "checked_in")
        ]
        if not confirmed:
            return

        wa.send_registration_confirmation_sync(
            phone=order.buyer_phone,
            buyer_name=order.buyer_name or order.buyer_email,
            event=event,
            registrations=confirmed,
        )

    log.info("whatsapp.confirmation.sent", order_id=order_id)


# ── Event reminder (24 h before) ─────────────────────────────────────────────

@shared_task(name="app.tasks.whatsapp.send_event_reminders")
def send_event_reminders() -> None:
    """
    Hourly Beat task — finds events starting in 23–25 h and WhatsApps attendees.
    Uses Redis dedup (same key namespace as email reminders, different suffix).
    """
    from app.models.event import Event
    from app.models.ticketing import Registration

    now = datetime.now(UTC)
    window_start = now + timedelta(hours=23)
    window_end = now + timedelta(hours=25)

    try:
        from redis import Redis as _Redis
        redis = _Redis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception:
        redis = None

    with _db() as db:
        events = (
            db.query(Event)
            .filter(
                Event.status.in_(["published", "live"]),
                Event.start_datetime >= window_start,
                Event.start_datetime <= window_end,
                Event.deleted_at.is_(None),
            )
            .all()
        )

        for event in events:
            sent_key = f"wa_reminder:{event.id}"
            regs = (
                db.query(Registration)
                .filter(
                    Registration.event_id == event.id,
                    Registration.status == "confirmed",
                    Registration.attendee_phone.isnot(None),
                )
                .all()
            )

            for reg in regs:
                rid = str(reg.id)
                if redis and redis.sismember(sent_key, rid):
                    continue
                try:
                    wa.send_event_reminder_sync(
                        phone=reg.attendee_phone,
                        attendee_name=reg.attendee_name,
                        event=event,
                        registration_id=rid,
                    )
                    if redis:
                        redis.sadd(sent_key, rid)
                        redis.expire(sent_key, 48 * 3600)
                except Exception as exc:
                    log.warning("whatsapp.reminder.failed", reg_id=rid, error=str(exc))


# ── Waitlist notification ─────────────────────────────────────────────────────

@shared_task(name="app.tasks.whatsapp.send_waitlist_notification", max_retries=3, default_retry_delay=60)
def send_waitlist_notification(waitlist_id: str) -> None:
    from app.models.ticketing import Waitlist, TicketType
    from app.models.event import Event

    with _db() as db:
        wl = db.query(Waitlist).filter(Waitlist.id == uuid.UUID(waitlist_id)).first()
        if not wl:
            return

        event = db.query(Event).filter(Event.id == wl.event_id).first()
        tt = db.query(TicketType).filter(TicketType.id == wl.ticket_type_id).first()

        wa.send_waitlist_notification_sync(
            phone=wl.email,  # waitlist stores email; phone lookup via user table if needed
            name=wl.name,
            event=event,
            ticket_type_name=tt.name if tt else "General",
            register_url=(
                f"{settings.FRONTEND_URL}/e/{event.slug}/register"
                if event else settings.FRONTEND_URL
            ),
        )


# ── Bot reply dispatcher ──────────────────────────────────────────────────────

@shared_task(name="app.tasks.whatsapp.handle_incoming_message")
def handle_incoming_message(from_phone: str, message_text: str) -> None:
    """
    Process an incoming WhatsApp message and send an appropriate reply.
    Dispatched from the webhook handler so the 200 response isn't blocked.
    """
    from app.models.ticketing import Registration
    from app.models.event import Event
    from app.models.organization import Organization
    from app.models.community import WhatsAppMessage

    text = message_text.strip().upper()

    with _db() as db:
        # Resolve org from attendee's most recent registration
        phone_norm = wa.format_phone(from_phone)
        phone_last10 = phone_norm[-10:] if phone_norm else None
        org_id = None
        if phone_last10:
            reg = (
                db.query(Registration)
                .filter(
                    Registration.attendee_phone.like(f"%{phone_last10}"),
                    Registration.status.in_(["confirmed", "checked_in"]),
                )
                .order_by(Registration.created_at.desc())
                .first()
            )
            if reg:
                ev = db.query(Event).filter(Event.id == reg.event_id).first()
                if ev:
                    org_id = ev.org_id

        # Store inbound message for the inbox
        if org_id:
            try:
                msg = WhatsAppMessage(
                    org_id=org_id,
                    from_number=phone_norm or from_phone,
                    to_number=settings.WHATSAPP_PHONE_NUMBER_ID or "heelo",
                    direction="inbound",
                    body=message_text,
                    message_type="text",
                    status="delivered",
                    is_read_by_org=False,
                )
                db.add(msg)
                db.commit()
            except Exception:
                db.rollback()
        _STOP_WORDS = {"STOP", "UNSUBSCRIBE", "OPTOUT", "OPT OUT", "OPT-OUT", "CANCEL", "END", "QUIT"}
        _START_WORDS = {"START", "SUBSCRIBE", "OPT IN", "OPT-IN", "YES"}

        if text in _STOP_WORDS:
            # Mark any Contact records with this number as unsubscribed
            try:
                from app.models.crm import Contact
                if phone_last10:
                    contacts_to_unsub = (
                        db.query(Contact)
                        .filter(Contact.whatsapp_number.like(f"%{phone_last10}"))
                        .all()
                    )
                    for c in contacts_to_unsub:
                        c.is_unsubscribed = True
                    if contacts_to_unsub:
                        db.commit()
            except Exception:
                pass
            # Persist in Redis so campaign sends can respect opt-out
            try:
                from redis import Redis as _Redis
                _r = _Redis.from_url(settings.REDIS_URL, decode_responses=True)
                _r.sadd("wa:optout", phone_norm or from_phone)
            except Exception:
                pass
            wa.send_text_sync(
                from_phone,
                "You've been unsubscribed from WhatsApp messages. Reply START to resubscribe.",
            )
            return

        if text in _START_WORDS:
            # Resubscribe
            try:
                from app.models.crm import Contact
                if phone_last10:
                    contacts_to_resub = (
                        db.query(Contact)
                        .filter(Contact.whatsapp_number.like(f"%{phone_last10}"))
                        .all()
                    )
                    for c in contacts_to_resub:
                        c.is_unsubscribed = False
                    if contacts_to_resub:
                        db.commit()
            except Exception:
                pass
            try:
                from redis import Redis as _Redis
                _r = _Redis.from_url(settings.REDIS_URL, decode_responses=True)
                _r.srem("wa:optout", phone_norm or from_phone)
            except Exception:
                pass
            wa.send_text_sync(from_phone, "You've been resubscribed to WhatsApp messages.")
            return

        if text in ("TICKET", "TICKETS", "MY TICKET", "STATUS"):
            phone_last10 = wa.format_phone(from_phone)
            phone_last10 = phone_last10[-10:] if phone_last10 else None

            if not phone_last10:
                wa.send_text_sync(from_phone, "Could not look up your number. Visit heelo.io for help.")
                return

            from sqlalchemy.orm import joinedload
            from sqlalchemy import select as sa_select
            from app.models.event import Event as EventModel

            regs = (
                db.query(Registration)
                .options(joinedload(Registration.ticket_type))
                .filter(
                    Registration.attendee_phone.like(f"%{phone_last10}"),
                    Registration.status.in_(["confirmed", "checked_in"]),
                )
                .limit(10)
                .all()
            )

            # Annotate each registration with its event title
            event_ids = list({r.event_id for r in regs})
            events_map = {
                e.id: e for e in db.query(EventModel).filter(EventModel.id.in_(event_ids)).all()
            } if event_ids else {}

            for reg in regs:
                ev = events_map.get(reg.event_id)
                reg._event_title = ev.title if ev else "Event"

            reply = wa.build_ticket_status_reply(regs)
            wa.send_text_sync(from_phone, reply)

        else:
            # Try AI-powered reply; fall back to static help text if AI unavailable
            try:
                from app.tasks.ai_tasks import suggest_whatsapp_reply
                suggest_whatsapp_reply.delay(from_phone, message_text)
            except Exception:
                wa.send_text_sync(from_phone, wa.HELP_TEXT)
