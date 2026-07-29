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


# ── Registration confirmation ─────────────────────────────────────────────────

@shared_task(name="app.tasks.email.send_registration_confirmation", max_retries=3, default_retry_delay=60)
def send_registration_confirmation(order_id: str) -> None:
    """Send ticket confirmation with per-registration QR code URLs."""
    from app.models.event import Event
    from app.models.organization import Organization
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

        org = db.query(Organization).filter(Organization.id == event.org_id).first()
        org_name = org.name if org else "Heelo"

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
            org_name=org_name,
            registrations=confirmed_regs,
            gcal_url=em.gcal_url(event),
        )
        em.send_sync(
            to=order.buyer_email,
            subject=f"Your tickets for {event.title} ✓",
            html=html,
        )

    log.info("email.registration_confirmation.sent", order_id=order_id)


# ── Event reminder (24 h before event) ───────────────────────────────────────

@shared_task(name="app.tasks.email.send_event_reminders")
def send_event_reminders() -> None:
    """
    Scan for events starting in 23–25 hours and email confirmed attendees.
    Run this task hourly via Celery Beat.
    Tracks sent registrations in Redis to prevent duplicates.
    """
    from app.models.event import Event
    from app.models.organization import Organization
    from app.models.ticketing import Registration

    now = datetime.now(UTC)
    window_start = now + timedelta(hours=23)
    window_end = now + timedelta(hours=25)

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
                Event.start_datetime >= window_start,
                Event.start_datetime <= window_end,
                Event.deleted_at.is_(None),
            )
            .all()
        )

        for event in events:
            org = db.query(Organization).filter(Organization.id == event.org_id).first()
            org_name = org.name if org else "Heelo"
            sent_key = f"reminder:{event.id}"

            regs = (
                db.query(Registration)
                .filter(
                    Registration.event_id == event.id,
                    Registration.status == "confirmed",
                )
                .all()
            )

            for reg in regs:
                rid = str(reg.id)
                if redis and redis.sismember(sent_key, rid):
                    continue
                try:
                    html = em.render(
                        "event_reminder.html",
                        event=event,
                        org_name=org_name,
                        attendee_name=reg.attendee_name,
                        registration_id=rid,
                        gcal_url=em.gcal_url(event),
                    )
                    em.send_sync(
                        to=reg.attendee_email,
                        subject=f"Reminder: {event.title} is tomorrow!",
                        html=html,
                    )
                    if redis:
                        redis.sadd(sent_key, rid)
                        redis.expire(sent_key, 48 * 3600)
                except Exception as exc:
                    log.warning("email.reminder.failed", reg_id=rid, error=str(exc))

    log.info("email.event_reminders.done", events_scanned=len(events) if "events" in dir() else 0)


# ── Waitlist notification ─────────────────────────────────────────────────────

@shared_task(name="app.tasks.email.send_waitlist_notification", max_retries=3, default_retry_delay=60)
def send_waitlist_notification(waitlist_id: str) -> None:
    """Notify a waitlisted attendee that a spot became available."""
    from app.models.ticketing import Event, TicketType, Waitlist
    from app.models.organization import Organization

    with _db() as db:
        wl = db.query(Waitlist).filter(Waitlist.id == uuid.UUID(waitlist_id)).first()
        if not wl or wl.notified_at:
            return

        from app.models.event import Event as EventModel
        event = db.query(EventModel).filter(EventModel.id == wl.event_id).first()
        tt = db.query(TicketType).filter(TicketType.id == wl.ticket_type_id).first()
        org = (
            db.query(Organization).filter(Organization.id == event.org_id).first()
            if event else None
        )

        html = em.render(
            "waitlist_notification.html",
            event=event,
            ticket_type_name=tt.name if tt else "General",
            org_name=org.name if org else "Heelo",
            name=wl.name,
            register_url=(
                f"{settings.FRONTEND_URL}/e/{event.slug}/register"
                if event else settings.FRONTEND_URL
            ),
            offer_expires_at=wl.offer_expires_at,
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
            )
            em.send_sync(
                to=reg.attendee_email,
                subject=f"Update: {event.title} — details have changed",
                html=html,
            )

    log.info("email.event_update.sent", event_id=event_id, count=len(seen_emails))
