from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, HttpUrl

from app.dependencies import DBSession, OrgAccess
from app.services import webhook_service as wh_svc

router_webhooks_api = APIRouter(
    prefix="/api/v1/organizations/{slug}/webhooks",
    tags=["webhooks"],
)


class SubscriptionIn(BaseModel):
    url: str = Field(..., max_length=2000)
    events: list[str] = Field(..., min_length=1)
    description: str = Field("", max_length=500)


class SubscriptionUpdate(BaseModel):
    url: str | None = Field(None, max_length=2000)
    events: list[str] | None = None
    description: str | None = Field(None, max_length=500)
    is_active: bool | None = None


def _sub_dict(sub) -> dict:
    return {
        "id": str(sub.id),
        "url": sub.url,
        "events": sub.events,
        "description": sub.description or "",
        "is_active": sub.is_active,
        "created_at": sub.created_at.isoformat(),
    }


@router_webhooks_api.get("")
async def list_subscriptions(slug: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    subs = await wh_svc.list_subscriptions(db, org.id)
    return {"success": True, "data": [_sub_dict(s) for s in subs]}


@router_webhooks_api.post("", status_code=201)
async def create_subscription(
    slug: str, body: SubscriptionIn, db: DBSession, org_access: OrgAccess
):
    org, role, is_owner = org_access

    # Validate event types
    invalid = [e for e in body.events if e not in wh_svc.WEBHOOK_EVENTS]
    if invalid:
        raise HTTPException(400, f"Unknown event types: {', '.join(invalid)}")

    sub = await wh_svc.create_subscription(
        db,
        org_id=org.id,
        url=body.url,
        events=body.events,
        description=body.description,
    )
    return {
        "success": True,
        "data": {**_sub_dict(sub), "secret": sub.secret},
        "warning": "Save the secret now — it will not be shown again.",
    }


@router_webhooks_api.patch("/{sub_id}")
async def update_subscription(
    slug: str, sub_id: str, body: SubscriptionUpdate, db: DBSession, org_access: OrgAccess
):
    org, role, is_owner = org_access
    sub = await wh_svc.get_subscription(db, uuid.UUID(sub_id), org.id)
    if not sub:
        raise HTTPException(404, "Webhook subscription not found.")

    if body.events is not None:
        invalid = [e for e in body.events if e not in wh_svc.WEBHOOK_EVENTS]
        if invalid:
            raise HTTPException(400, f"Unknown event types: {', '.join(invalid)}")

    sub = await wh_svc.update_subscription(
        db,
        sub,
        url=body.url,
        events=body.events,
        description=body.description,
        is_active=body.is_active,
    )
    return {"success": True, "data": _sub_dict(sub)}


@router_webhooks_api.delete("/{sub_id}")
async def delete_subscription(
    slug: str, sub_id: str, db: DBSession, org_access: OrgAccess
):
    org, role, is_owner = org_access
    sub = await wh_svc.get_subscription(db, uuid.UUID(sub_id), org.id)
    if not sub:
        raise HTTPException(404, "Webhook subscription not found.")
    await wh_svc.delete_subscription(db, sub)
    return {"success": True, "message": "Subscription deleted."}


@router_webhooks_api.get("/{sub_id}/deliveries")
async def list_deliveries(
    slug: str, sub_id: str, db: DBSession, org_access: OrgAccess
):
    org, role, is_owner = org_access
    sub = await wh_svc.get_subscription(db, uuid.UUID(sub_id), org.id)
    if not sub:
        raise HTTPException(404, "Webhook subscription not found.")

    deliveries = await wh_svc.get_deliveries(db, sub.id)
    return {
        "success": True,
        "data": [
            {
                "id": str(d.id),
                "event_type": d.event_type,
                "status": d.status,
                "attempts": d.attempts,
                "response_status": d.response_status,
                "response_body": d.response_body,
                "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
                "next_retry_at": d.next_retry_at.isoformat() if d.next_retry_at else None,
                "created_at": d.created_at.isoformat(),
            }
            for d in deliveries
        ],
    }


@router_webhooks_api.post("/{sub_id}/test")
async def test_webhook(
    slug: str, sub_id: str, db: DBSession, org_access: OrgAccess
):
    """Send a test ping directly to the webhook URL, bypassing event filtering."""
    from app.models.api import WebhookDelivery

    org, role, is_owner = org_access
    sub = await wh_svc.get_subscription(db, uuid.UUID(sub_id), org.id)
    if not sub:
        raise HTTPException(404, "Webhook subscription not found.")

    delivery = WebhookDelivery(
        subscription_id=sub.id,
        event_type="webhook.test",
        payload={"event": "webhook.test", "org_id": str(org.id), "message": "Test delivery from Heelo."},
        status="pending",
    )
    db.add(delivery)
    await db.flush()

    try:
        from app.tasks.webhooks import deliver_webhook
        deliver_webhook.delay(str(delivery.id))
    except Exception:
        pass

    await db.commit()
    return {"success": True, "message": "Test delivery queued."}
