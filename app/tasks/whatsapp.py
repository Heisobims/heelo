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

        _engine = create_engine(
            settings.DATABASE_URL_SYNC, pool_pre_ping=True, pool_size=2, max_overflow=4
        )
        _SyncSession = sessionmaker(bind=_engine)
    return _SyncSession()


# ── Registration confirmation ─────────────────────────────────────────────────


@shared_task(
    name="app.tasks.whatsapp.send_registration_confirmation", max_retries=3, default_retry_delay=60
)
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
        if not order.whatsapp_consent:
            log.info("whatsapp.confirmation.skipped", order_id=order_id, reason="no_consent")
            return

        event = db.query(Event).filter(Event.id == order.event_id).first()
        if not event:
            return

        confirmed_regs = [r for r in order.registrations if r.status in ("confirmed", "checked_in")]
        confirmed = [
            {
                "registration_id": str(r.id),
                "attendee_name": r.attendee_name,
                "ticket_type": r.ticket_type.name if r.ticket_type else "General",
            }
            for r in confirmed_regs
        ]
        if not confirmed:
            return

        try:
            wa.send_registration_confirmation_sync(
                phone=order.buyer_phone,
                buyer_name=order.buyer_name or order.buyer_email,
                event=event,
                registrations=confirmed,
            )
        except Exception as exc:
            log.warning("whatsapp.confirmation.failed", order_id=order_id, error=str(exc))
            return

        now = datetime.now(UTC)
        for r in confirmed_regs:
            r.whatsapp_sent_at = now
        db.commit()

    log.info("whatsapp.confirmation.sent", order_id=order_id)


# ── Registration cancellation ─────────────────────────────────────────────────


@shared_task(
    name="app.tasks.whatsapp.send_registration_cancellation", max_retries=3, default_retry_delay=60
)
def send_registration_cancellation(registration_id: str) -> None:
    from app.models.event import Event
    from app.models.ticketing import Registration

    with _db() as db:
        reg = db.query(Registration).filter(Registration.id == uuid.UUID(registration_id)).first()
        if not reg or not reg.whatsapp_consent or not reg.attendee_phone:
            return

        event = db.query(Event).filter(Event.id == reg.event_id).first()
        if not event:
            return

        wa.send_registration_cancellation_sync(
            phone=reg.attendee_phone,
            attendee_name=reg.attendee_name,
            event=event,
            ticket_type_name=reg.ticket_type.name if reg.ticket_type else "General",
            refunded=(reg.status == "refunded"),
        )

    log.info("whatsapp.cancellation.sent", registration_id=registration_id)


# ── Event reminders (configurable intervals) ──────────────────────────────────

DEFAULT_REMINDER_HOURS = [24, 1]
_MAX_REMINDER_HORIZON_DAYS = 14  # events further out than this are never scanned


def _reminder_hours(event) -> list[float]:
    """Per-event configured reminder offsets, from Event.extras['whatsapp_reminder_hours']."""
    raw = (event.extras or {}).get("whatsapp_reminder_hours") if event.extras else None
    if not raw:
        return DEFAULT_REMINDER_HOURS
    hours: list[float] = []
    for v in raw:
        try:
            h = float(v)
            if h > 0:
                hours.append(h)
        except (TypeError, ValueError):
            continue
    return hours or DEFAULT_REMINDER_HOURS


@shared_task(name="app.tasks.whatsapp.send_event_reminders")
def send_event_reminders() -> None:
    """
    Hourly Beat task - for each upcoming event, checks its configured reminder
    offsets (default 24h + 1h before start) and WhatsApps attendees who are
    within +/-1h of a due offset. Uses Redis dedup per (event, offset).
    """
    from app.models.event import Event
    from app.models.ticketing import Registration

    now = datetime.now(UTC)

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
                Event.start_datetime >= now,
                Event.start_datetime <= now + timedelta(days=_MAX_REMINDER_HORIZON_DAYS),
                Event.deleted_at.is_(None),
            )
            .all()
        )

        for event in events:
            hours_until = (event.start_datetime - now).total_seconds() / 3600
            due_offsets: list[float] = []

            # 24-hour countdown reminder
            if 22.0 <= hours_until <= 26.0:
                due_offsets.append(24.0)

            # 1-hour countdown reminder
            if 0.5 <= hours_until <= 1.5:
                due_offsets.append(1.0)

            # Custom configured offsets
            for h in _reminder_hours(event):
                if h not in (24.0, 1.0) and abs(hours_until - h) <= 0.75:
                    due_offsets.append(h)

            if not due_offsets:
                continue

            regs = (
                db.query(Registration)
                .filter(
                    Registration.event_id == event.id,
                    Registration.status == "confirmed",
                    Registration.attendee_phone.isnot(None),
                    Registration.whatsapp_consent.is_(True),
                )
                .all()
            )
            if not regs:
                continue

            for offset in due_offsets:
                sent_key = f"wa_reminder:{event.id}:{offset}"
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
                            hours_before=offset,
                        )
                        if redis:
                            redis.sadd(sent_key, rid)
                            redis.expire(sent_key, 48 * 3600)
                    except Exception as exc:
                        log.warning(
                            "whatsapp.reminder.failed", reg_id=rid, offset=offset, error=str(exc)
                        )


# ── Waitlist notification ─────────────────────────────────────────────────────


@shared_task(
    name="app.tasks.whatsapp.send_waitlist_notification", max_retries=3, default_retry_delay=60
)
def send_waitlist_notification(waitlist_id: str) -> None:
    from app.models.event import Event
    from app.models.ticketing import TicketType, Waitlist

    with _db() as db:
        wl = db.query(Waitlist).filter(Waitlist.id == uuid.UUID(waitlist_id)).first()
        if not wl:
            return
        if not wl.phone:
            log.info(
                "whatsapp.waitlist_notification.skipped",
                waitlist_id=waitlist_id,
                reason="no_phone",
            )
            return

        event = db.query(Event).filter(Event.id == wl.event_id).first()
        tt = db.query(TicketType).filter(TicketType.id == wl.ticket_type_id).first()

        wa.send_waitlist_notification_sync(
            phone=wl.phone,
            name=wl.name,
            event=event,
            ticket_type_name=tt.name if tt else "General",
            register_url=(
                f"{settings.FRONTEND_URL}/e/{event.slug}/register"
                if event
                else settings.FRONTEND_URL
            ),
        )


# ── Bot reply dispatcher ──────────────────────────────────────────────────────


@shared_task(name="app.tasks.whatsapp.handle_incoming_message")
def handle_incoming_message(from_phone: str, message_text: str) -> None:
    """
    Process an incoming WhatsApp message and send an appropriate reply.
    Dispatched from the webhook handler so the 200 response isn't blocked.
    """
    from app.models.community import WhatsAppMessage
    from app.models.event import Event
    from app.models.ticketing import Registration

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
                    to_number=settings.WHATSAPP_PHONE_NUMBER_ID or "tixdoo",
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
        _STOP_WORDS = {
            "STOP",
            "UNSUBSCRIBE",
            "OPTOUT",
            "OPT OUT",
            "OPT-OUT",
            "CANCEL",
            "END",
            "QUIT",
        }
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
            except Exception as err:
                db.rollback()
                log.warning(
                    "whatsapp.contact_unsubscribe_failed",
                    phone=from_phone[:6] + "****",
                    error=str(err),
                )
            # Persist in Redis so campaign sends can respect opt-out
            try:
                from redis import Redis as _Redis

                _r = _Redis.from_url(settings.REDIS_URL, decode_responses=True)
                _r.sadd("wa:optout", phone_norm or from_phone)
            except Exception as err:
                log.warning(
                    "whatsapp.redis_optout_failed", phone=from_phone[:6] + "****", error=str(err)
                )
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
            except Exception as err:
                db.rollback()
                log.warning(
                    "whatsapp.contact_resubscribe_failed",
                    phone=from_phone[:6] + "****",
                    error=str(err),
                )
            try:
                from redis import Redis as _Redis

                _r = _Redis.from_url(settings.REDIS_URL, decode_responses=True)
                _r.srem("wa:optout", phone_norm or from_phone)
            except Exception as err:
                log.warning(
                    "whatsapp.redis_optin_failed", phone=from_phone[:6] + "****", error=str(err)
                )
            wa.send_text_sync(from_phone, "You've been resubscribed to WhatsApp messages.")
            return

        if text in ("TICKET", "TICKETS", "MY TICKET", "STATUS"):
            phone_last10 = wa.format_phone(from_phone)
            phone_last10 = phone_last10[-10:] if phone_last10 else None

            if not phone_last10:
                wa.send_text_sync(
                    from_phone, "Could not look up your number. Visit tixdoo.com for help."
                )
                return

            from sqlalchemy.orm import joinedload

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
            events_map = (
                {e.id: e for e in db.query(EventModel).filter(EventModel.id.in_(event_ids)).all()}
                if event_ids
                else {}
            )

            for reg in regs:
                ev = events_map.get(reg.event_id)
                reg._event_title = ev.title if ev else "Event"

            reply = wa.build_ticket_status_reply(regs)
            wa.send_text_sync(from_phone, reply)

        else:
            reply = _structured_reply(db, from_phone, message_text)
            wa.send_text_sync(from_phone, reply)


# ── Structured keyword Q&A (v1: no NLP - see app/services/ai_service.py for
# the LLM-based responder, which exists but is intentionally not used here) ───

_LOCATION_KEYWORDS = ("where", "location", "venue", "address", "held")
_TIME_KEYWORDS = ("what time", "when", "start time", "starts")
_GUEST_KEYWORDS = ("guest", "plus one", "plus 1", "bring someone", "bring a friend")


def _most_recent_event_context(db, from_phone: str):
    """Return (registration, event) for the attendee's most recent confirmed ticket, or (None, None)."""
    from app.models.event import Event as EventModel
    from app.models.ticketing import Registration

    phone_norm = wa.format_phone(from_phone)
    phone_last10 = phone_norm[-10:] if phone_norm else None
    if not phone_last10:
        return None, None

    reg = (
        db.query(Registration)
        .filter(
            Registration.attendee_phone.like(f"%{phone_last10}"),
            Registration.status.in_(["confirmed", "checked_in"]),
        )
        .order_by(Registration.created_at.desc())
        .first()
    )
    if not reg:
        return None, None

    event = db.query(EventModel).filter(EventModel.id == reg.event_id).first()
    return reg, event


def _structured_reply(db, from_phone: str, message_text: str) -> str:
    """Keyword/menu-based Q&A for common attendee questions - no LLM involved."""
    text = message_text.strip().lower()

    reg, event = _most_recent_event_context(db, from_phone)
    if not event:
        return wa.HELP_TEXT

    if any(kw in text for kw in _LOCATION_KEYWORDS):
        return f"*{event.title}* is at:\nVenue: {wa.location_label(event)}"

    if any(kw in text for kw in _TIME_KEYWORDS):
        when = wa.date_label(event) or "Date/time TBA"
        return f"*{event.title}* starts:\nDate: {when}"

    if any(kw in text for kw in _GUEST_KEYWORDS):
        from app.models.ticketing import TicketType

        tt = (
            db.query(TicketType).filter(TicketType.id == reg.ticket_type_id).first()
            if reg
            else None
        )
        if tt and tt.max_per_order > 1:
            return (
                f"Group tickets are available for *{event.title}* - "
                "get your guest their own ticket at checkout so they're on the list too."
            )
        return (
            "Each attendee needs their own ticket to enter - "
            "please have your guest register separately."
        )

    return wa.HELP_TEXT
