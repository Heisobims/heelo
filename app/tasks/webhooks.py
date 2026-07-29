"""
Webhook delivery tasks.
Uses exponential backoff: 1 min, 5 min, 30 min, 2 h, 8 h (max 5 attempts).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

import httpx
import structlog
from celery import shared_task

from app.config import settings

log = structlog.get_logger()

_RETRY_DELAYS = [60, 300, 1800, 7200, 28800]  # seconds for attempts 1-5

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


def _sign(secret: str, payload: dict) -> str:
    ts = str(int(time.time()))
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    msg = f"{ts}.{body}".encode()
    sig = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


@shared_task(name="app.tasks.webhooks.deliver_webhook", max_retries=0)
def deliver_webhook(delivery_id: str) -> None:
    import uuid as _uuid
    from app.models.api import WebhookDelivery, WebhookSubscription

    with _db() as db:
        delivery = db.query(WebhookDelivery).filter(
            WebhookDelivery.id == _uuid.UUID(delivery_id)
        ).first()
        if not delivery:
            return

        sub = db.query(WebhookSubscription).filter(
            WebhookSubscription.id == delivery.subscription_id
        ).first()
        if not sub or not sub.is_active:
            delivery.status = "failed"
            db.commit()
            return

        payload = delivery.payload
        signature = _sign(sub.secret, payload)
        body = json.dumps(payload, separators=(",", ":"))

        attempt = (delivery.attempts or 0) + 1
        delivery.attempts = attempt
        status_code = None
        resp_body = ""

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    sub.url,
                    content=body.encode(),
                    headers={
                        "Content-Type": "application/json",
                        "X-Heelo-Signature": signature,
                        "X-Heelo-Event": delivery.event_type,
                        "User-Agent": "Heelo-Webhooks/1.0",
                    },
                )
            status_code = resp.status_code
            resp_body = resp.text[:2000]
            success = 200 <= status_code < 300
        except Exception as exc:
            success = False
            resp_body = str(exc)[:2000]

        now = datetime.now(UTC)
        delivery.response_status = status_code
        delivery.response_body = resp_body
        delivery.delivered_at = now

        if success:
            delivery.status = "success"
            delivery.next_retry_at = None
        elif attempt >= len(_RETRY_DELAYS) + 1:
            delivery.status = "exhausted"
            delivery.next_retry_at = None
            log.warning("webhook.exhausted", delivery_id=delivery_id, url=sub.url)
        else:
            delivery.status = "pending"
            delay = _RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)]
            delivery.next_retry_at = now + timedelta(seconds=delay)

        db.commit()
        log.info(
            "webhook.delivered",
            delivery_id=delivery_id,
            event_type=delivery.event_type,
            status=delivery.status,
            http_status=status_code,
            attempt=attempt,
        )


@shared_task(name="app.tasks.webhooks.retry_failed_webhooks")
def retry_failed_webhooks() -> None:
    """Beat task — retries pending deliveries whose next_retry_at has passed."""
    from app.models.api import WebhookDelivery

    now = datetime.now(UTC)
    with _db() as db:
        pending = (
            db.query(WebhookDelivery)
            .filter(
                WebhookDelivery.status == "pending",
                WebhookDelivery.next_retry_at.isnot(None),
                WebhookDelivery.next_retry_at <= now,
            )
            .limit(100)
            .all()
        )
        for d in pending:
            deliver_webhook.delay(str(d.id))
        log.info("webhook.retry_scan", found=len(pending))
