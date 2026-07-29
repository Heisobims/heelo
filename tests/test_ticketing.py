"""Ticket types, registration, promo codes."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def test_create_ticket_type(client: AsyncClient, org, published_event, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/ticket-types",
        json={
            "name": "VIP",
            "price": 25000.0,
            "currency": "NGN",
            "quantity_total": 50,
            "description": "VIP access with lounge",
        },
        headers=user_headers,
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["name"] == "VIP"
    assert data["price"] == 25000.0


async def test_list_ticket_types_public(client: AsyncClient, published_event, ticket_type):
    resp = await client.get(f"/api/v1/events/{published_event.slug}/ticket-types")
    assert resp.status_code == 200
    types = resp.json()["data"]
    assert any(t["id"] == str(ticket_type.id) for t in types)


async def test_register_for_event(client: AsyncClient, published_event, ticket_type):
    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/register",
        json={
            "tickets": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
            "attendee_name": "Bob Okafor",
            "attendee_email": "bob@example.com",
            "phone": "+2348012345678",
        },
    )
    assert resp.status_code in (200, 201)
    data = resp.json()["data"]
    assert "order_id" in data or "registrations" in data


async def test_register_exceeding_capacity_returns_400(
    client: AsyncClient, db: AsyncSession, published_event, ticket_type
):
    # Set capacity to 0
    from app.models.ticketing import TicketType
    from sqlalchemy import select
    tt = await db.scalar(select(TicketType).where(TicketType.id == ticket_type.id))
    tt.quantity_sold = tt.quantity_total
    await db.flush()

    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/register",
        json={
            "tickets": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
            "attendee_name": "Overflow Attendee",
            "attendee_email": "over@example.com",
        },
    )
    assert resp.status_code == 400


async def test_create_promo_code(client: AsyncClient, org, published_event, ticket_type, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/promo-codes",
        json={
            "code": "SAVE20",
            "discount_type": "percentage",
            "discount_value": 20.0,
            "max_uses": 50,
        },
        headers=user_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["code"] == "SAVE20"


async def test_apply_valid_promo_code(client: AsyncClient, org, published_event, ticket_type, user_headers):
    # Create promo code first
    await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/promo-codes",
        json={"code": "FLAT500", "discount_type": "fixed", "discount_value": 500.0, "max_uses": 10},
        headers=user_headers,
    )

    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/promo-codes/validate",
        json={"code": "FLAT500"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["discount_value"] == 500.0


async def test_apply_invalid_promo_code_returns_404(client: AsyncClient, published_event):
    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/promo-codes/validate",
        json={"code": "NOSUCHCODE"},
    )
    assert resp.status_code in (404, 400)


async def test_get_registration_qr(client: AsyncClient, registration):
    resp = await client.get(f"/api/v1/registrations/{registration.id}/qr.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
