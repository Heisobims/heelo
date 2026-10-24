"""
Celery email tasks - uses shared_task so the module is importable
without the Celery app instance being initialized first.

Synchronous SQLAlchemy (psycopg2) is used because Celery workers run
in separate processes and cannot share the FastAPI asyncpg pool.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus

import structlog
from celery import shared_task
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.config import settings
from app.services import email_service as em

log = structlog.get_logger()

# One sync engine per worker process - lazy initialized to survive test imports.
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
    """org_name/org_logo_url/brand_color kwargs for em.render() - every
    org/event-related email template reads these to theme its header and
    CTA buttons with the organizer's own branding instead of Heelo's.

    Custom branding (logo + brand color) is a Growth+ feature - Free-tier
    orgs get Heelo's own black/cyan look and a "Powered by Heelo" footer
    line; Enterprise additionally drops that footer line (full white-label).
    """
    from app.models.organization import Organization
    from app.plans import PlanFeature, has_feature

    org = db.query(Organization).filter(Organization.id == org_id).first() if org_id else None
    plan = org.plan if org else "free"
    branded = has_feature(plan, PlanFeature.CUSTOM_BRANDING)
    return {
        "org_name": org.name if org else "Heelo",
        "org_logo_url": (org.logo_url if org else None) if branded else None,
        "brand_color": (org.brand_color if org else None) if branded else None,
        "show_powered_by": not has_feature(plan, PlanFeature.FULL_WHITE_LABEL),
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
            subject=f"Your tickets for {event.title}",
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


# ── Ticket transfer ────────────────────────────────────────────────────────────


@shared_task(
    name="app.tasks.email.send_ticket_transfer_confirmation",
    max_retries=3,
    default_retry_delay=60,
)
def send_ticket_transfer_confirmation(registration_id: str) -> None:
    """Sent to the *new* holder of a transferred ticket - deliberately its
    own task rather than reusing send_registration_confirmation, which sends
    one combined email per *order* (every registration on it) to the
    original buyer. A transfer needs a single-registration email sent to
    whoever just claimed it, same shape as the cancellation email."""
    from app.models.event import Event
    from app.models.ticketing import Order, Registration

    with _db() as db:
        reg = db.query(Registration).filter(Registration.id == uuid.UUID(registration_id)).first()
        if not reg or reg.status not in ("confirmed", "checked_in"):
            return

        event = db.query(Event).filter(Event.id == reg.event_id).first()
        if not event:
            return

        order = db.query(Order).filter(Order.id == reg.order_id).first() if reg.order_id else None
        branding = _org_branding(db, event.org_id)

        confirmed_regs = [
            {
                "registration_id": str(reg.id),
                "attendee_name": reg.attendee_name,
                "attendee_email": reg.attendee_email,
                "ticket_type": reg.ticket_type.name if reg.ticket_type else "General",
            }
        ]

        html = em.render(
            "registration_confirmation.html",
            order=order,
            event=event,
            registrations=confirmed_regs,
            gcal_url=em.gcal_url(event),
            first_registration_id=str(reg.id),
            **branding,
        )
        em.send_sync(
            to=reg.attendee_email,
            subject=f"You've received a ticket for {event.title}",
            html=html,
        )

    log.info("email.ticket_transfer_confirmation.sent", registration_id=registration_id)


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
    Hourly Beat task - for each upcoming event, checks its configured reminder
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
            due_offsets: list[float] = []

            # 24-hour countdown reminder
            if 22.0 <= hours_until <= 26.0 and not event.reminder_24h_sent_at:
                due_offsets.append(24.0)

            # 1-hour countdown reminder
            if 0.5 <= hours_until <= 1.5 and not event.reminder_1h_sent_at:
                due_offsets.append(1.0)

            # Custom configured offsets
            for h in _reminder_hours(event):
                if h not in (24.0, 1.0) and abs(hours_until - h) <= 0.75:
                    due_offsets.append(h)

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

            venue_parts = [event.venue_name, event.venue_address, event.venue_city]
            venue_query = " ".join([p for p in venue_parts if p])
            venue_directions_url = (
                f"https://www.google.com/maps/search/?api=1&query={quote_plus(venue_query)}"
                if venue_query
                else None
            )

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
                            venue_directions_url=venue_directions_url,
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

                if offset == 24.0:
                    event.reminder_24h_sent_at = now
                elif offset == 1.0:
                    event.reminder_1h_sent_at = now

            db.commit()

    log.info("email.event_reminders.done", events_scanned=len(events))


# ── Post-event feedback request ─────────────────────────────────────────────

_FEEDBACK_DELAY_HOURS = 3  # how long after an event ends before asking for feedback
_FEEDBACK_WINDOW_HOURS = 1  # tolerance around that delay, matching the hourly beat cadence


@shared_task(name="app.tasks.email.send_feedback_requests")
def send_feedback_requests() -> None:
    """
    Hourly Beat task - for events that ended ~3h ago, emails confirmed/checked-in
    attendees a link to rate the event. One-shot per event (not per offset, unlike
    reminders) - Redis dedup keyed per event so it never double-sends.
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
    Hourly Beat task - nudges users who marked an event 'interested' but never
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

            # Anyone in this set already has a real ticket - don't nudge them to buy one.
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
                        subject=f"{event.title} is coming up - grab your ticket",
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
                subject=f"Update: {event.title} - details have changed",
                html=html,
            )

    log.info("email.event_update.sent", event_id=event_id, count=len(seen_emails))


# ── Plan billing ─────────────────────────────────────────────────────────────
#
# These go to the org OWNER's account email, not org.contact_email (which is
# public-facing, shown in campaign footers) - billing notices are an account
# matter. Sent with no org-branding overrides (Heelo's own black/cyan look),
# since these are emails from Heelo about the org's own subscription, not
# organizer-branded attendee-facing mail.


def _org_owner_email(db: Session, org) -> str | None:
    from app.models.user import User

    owner = db.query(User).filter(User.id == org.owner_id).first()
    return owner.email if owner else None


@shared_task(
    name="app.tasks.email.send_plan_renewal_reminder", max_retries=3, default_retry_delay=60
)
def send_plan_renewal_reminder(org_id: str) -> None:
    from app.models.organization import Organization

    with _db() as db:
        org = db.query(Organization).filter(Organization.id == uuid.UUID(org_id)).first()
        if not org or not org.plan_expires_at:
            return
        to = _org_owner_email(db, org)
        if not to:
            return

        html = em.render(
            "plan_renewal_reminder.html",
            org_display_name=org.name,
            org_slug=org.slug,
            plan=org.plan,
            expires_date=org.plan_expires_at.strftime("%B %d, %Y"),
        )
        em.send_sync(
            to=to, subject=f"Your Heelo {org.plan.capitalize()} plan renews soon", html=html
        )

    log.info("email.plan_renewal_reminder.sent", org_id=org_id)


@shared_task(name="app.tasks.email.send_plan_downgraded", max_retries=3, default_retry_delay=60)
def send_plan_downgraded(org_id: str, previous_plan: str = "growth") -> None:
    from app.models.organization import Organization

    with _db() as db:
        org = db.query(Organization).filter(Organization.id == uuid.UUID(org_id)).first()
        if not org:
            return
        to = _org_owner_email(db, org)
        if not to:
            return

        html = em.render(
            "plan_downgraded.html",
            org_display_name=org.name,
            org_slug=org.slug,
            previous_plan=previous_plan,
        )
        em.send_sync(to=to, subject=f"{org.name} has moved to the Free plan", html=html)

    log.info("email.plan_downgraded.sent", org_id=org_id)


@shared_task(name="app.tasks.email.send_plan_receipt", max_retries=3, default_retry_delay=60)
def send_plan_receipt(invoice_id: str) -> None:
    from app.models.organization import Organization
    from app.models.payment import PlanInvoice

    with _db() as db:
        invoice = db.query(PlanInvoice).filter(PlanInvoice.id == uuid.UUID(invoice_id)).first()
        if not invoice or invoice.status != "paid":
            return
        org = db.query(Organization).filter(Organization.id == invoice.org_id).first()
        if not org:
            return
        to = _org_owner_email(db, org)
        if not to:
            return

        list_price = float(invoice.amount) - float(invoice.gateway_fee_amount or 0)
        html = em.render(
            "plan_receipt.html",
            org_display_name=org.name,
            org_slug=org.slug,
            plan=invoice.plan,
            amount=f"{invoice.amount:,.2f}",
            list_price=f"{list_price:,.2f}",
            gateway_fee_amount=f"{invoice.gateway_fee_amount:,.2f}",
            currency=invoice.currency,
            period_end_date=(
                org.plan_expires_at.strftime("%B %d, %Y") if org.plan_expires_at else "-"
            ),
        )
        em.send_sync(to=to, subject=f"Receipt: Heelo {invoice.plan.capitalize()} plan", html=html)

    log.info("email.plan_receipt.sent", invoice_id=invoice_id)


@shared_task(
    name="app.tasks.email.send_vendor_lead_notification", max_retries=3, default_retry_delay=60
)
def send_vendor_lead_notification(lead_id: str) -> None:
    """Notify a vendor of a new enquiry. Dispatched via .delay() from the
    public, unauthenticated /vendors/{slug}/contact endpoint so a slow/down
    SMTP provider can't block that request."""
    from app.models.vendor import Vendor, VendorLead

    with _db() as db:
        lead = db.query(VendorLead).filter(VendorLead.id == uuid.UUID(lead_id)).first()
        if not lead:
            return
        vendor = db.query(Vendor).filter(Vendor.id == lead.vendor_id).first()
        if not vendor:
            return
        to = vendor.contact_email or vendor.user.email
        if not to:
            return

        html = em.render(
            "vendor_lead.html",
            business_name=vendor.business_name,
            requester_name=lead.requester_name,
            event_name=lead.event_name,
            message=lead.message,
        )
        em.send_sync(to=to, subject=f"New enquiry for {vendor.business_name}", html=html)

    log.info("email.vendor_lead_notification.sent", lead_id=lead_id)


@shared_task(
    name="app.tasks.email.send_booth_application_submitted", max_retries=3, default_retry_delay=60
)
def send_booth_application_submitted(application_id: str) -> None:
    from app.models.event import Event
    from app.models.vendor import BoothApplication

    with _db() as db:
        app = db.query(BoothApplication).filter(BoothApplication.id == uuid.UUID(application_id)).first()
        if not app:
            return
        event = db.query(Event).filter(Event.id == app.event_id).first()
        if not event:
            return

        branding = _org_branding(db, event.org_id)
        pkg_name = app.package.name if app.package else None

        html = em.render(
            "booth_application_submitted.html",
            event=event,
            contact_name=app.contact_name,
            business_name=app.business_name,
            package_name=pkg_name,
            price=float(app.price),
            currency=app.currency,
            **branding,
        )
        em.send_sync(
            to=app.contact_email,
            subject=f"Booth Application Received: {event.title}",
            html=html,
        )

    log.info("email.booth_application_submitted.sent", application_id=application_id)


@shared_task(
    name="app.tasks.email.send_booth_application_approved", max_retries=3, default_retry_delay=60
)
def send_booth_application_approved(application_id: str) -> None:
    from app.models.event import Event
    from app.models.vendor import BoothApplication

    with _db() as db:
        app = db.query(BoothApplication).filter(BoothApplication.id == uuid.UUID(application_id)).first()
        if not app:
            return
        event = db.query(Event).filter(Event.id == app.event_id).first()
        if not event:
            return

        branding = _org_branding(db, event.org_id)
        pkg_name = app.package.name if app.package else None
        payment_url = app.invoice_url or f"{settings.FRONTEND_URL}/booths/{app.id}/pay"

        html = em.render(
            "booth_application_approved.html",
            event=event,
            contact_name=app.contact_name,
            business_name=app.business_name,
            package_name=pkg_name,
            assigned_booth_number=app.assigned_booth_number,
            price=float(app.price),
            currency=app.currency,
            payment_url=payment_url,
            **branding,
        )
        em.send_sync(
            to=app.contact_email,
            subject=f"Action Required: Your Booth Application for {event.title} is Approved!",
            html=html,
        )

    log.info("email.booth_application_approved.sent", application_id=application_id)


@shared_task(
    name="app.tasks.email.send_booth_application_confirmed", max_retries=3, default_retry_delay=60
)
def send_booth_application_confirmed(application_id: str) -> None:
    from app.models.event import Event
    from app.models.vendor import BoothApplication

    with _db() as db:
        app = db.query(BoothApplication).filter(BoothApplication.id == uuid.UUID(application_id)).first()
        if not app:
            return
        event = db.query(Event).filter(Event.id == app.event_id).first()
        if not event:
            return

        branding = _org_branding(db, event.org_id)
        pkg_name = app.package.name if app.package else None

        html = em.render(
            "booth_application_confirmed.html",
            event=event,
            contact_name=app.contact_name,
            business_name=app.business_name,
            package_name=pkg_name,
            assigned_booth_number=app.assigned_booth_number,
            price=float(app.price),
            currency=app.currency,
            payment_reference=app.payment_reference,
            **branding,
        )
        em.send_sync(
            to=app.contact_email,
            subject=f"Receipt & Confirmation: Booth Confirmed for {event.title}!",
            html=html,
        )

    log.info("email.booth_application_confirmed.sent", application_id=application_id)


# ── Vendor Marketplace Email Notifications ─────────────────────────────────────


@shared_task(
    name="app.tasks.email.send_vendor_quote_request_notification",
    max_retries=3,
    default_retry_delay=60,
)
def send_vendor_quote_request_notification(quote_request_id: str) -> None:
    from app.models.vendor import Vendor, VendorQuoteRecipient, VendorQuoteRequest

    with _db() as db:
        req = db.query(VendorQuoteRequest).filter(VendorQuoteRequest.id == uuid.UUID(quote_request_id)).first()
        if not req:
            return

        recipients = db.query(VendorQuoteRecipient).filter(VendorQuoteRecipient.request_id == req.id).all()
        requester_name = req.requester.full_name or "An Organizer"
        event_date_str = req.event_date.strftime("%B %d, %Y") if req.event_date else None

        vendor_names = []
        for rcp in recipients:
            vendor = db.query(Vendor).filter(Vendor.id == rcp.vendor_id).first()
            if not vendor:
                continue
            vendor_names.append(vendor.business_name)
            to_email = vendor.contact_email or (vendor.user.email if vendor.user else None)
            if not to_email:
                continue

            html = em.render(
                "vendor_quote_request.html",
                business_name=vendor.business_name,
                requester_name=requester_name,
                event_name=req.event_name,
                event_date=event_date_str,
                event_location=req.event_location,
                expected_attendance=req.expected_attendance,
                budget_min=float(req.budget_min) if req.budget_min else None,
                budget_max=float(req.budget_max) if req.budget_max else None,
                currency=req.currency or "NGN",
                requirements=req.requirements,
                frontend_url=settings.FRONTEND_URL,
                dashboard_url=f"{settings.FRONTEND_URL}/my-vendor-dashboard?tab=inquiries",
            )
            try:
                em.send_sync(
                    to=to_email,
                    subject=f"New Quote Request: {req.event_name} on Heelo",
                    html=html,
                )
            except Exception as exc:
                log.warning("email.vendor_quote_request.failed", vendor_id=str(vendor.id), error=str(exc))

        # Send confirmation email to requester / organizer
        if req.requester and req.requester.email:
            try:
                org_html = em.render(
                    "organizer_quote_request_submitted.html",
                    requester_name=requester_name,
                    event_name=req.event_name,
                    service_category=req.service_category,
                    event_date=event_date_str,
                    vendor_count=len(recipients),
                    vendors_list=", ".join(vendor_names) if vendor_names else "Requested vendors",
                    frontend_url=settings.FRONTEND_URL,
                )
                em.send_sync(
                    to=req.requester.email,
                    subject=f"Quote Request Dispatched: {req.event_name}",
                    html=org_html,
                )
            except Exception as exc:
                log.warning("email.organizer_quote_request.failed", error=str(exc))

    log.info("email.vendor_quote_request.sent", quote_request_id=quote_request_id)


@shared_task(
    name="app.tasks.email.send_vendor_quotation_submitted_notification",
    max_retries=3,
    default_retry_delay=60,
)
def send_vendor_quotation_submitted_notification(quotation_id: str) -> None:
    from app.models.vendor import Vendor, VendorQuotation, VendorQuoteRequest

    with _db() as db:
        quotation = db.query(VendorQuotation).filter(VendorQuotation.id == uuid.UUID(quotation_id)).first()
        if not quotation or not quotation.requester or not quotation.requester.email:
            return

        vendor = db.query(Vendor).filter(Vendor.id == quotation.vendor_id).first()
        if not vendor:
            return

        req = db.query(VendorQuoteRequest).filter(VendorQuoteRequest.id == quotation.quote_request_id).first() if quotation.quote_request_id else None
        event_name = req.event_name if req else "your upcoming event"
        valid_until_str = quotation.valid_until.strftime("%B %d, %Y") if quotation.valid_until else None

        html = em.render(
            "vendor_quotation_submitted.html",
            requester_name=quotation.requester.full_name or "Organizer",
            vendor_name=vendor.business_name,
            vendor_slug=vendor.slug,
            event_name=event_name,
            quotation_title=quotation.title,
            total_amount=float(quotation.total_amount),
            currency=quotation.currency or "NGN",
            valid_until=valid_until_str,
            scope_of_work=quotation.scope_of_work,
            attachment_url=quotation.attachment_url,
            attachment_name=quotation.attachment_name,
            frontend_url=settings.FRONTEND_URL,
            booking_url=f"{settings.FRONTEND_URL}/vendors/{vendor.slug}",
        )
        em.send_sync(
            to=quotation.requester.email,
            subject=f"Quotation Received from {vendor.business_name} for {event_name}",
            html=html,
        )

    log.info("email.vendor_quotation_submitted.sent", quotation_id=quotation_id)


@shared_task(
    name="app.tasks.email.send_vendor_booking_confirmed_notification",
    max_retries=3,
    default_retry_delay=60,
)
def send_vendor_booking_confirmed_notification(booking_id: str) -> None:
    from app.models.vendor import Vendor, VendorBooking

    with _db() as db:
        booking = db.query(VendorBooking).filter(VendorBooking.id == uuid.UUID(booking_id)).first()
        if not booking:
            return

        vendor = db.query(Vendor).filter(Vendor.id == booking.vendor_id).first()
        if not vendor:
            return

        event_date_str = booking.event_date.strftime("%B %d, %Y") if booking.event_date else None
        client_name = booking.requester.full_name if booking.requester else "Client"
        client_email = booking.requester.email if booking.requester else ""
        client_phone = booking.requester.whatsapp_number if booking.requester else None

        # 1. Email to Vendor
        vendor_email = vendor.contact_email or (vendor.user.email if vendor.user else None)
        if vendor_email:
            try:
                vendor_html = em.render(
                    "vendor_booking_confirmed.html",
                    business_name=vendor.business_name,
                    booking_reference=booking.booking_reference,
                    event_name=booking.event_name or "Private Event",
                    event_date=event_date_str,
                    event_location=booking.event_location,
                    client_name=client_name,
                    client_email=client_email,
                    client_phone=client_phone,
                    total_amount=float(booking.total_amount),
                    commission_rate=float(booking.platform_commission_rate),
                    commission_amount=float(booking.commission_amount),
                    vendor_earnings=float(booking.vendor_earnings),
                    currency=booking.currency or "NGN",
                    frontend_url=settings.FRONTEND_URL,
                )
                em.send_sync(
                    to=vendor_email,
                    subject=f"New Confirmed Booking: {booking.event_name} (Ref: {booking.booking_reference})",
                    html=vendor_html,
                )
            except Exception as exc:
                log.warning("email.vendor_booking_confirmed.vendor_failed", error=str(exc))

        # 2. Email to Organizer / Requester
        if client_email:
            try:
                org_html = em.render(
                    "organizer_booking_confirmed.html",
                    requester_name=client_name,
                    vendor_name=vendor.business_name,
                    vendor_slug=vendor.slug,
                    booking_reference=booking.booking_reference,
                    event_name=booking.event_name or "Private Event",
                    event_date=event_date_str,
                    event_location=booking.event_location,
                    total_amount=float(booking.total_amount),
                    currency=booking.currency or "NGN",
                    payment_reference=booking.payment_reference or booking.booking_reference,
                    frontend_url=settings.FRONTEND_URL,
                )
                em.send_sync(
                    to=client_email,
                    subject=f"Booking Confirmed: {vendor.business_name} for {booking.event_name}",
                    html=org_html,
                )
            except Exception as exc:
                log.warning("email.vendor_booking_confirmed.organizer_failed", error=str(exc))

    log.info("email.vendor_booking_confirmed.sent", booking_id=booking_id)


@shared_task(
    name="app.tasks.email.send_vendor_booking_completed_notification",
    max_retries=3,
    default_retry_delay=60,
)
def send_vendor_booking_completed_notification(booking_id: str) -> None:
    from app.models.vendor import Vendor, VendorBooking

    with _db() as db:
        booking = db.query(VendorBooking).filter(VendorBooking.id == uuid.UUID(booking_id)).first()
        if not booking:
            return

        vendor = db.query(Vendor).filter(Vendor.id == booking.vendor_id).first()
        if not vendor:
            return

        client_name = booking.requester.full_name if booking.requester else "Organizer"
        client_email = booking.requester.email if booking.requester else None
        vendor_email = vendor.contact_email or (vendor.user.email if vendor.user else None)

        # 1. Email to Vendor (earnings credited)
        if vendor_email:
            try:
                vendor_html = em.render(
                    "vendor_booking_completed.html",
                    business_name=vendor.business_name,
                    booking_reference=booking.booking_reference,
                    event_name=booking.event_name or "Private Event",
                    vendor_earnings=float(booking.vendor_earnings),
                    payable_balance=float(vendor.payable_balance),
                    currency=booking.currency or "NGN",
                    frontend_url=settings.FRONTEND_URL,
                )
                em.send_sync(
                    to=vendor_email,
                    subject=f"Booking Completed & Earnings Credited: Ref {booking.booking_reference}",
                    html=vendor_html,
                )
            except Exception as exc:
                log.warning("email.vendor_booking_completed.vendor_failed", error=str(exc))

        # 2. Email to Organizer (invite review)
        if client_email:
            try:
                org_html = em.render(
                    "organizer_booking_completed.html",
                    requester_name=client_name,
                    vendor_name=vendor.business_name,
                    vendor_slug=vendor.slug,
                    booking_reference=booking.booking_reference,
                    event_name=booking.event_name or "Private Event",
                    frontend_url=settings.FRONTEND_URL,
                )
                em.send_sync(
                    to=client_email,
                    subject=f"Service Completed: How was your experience with {vendor.business_name}?",
                    html=org_html,
                )
            except Exception as exc:
                log.warning("email.vendor_booking_completed.organizer_failed", error=str(exc))

    log.info("email.vendor_booking_completed.sent", booking_id=booking_id)


@shared_task(
    name="app.tasks.email.send_vendor_fulfillment_submitted_notification",
    max_retries=3,
    default_retry_delay=60,
)
def send_vendor_fulfillment_submitted_notification(booking_id: str) -> None:
    from app.models.vendor import Vendor, VendorBooking

    with _db() as db:
        booking = db.query(VendorBooking).filter(VendorBooking.id == uuid.UUID(booking_id)).first()
        if not booking:
            return

        vendor = db.query(Vendor).filter(Vendor.id == booking.vendor_id).first()
        if not vendor:
            return

        client_name = booking.requester.full_name if booking.requester else "Organizer"
        client_email = booking.requester.email if booking.requester else None

        if client_email:
            try:
                html = em.render(
                    "vendor_fulfillment_submitted.html",
                    client_name=client_name,
                    business_name=vendor.business_name,
                    booking_reference=booking.booking_reference,
                    event_name=booking.event_name or "Private Event",
                    total_amount=float(booking.total_amount),
                    currency=booking.currency or "NGN",
                    proof_notes=booking.fulfillment_proof_notes,
                    frontend_url=settings.FRONTEND_URL,
                )
                em.send_sync(
                    to=client_email,
                    subject=f"Action Required: Service Delivered for {booking.event_name or 'Your Event'} (Ref {booking.booking_reference})",
                    html=html,
                )
            except Exception as exc:
                log.warning("email.vendor_fulfillment_submitted.failed", error=str(exc))

    log.info("email.vendor_fulfillment_submitted.sent", booking_id=booking_id)


@shared_task(
    name="app.tasks.email.send_vendor_payout_requested_notification",
    max_retries=3,
    default_retry_delay=60,
)
def send_vendor_payout_requested_notification(payout_id: str) -> None:
    from app.models.vendor import Vendor, VendorPayout

    with _db() as db:
        payout = db.query(VendorPayout).filter(VendorPayout.id == uuid.UUID(payout_id)).first()
        if not payout:
            return

        vendor = db.query(Vendor).filter(Vendor.id == payout.vendor_id).first()
        if not vendor:
            return

        to_email = vendor.contact_email or (vendor.user.email if vendor.user else None)
        if not to_email:
            return

        acc = payout.account_details or {}
        html = em.render(
            "vendor_payout_requested.html",
            business_name=vendor.business_name,
            amount=float(payout.amount),
            currency=payout.currency or "NGN",
            bank_name=acc.get("bank_name", "Bank"),
            account_number=acc.get("account_number", ""),
            account_name=acc.get("account_name", ""),
            frontend_url=settings.FRONTEND_URL,
        )
        em.send_sync(
            to=to_email,
            subject=f"Withdrawal Request Received: ₦{float(payout.amount):,.2f}",
            html=html,
        )

    log.info("email.vendor_payout_requested.sent", payout_id=payout_id)


@shared_task(
    name="app.tasks.email.send_vendor_payout_completed_notification",
    max_retries=3,
    default_retry_delay=60,
)
def send_vendor_payout_completed_notification(payout_id: str) -> None:
    from app.models.vendor import Vendor, VendorPayout

    with _db() as db:
        payout = db.query(VendorPayout).filter(VendorPayout.id == uuid.UUID(payout_id)).first()
        if not payout:
            return

        vendor = db.query(Vendor).filter(Vendor.id == payout.vendor_id).first()
        if not vendor:
            return

        to_email = vendor.contact_email or (vendor.user.email if vendor.user else None)
        if not to_email:
            return

        acc = payout.account_details or {}
        html = em.render(
            "vendor_payout_completed.html",
            business_name=vendor.business_name,
            amount=float(payout.amount),
            currency=payout.currency or "NGN",
            bank_name=acc.get("bank_name", "Bank"),
            account_number=acc.get("account_number", ""),
            provider_reference=payout.provider_reference or payout.transfer_code or "",
            frontend_url=settings.FRONTEND_URL,
        )
        em.send_sync(
            to=to_email,
            subject=f"Payout Disbursed: ₦{float(payout.amount):,.2f} Sent to Your Bank",
            html=html,
        )

    log.info("email.vendor_payout_completed.sent", payout_id=payout_id)


# ── Abandoned checkout recovery ───────────────────────────────────────────────


@shared_task(
    name="app.tasks.email.send_abandoned_checkout_recovery",
    max_retries=3,
    default_retry_delay=60,
)
def send_abandoned_checkout_recovery(order_id: str) -> None:
    """Send abandoned checkout recovery email with 1-click resumption URL."""
    from app.models.event import Event
    from app.models.ticketing import Order

    with _db() as db:
        order = db.query(Order).filter(Order.id == uuid.UUID(order_id)).first()
        if not order or order.payment_status != "pending" or not order.buyer_email:
            return

        event = db.query(Event).filter(Event.id == order.event_id).first()
        if not event or event.status not in ("published", "live"):
            return

        branding = _org_branding(db, event.org_id)
        resume_url = (
            f"{settings.FRONTEND_URL}/orders/resume/{order.recovery_token}"
            if order.recovery_token
            else f"{settings.FRONTEND_URL}/orders/{order.id}/confirmation"
        )

        html = em.render(
            "abandoned_checkout_recovery.html",
            order=order,
            event=event,
            resume_url=resume_url,
            **branding,
        )
        em.send_sync(
            to=order.buyer_email,
            subject=f"Did life get in the way? Your tickets to {event.title} are waiting",
            html=html,
        )

    log.info("email.abandoned_checkout_recovery.sent", order_id=order_id)



