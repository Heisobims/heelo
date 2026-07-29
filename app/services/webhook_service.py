from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api import WebhookDelivery, WebhookSubscription

# Supported event types
WEBHOOK_EVENTS = [
    "registration.created",
    "registration.confirmed",
    "registration.cancelled",
    "checkin.completed",
    "order.paid",
    "event.published",
    "event.cancelled",
]


def sign_payload(secret: str, payload: dict) -> str:
    """Return `t=<ts>,v1=<hmac>` for X-Heelo-Signature header."""
    ts = str(int(time.time()))
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    msg = f"{ts}.{body}".encode()
    sig = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


async def create_subscription(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    url: str,
    events: list[str],
    description: str = "",
) -> WebhookSubscription:
    sub = WebhookSubscription(
        org_id=org_id,
        url=url,
        events=events,
        secret=secrets.token_hex(32),
        description=description or None,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


async def list_subscriptions(
    db: AsyncSession, org_id: uuid.UUID
) -> list[WebhookSubscription]:
    rows = await db.scalars(
        select(WebhookSubscription)
        .where(WebhookSubscription.org_id == org_id)
        .order_by(WebhookSubscription.created_at.desc())
    )
    return list(rows.all())


async def get_subscription(
    db: AsyncSession, sub_id: uuid.UUID, org_id: uuid.UUID
) -> WebhookSubscription | None:
    return await db.scalar(
        select(WebhookSubscription).where(
            WebhookSubscription.id == sub_id,
            WebhookSubscription.org_id == org_id,
        )
    )


async def update_subscription(
    db: AsyncSession,
    sub: WebhookSubscription,
    *,
    url: str | None = None,
    events: list[str] | None = None,
    description: str | None = None,
    is_active: bool | None = None,
) -> WebhookSubscription:
    if url is not None:
        sub.url = url
    if events is not None:
        sub.events = events
    if description is not None:
        sub.description = description
    if is_active is not None:
        sub.is_active = is_active
    await db.commit()
    await db.refresh(sub)
    return sub


async def delete_subscription(db: AsyncSession, sub: WebhookSubscription) -> None:
    await db.delete(sub)
    await db.commit()


async def get_deliveries(
    db: AsyncSession, sub_id: uuid.UUID, limit: int = 50
) -> list[WebhookDelivery]:
    rows = await db.scalars(
        select(WebhookDelivery)
        .where(WebhookDelivery.subscription_id == sub_id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(limit)
    )
    return list(rows.all())


async def fire_event(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    event_type: str,
    payload: dict,
) -> None:
    """
    Find active subscriptions for this org + event_type,
    create delivery records, and dispatch Celery tasks.
    """
    subs = await db.scalars(
        select(WebhookSubscription).where(
            WebhookSubscription.org_id == org_id,
            WebhookSubscription.is_active.is_(True),
        )
    )
    for sub in subs.all():
        if event_type not in (sub.events or []):
            continue
        delivery = WebhookDelivery(
            subscription_id=sub.id,
            event_type=event_type,
            payload=payload,
            status="pending",
        )
        db.add(delivery)
        await db.flush()  # get delivery.id before dispatching

        try:
            from app.tasks.webhooks import deliver_webhook
            deliver_webhook.delay(str(delivery.id))
        except Exception:
            # Celery unavailable — beat task will retry once next_retry_at passes
            delivery.next_retry_at = datetime.now(UTC) + timedelta(seconds=60)

    await db.commit()


def fire_event_sync(
    db,  # sync Session
    *,
    org_id: uuid.UUID,
    event_type: str,
    payload: dict,
) -> None:
    """Sync version for Celery tasks."""
    from app.models.api import WebhookSubscription as WS, WebhookDelivery as WD

    subs = (
        db.query(WS)
        .filter(WS.org_id == org_id, WS.is_active.is_(True))
        .all()
    )
    for sub in subs:
        if event_type not in (sub.events or []):
            continue
        delivery = WD(
            subscription_id=sub.id,
            event_type=event_type,
            payload=payload,
            status="pending",
        )
        db.add(delivery)
        db.flush()
        try:
            from app.tasks.webhooks import deliver_webhook
            deliver_webhook.delay(str(delivery.id))
        except Exception:
            delivery.next_retry_at = datetime.now(UTC) + timedelta(seconds=60)
    db.commit()
