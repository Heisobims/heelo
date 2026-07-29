"""Webhook subscriptions — CRUD, signing, delivery."""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from httpx import AsyncClient

from app.services.webhook_service import WEBHOOK_EVENTS, sign_payload


_VALID_SUB = {
    "url": "https://example.com/webhook",
    "events": ["registration.created", "order.paid"],
    "description": "Test subscription",
}


async def test_create_webhook_subscription(client: AsyncClient, org, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/webhooks",
        json=_VALID_SUB,
        headers=user_headers,
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["url"] == _VALID_SUB["url"]
    assert "secret" in data  # shown once
    assert data["is_active"] is True


async def test_create_webhook_with_invalid_event_type_returns_400(
    client: AsyncClient, org, user_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/webhooks",
        json={**_VALID_SUB, "events": ["not.a.real.event"]},
        headers=user_headers,
    )
    assert resp.status_code == 400


async def test_list_webhook_subscriptions(client: AsyncClient, org, user_headers):
    await client.post(f"/api/v1/organizations/{org.slug}/webhooks", json=_VALID_SUB, headers=user_headers)
    resp = await client.get(f"/api/v1/organizations/{org.slug}/webhooks", headers=user_headers)
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


async def test_update_webhook_subscription(client: AsyncClient, org, user_headers):
    create = await client.post(
        f"/api/v1/organizations/{org.slug}/webhooks", json=_VALID_SUB, headers=user_headers
    )
    sub_id = create.json()["data"]["id"]

    resp = await client.patch(
        f"/api/v1/organizations/{org.slug}/webhooks/{sub_id}",
        json={"is_active": False},
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["is_active"] is False


async def test_delete_webhook_subscription(client: AsyncClient, org, user_headers):
    create = await client.post(
        f"/api/v1/organizations/{org.slug}/webhooks", json=_VALID_SUB, headers=user_headers
    )
    sub_id = create.json()["data"]["id"]

    resp = await client.delete(
        f"/api/v1/organizations/{org.slug}/webhooks/{sub_id}",
        headers=user_headers,
    )
    assert resp.status_code == 200

    # Confirm it's gone
    list_resp = await client.get(f"/api/v1/organizations/{org.slug}/webhooks", headers=user_headers)
    assert all(s["id"] != sub_id for s in list_resp.json()["data"])


async def test_sign_payload_format():
    secret = "testsecret"
    payload = {"event": "registration.created", "data": {"id": "abc"}}
    sig = sign_payload(secret, payload)

    assert sig.startswith("t=")
    assert ",v1=" in sig

    parts = dict(p.split("=", 1) for p in sig.split(","))
    ts = parts["t"]
    v1 = parts["v1"]

    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    msg = f"{ts}.{body}".encode()
    expected = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(v1, expected)


async def test_webhook_events_list_is_complete():
    required = {
        "registration.created",
        "registration.confirmed",
        "registration.cancelled",
        "checkin.completed",
        "order.paid",
        "event.published",
        "event.cancelled",
    }
    assert required.issubset(set(WEBHOOK_EVENTS))


async def test_webhook_delivery_log_endpoint(client: AsyncClient, org, user_headers):
    create = await client.post(
        f"/api/v1/organizations/{org.slug}/webhooks", json=_VALID_SUB, headers=user_headers
    )
    sub_id = create.json()["data"]["id"]

    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/webhooks/{sub_id}/deliveries",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert isinstance(resp.json()["data"], list)
