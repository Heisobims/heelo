"""
Celery email tasks — uses shared_task so the module is importable
without the Celery app instance being initialized first.

Synchronous SQLAlchemy (psycopg2) is used because Celery workers run
in separate processes and cannot share the FastAPI asyncpg pool.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from celery import shared_task
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.config import settings
from app.services import email_service as em

log = structlog.get_logger()

# One sync engine per worker process — lazy initialized to survive test imports.
_engine = None
_SyncSession = None


def _db() -> Session:
    global _engine, _SyncSession
    if _engine is None:
        _engine = create_engine(
            settings.DATABASE_URL_SYNC,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=4,
        )
        _SyncSession = sessionmaker(bind=_engine)
    return _SyncSession()


def _org_branding(db: Session, org_id) -> dict:
    """org_name/org_logo_url/brand_color kwargs for em.render() — every
    org/event-related email template reads these to theme its header and
    CTA buttons with the organizer's own branding instead of Heelo's."""
    from app.models.organization import Organization

    org = db.query(Organization).filter(Organization.id == org_id).first() if org_id else None
    return {
        "org_name": org.name if org else "Heelo",
        "org_logo_url": org.logo_url if org else None,
        "brand_color": org.brand_color if org else None,
    }


# ── Registration confirmation ─────────────────────────────────────────────────


@shared_task(
    name="app.tasks.email.send_registration_confirmation", max_retries=3, default_retry_delay=60
)
def send_registration_confirmation(order_id: str) -> None:
    """Send ticket confirmation with per-registration QR code URLs."""
    from app.models.event import Event
    from app.models.ticketing import Order, Registration

    with _db() as db:
        order = (
            db.query(Order)
            .options(joinedload(Order.registrations).joinedload(Registration.ticket_type))
            .filter(Order.id == uuid.UUID(order_id))
            .first()
        )
        if not order or order.payment_status != "paid":
            return

        event = db.query(Event).filter(Event.id == order.event_id).first()
        if not event:
            return

        branding = _org_branding(db, event.org_id)

        confirmed_regs = [
            {
                "registration_id": str(r.id),
                "attendee_name": r.attendee_name,
                "attendee_email": r.attendee_email,
                "ticket_type": r.ticket_type.name if r.ticket_type else "General",
            }
            for r in order.registrations
            if r.status in ("confirmed", "checked_in")
        ]
        if not confirmed_regs:
            return

        html = em.render(
            "registration_confirmation.html",
            order=order,
            event=event,
            registrations=confirmed_regs,
            gcal_url=em.gcal_url(event),
            first_registration_id=confirmed_regs[0]["registration_id"],
            **branding,
        )
        em.send_sync(
            to=order.buyer_email,
            subject=f"Your tickets for {event.title} ✓",
            html=html,
        )

    log.info("email.registration_confirmation.sent", order_id=order_id)


# ── Registration cancellation ─────────────────────────────────────────────────


@shared_task(
    name="app.tasks.email.send_registration_cancellation", max_retries=3, default_retry_delay=60
)
def send_registration_cancellation(registration_id: str, cancelled_by: str = "organizer") -> None:
    from app.models.event import Event
    from app.models.ticketing import Registration

    with _db() as db:
        reg = db.query(Registration).filter(Registration.id == uuid.UUID(registration_id)).first()
        if not reg:
            return

        event = db.query(Event).filter(Event.id == reg.event_id).first()
        if not event:
            return

        branding = _org_branding(db, event.org_id)

        html = em.render(
            "registration_cancelled.html",
            event=event,
            attendee_name=reg.attendee_name,
            ticket_type_name=reg.ticket_type.name if reg.ticket_type else "General",
            refunded=(reg.status == "refunded"),
            cancelled_by=cancelled_by,
            **branding,
        )
        em.send_sync(
            to=reg.attendee_email,
            subject=f"Your ticket for {event.title} has been cancelled",
            html=html,
        )

    log.info("email.registration_cancellation.sent", registration_id=registration_id)


# ── Event reminders (configurable intervals) ─────────────────────────────────

DEFAULT_REMINDER_HOURS = [24, 1]
_MAX_REMINDER_HORIZON_DAYS = 14  # events further out than this are never scanned


def _reminder_hours(event) -> list[float]:
    """Per-event configured reminder offsets, from Event.extras['email_reminder_hours']."""
    raw = (event.extras or {}).get("email_reminder_hours") if event.extras else None
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


def _reminder_headline(hours_before: float) -> str:
    if hours_before >= 12:
        return "is tomorrow!"
    if hours_before >= 2:
        return f"starts in about {round(hours_before)} hours!"
    return "starts soon!"


@shared_task(name="app.tasks.email.send_event_reminders")
def send_event_reminders() -> None:
    """
    Hourly Beat task — for each upcoming event, checks its configured reminder
    offsets (default 24h + 1h before start) and emails confirmed attendees who
    are within +/-1h of a due offset. Uses Redis dedup per (event, offset).
    """
    from app.models.event import Event
    from app.models.ticketing import Registration

    now = datetime.now(UTC)

    # Redis for dedup tracking
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
            due_offsets = [h for h in _reminder_hours(event) if abs(hours_until - h) <= 1]
            if not due_offsets:
                continue

            branding = _org_branding(db, event.org_id)

            regs = (
                db.query(Registration)
                .filter(
                    Registration.event_id == event.id,
                    Registration.status == "confirmed",
                )
                .all()
            )
            if not regs:
                continue

            for offset in due_offsets:
                sent_key = f"reminder:{event.id}:{offset}"
                headline = _reminder_headline(offset)
                for reg in regs:
                    rid = str(reg.id)
                    if redis and redis.sismember(sent_key, rid):
                        continue
                    try:
                        html = em.render(
                            "event_reminder.html",
                            event=event,
                            attendee_name=reg.attendee_name,
                            registration_id=rid,
                            gcal_url=em.gcal_url(event),
                            reminder_headline=headline,
                            **branding,
                        )
                        em.send_sync(
                            to=reg.attendee_email,
                            subject=f"Reminder: {event.title} {headline}",
                            html=html,
                        )
                        if redis:
                            redis.sadd(sent_key, rid)
                            redis.expire(sent_key, 48 * 3600)
                    except Exception as exc:
                        log.warning(
                            "email.reminder.failed", reg_id=rid, offset=offset, error=str(exc)
                        )

    log.info("email.event_reminders.done", events_scanned=len(events))


# ── Post-event feedback request ─────────────────────────────────────────────

_FEEDBACK_DELAY_HOURS = 3  # how long after an event ends before asking for feedback
_FEEDBACK_WINDOW_HOURS = 1  # tolerance around that delay, matching the hourly beat cadence


@shared_task(name="app.tasks.email.send_feedback_requests")
def send_feedback_requests() -> None:
    """
    Hourly Beat task — for events that ended ~3h ago, emails confirmed/checked-in
    attendees a link to rate the event. One-shot per event (not per offset, unlike
    reminders) — Redis dedup keyed per event so it never double-sends.
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
                Event.status.in_(["ended", "live", "published"]),
                Event.end_datetime <= now - timedelta(hours=_FEEDBACK_DELAY_HOURS),
                Event.end_datetime
                >= now - timedelta(hours=_FEEDBACK_DELAY_HOURS + _FEEDBACK_WINDOW_HOURS),
                Event.deleted_at.is_(None),
            )
            .all()
        )

        for event in events:
            sent_key = f"feedback_request:{event.id}"
            if redis and redis.get(sent_key):
                continue

            branding = _org_branding(db, event.org_id)

            regs = (
                db.query(Registration)
                .filter(
                    Registration.event_id == event.id,
                    Registration.status.in_(["confirmed", "checked_in"]),
                )
                .all()
            )
            for reg in regs:
                try:
                    html = em.render(
                        "feedback_request.html",
                        event=event,
                        attendee_name=reg.attendee_name,
                        registration_id=str(reg.id),
                        **branding,
                    )
                    em.send_sync(
                        to=reg.attendee_email,
                        subject=f"How was {event.title}?",
                        html=html,
                    )
                except Exception as exc:
                    log.warning(
                        "email.feedback_request.failed",
                        reg_id=str(reg.id),
                        event_id=str(event.id),
                        error=str(exc),
                    )

            if redis:
                redis.set(sent_key, "1", ex=7 * 24 * 3600)

    log.info("email.feedback_requests.done", events_scanned=len(events))


# ── Interest nudge ("save and remind") ────────────────────────────────────────

_INTEREST_NUDGE_HOURS = 48


@shared_task(name="app.tasks.email.send_interest_nudges")
def send_interest_nudges() -> None:
    """
    Hourly Beat task — nudges users who marked an event 'interested' but never
    bought a ticket, ~48h before it starts. One nudge per event, ever (Redis dedup).
    """
    from app.models.community import EventInterest
    from app.models.event import Event
    from app.models.ticketing import Registration
    from app.models.user import User

    now = datetime.now(UTC)
    window_start = now + timedelta(hours=_INTEREST_NUDGE_HOURS - 1)
    window_end = now + timedelta(hours=_INTEREST_NUDGE_HOURS + 1)

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
            branding = _org_branding(db, event.org_id)
            sent_key = f"interest_nudge:{event.id}"

            interests = db.query(EventInterest).filter(EventInterest.event_id == event.id).all()
            if not interests:
                continue

            # Anyone in this set already has a real ticket — don't nudge them to buy one.
            ticketed_user_ids = {
                r.user_id
                for r in db.query(Registration.user_id)
                .filter(
                    Registration.event_id == event.id,
                    Registration.status.in_(["confirmed", "checked_in"]),
                    Registration.user_id.isnot(None),
                )
                .all()
            }

            for interest in interests:
                uid = str(interest.user_id)
                if redis and redis.sismember(sent_key, uid):
                    continue
                if interest.user_id in ticketed_user_ids:
                    continue

                user = db.query(User).filter(User.id == interest.user_id).first()
                if not user or user.deleted_at is not None:
                    continue

                try:
                    html = em.render(
                        "interest_nudge.html",
                        event=event,
                        attendee_name=user.full_name,
                        gcal_url=em.gcal_url(event),
                        **branding,
                    )
                    em.send_sync(
                        to=user.email,
                        subject=f"{event.title} is coming up — grab your ticket",
                        html=html,
                    )
                    if redis:
                        redis.sadd(sent_key, uid)
                        redis.expire(sent_key, 7 * 24 * 3600)
                except Exception as exc:
                    log.warning("email.interest_nudge.failed", user_id=uid, error=str(exc))

    log.info("email.interest_nudges.done", events_scanned=len(events))


# ── Waitlist notification ─────────────────────────────────────────────────────


@shared_task(
    name="app.tasks.email.send_waitlist_notification", max_retries=3, default_retry_delay=60
)
def send_waitlist_notification(waitlist_id: str) -> None:
    """Notify a waitlisted attendee that a spot became available."""
    from app.models.ticketing import TicketType, Waitlist

    with _db() as db:
        wl = db.query(Waitlist).filter(Waitlist.id == uuid.UUID(waitlist_id)).first()
        if not wl or wl.notified_at:
            return

        from app.models.event import Event as EventModel

        event = db.query(EventModel).filter(EventModel.id == wl.event_id).first()
        tt = db.query(TicketType).filter(TicketType.id == wl.ticket_type_id).first()
        branding = _org_branding(db, event.org_id if event else None)

        html = em.render(
            "waitlist_notification.html",
            event=event,
            ticket_type_name=tt.name if tt else "General",
            name=wl.name,
            register_url=(
                f"{settings.FRONTEND_URL}/e/{event.slug}/register"
                if event
                else settings.FRONTEND_URL
            ),
            offer_expires_at=wl.offer_expires_at,
            **branding,
        )

        em.send_sync(
            to=wl.email,
            subject=f"A spot opened up for {event.title if event else 'the event'}!",
            html=html,
        )

        wl.notified_at = datetime.now(UTC)
        db.commit()

    log.info("email.waitlist_notification.sent", waitlist_id=waitlist_id)


# ── Event cancellation notification ──────────────────────────────────────────


@shared_task(name="app.tasks.email.send_event_cancellation", max_retries=3, default_retry_delay=60)
def send_event_cancellation(event_id: str, cancellation_note: str = "") -> None:
    """Email all confirmed attendees that the event has been cancelled."""
    from app.models.event import Event as EventModel
    from app.models.ticketing import Registration

    with _db() as db:
        event = db.query(EventModel).filter(EventModel.id == uuid.UUID(event_id)).first()
        if not event:
            return

        branding = _org_branding(db, event.org_id)

        regs = (
            db.query(Registration)
            .filter(
                Registration.event_id == event.id,
                Registration.status.in_(["confirmed", "checked_in"]),
            )
            .all()
        )

        seen_emails: set[str] = set()
        for reg in regs:
            if reg.attendee_email in seen_emails:
                continue
            seen_emails.add(reg.attendee_email)
            html = em.render(
                "event_cancelled.html",
                event=event,
                attendee_name=reg.attendee_name,
                cancellation_note=cancellation_note,
                **branding,
            )
            em.send_sync(
                to=reg.attendee_email,
                subject=f"Cancelled: {event.title}",
                html=html,
            )

    log.info("email.event_cancellation.sent", event_id=event_id, count=len(seen_emails))


# ── Event update notification ─────────────────────────────────────────────────


@shared_task(name="app.tasks.email.send_event_update", max_retries=3, default_retry_delay=60)
def send_event_update(event_id: str, changes: list[dict]) -> None:
    """Email confirmed attendees when key event details change (date/venue)."""
    from app.models.event import Event as EventModel
    from app.models.ticketing import Registration

    if not changes:
        return

    with _db() as db:
        event = db.query(EventModel).filter(EventModel.id == uuid.UUID(event_id)).first()
        if not event:
            return

        branding = _org_branding(db, event.org_id)

        regs = (
            db.query(Registration)
            .filter(
                Registration.event_id == event.id,
                Registration.status.in_(["confirmed", "checked_in"]),
            )
            .all()
        )

        seen_emails: set[str] = set()
        for reg in regs:
            if reg.attendee_email in seen_emails:
                continue
            seen_emails.add(reg.attendee_email)
            html = em.render(
                "event_updated.html",
                event=event,
                attendee_name=reg.attendee_name,
                changes=changes,
                **branding,
            )
            em.send_sync(
                to=reg.attendee_email,
                subject=f"Update: {event.title} — details have changed",
                html=html,
            )

    log.info("email.event_update.sent", event_id=event_id, count=len(seen_emails))
