"""Platform-wide promotional email/notification sending — admin broadcasts."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import structlog
from celery import shared_task
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.services import email_service as em

log = structlog.get_logger()

_engine = None
_SyncSession = None


def _db() -> Session:
    global _engine, _SyncSession
    if _engine is None:
        _engine = create_engine(
            settings.DATABASE_URL_SYNC, pool_pre_ping=True, pool_size=2, max_overflow=4
        )
        _SyncSession = sessionmaker(bind=_engine)
    return _SyncSession()


_TAG_RE = re.compile(r"<[^>]+>")


def _plain_text(html: str, *, limit: int = 300) -> str:
    text = _TAG_RE.sub("", html).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


@shared_task(name="app.tasks.admin_broadcast.send_broadcast", max_retries=0)
def send_broadcast(broadcast_id: str) -> None:
    from app.models.notification import AdminBroadcast, Notification
    from app.models.user import User
    from app.models.vendor import Vendor
    from app.services.admin_broadcast_service import render_personalized

    with _db() as db:
        broadcast = (
            db.query(AdminBroadcast).filter(AdminBroadcast.id == uuid.UUID(broadcast_id)).first()
        )
        if not broadcast or broadcast.status not in ("draft", "failed"):
            return

        broadcast.status = "sending"
        db.commit()

        try:
            q = db.query(User).filter(User.deleted_at.is_(None))
            cat = broadcast.audience_category
            if cat == "organizer":
                q = q.filter(User.role.in_(["organizer", "both"]))
            elif cat == "attendee":
                q = q.filter(User.role.in_(["attendee", "both"]))
            elif cat == "admin":
                q = q.filter(User.role == "admin")
            elif cat == "vendor":
                q = q.join(Vendor, Vendor.user_id == User.id)
            recipients = q.all()

            channel = broadcast.channel or "email"
            sent = 0
            failed = 0
            for user in recipients:
                try:
                    html = render_personalized(broadcast.body, user)
                    if channel in ("email", "both"):
                        em.send_sync(to=user.email, subject=broadcast.subject, html=html)
                    if channel in ("notification", "both"):
                        db.add(
                            Notification(
                                id=uuid.uuid4(),
                                user_id=user.id,
                                type="admin_announcement",
                                title=broadcast.subject,
                                body=_plain_text(html),
                                icon="campaign",
                            )
                        )
                    sent += 1
                except Exception as exc:
                    failed += 1
                    log.warning("admin_broadcast.send_failed", user_id=str(user.id), error=str(exc))

            broadcast.sent_count = sent
            broadcast.failed_count = failed
            broadcast.recipient_count = len(recipients)
            broadcast.sent_at = datetime.now(UTC)
            broadcast.status = "sent" if sent > 0 or not recipients else "failed"
            db.commit()
        except Exception:
            # Per-recipient failures are tracked above and never reach here — this
            # only catches catastrophic failures. Without it, `status` would stay
            # stuck on "sending" forever since this task has max_retries=0.
            db.rollback()
            broadcast.status = "failed"
            db.commit()
            raise

    log.info("admin_broadcast.done", broadcast_id=broadcast_id, sent=sent, failed=failed)
