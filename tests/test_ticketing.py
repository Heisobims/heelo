"""Ticket types, registration, promo codes."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def test_create_ticket_type(client: AsyncClient, org, published_event, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/ticket-types",
        json={
            "name": "VIP",
            "price": 25000.0,
            "currency": "NGN",
            "quantity": 50,
            "description": "VIP access with lounge",
        },
        headers=user_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "VIP"
    assert float(data["price"]) == 25000.0


async def test_list_ticket_types_public(client: AsyncClient, published_event, ticket_type):
    resp = await client.get(f"/api/v1/events/{published_event.slug}/ticket-types")
    assert resp.status_code == 200
    types = resp.json()
    assert any(t["id"] == str(ticket_type.id) for t in types)


async def test_register_for_event(client: AsyncClient, published_event, ticket_type):
    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/register",
        json={
            "items": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
            "buyer_name": "Bob Okafor",
            "buyer_email": "bob@example.com",
            "buyer_phone": "+2348012345678",
        },
    )
    assert resp.status_code in (200, 201)
    data = resp.json()["data"]
    assert "id" in data or "registrations" in data


async def test_register_exceeding_capacity_returns_409(
    client: AsyncClient, db: AsyncSession, published_event, ticket_type
):
    # Fill capacity so the next registration has no room.
    from sqlalchemy import select

    from app.models.ticketing import TicketType

    tt = await db.scalar(select(TicketType).where(TicketType.id == ticket_type.id))
    tt.quantity_sold = tt.quantity
    await db.flush()

    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/register",
        json={
            "items": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
            "buyer_name": "Overflow Attendee",
            "buyer_email": "over@example.com",
        },
    )
    assert resp.status_code == 409


async def test_create_promo_code(
    client: AsyncClient, org, published_event, ticket_type, user_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/promo-codes",
        json={
            "code": "SAVE20",
            "discount_type": "percent",
            "discount_value": 20.0,
            "max_uses": 50,
        },
        headers=user_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["code"] == "SAVE20"


async def test_apply_valid_promo_code(
    client: AsyncClient, org, published_event, ticket_type, user_headers
):
    # Create promo code first
    await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/promo-codes",
        json={"code": "FLAT500", "discount_type": "fixed", "discount_value": 500.0, "max_uses": 10},
        headers=user_headers,
    )

    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/promo-codes/validate",
        json={
            "code": "FLAT500",
            "items": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert float(body["discount_value"]) == 500.0


async def test_apply_invalid_promo_code_returns_not_valid(
    client: AsyncClient, published_event, ticket_type
):
    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/promo-codes/validate",
        json={
            "code": "NOSUCHCODE",
            "items": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
        },
    )
    # Promo validation always returns 200 — invalidity is signalled via `valid`, not
    # a 4xx status, so the frontend can show an inline message rather than an error.
    assert resp.status_code == 200
    assert resp.json()["valid"] is False


async def test_get_registration_qr(client: AsyncClient, registration):
    resp = await client.get(f"/api/v1/registrations/{registration.id}/qr.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


# ── Referral tracking ────────────────────────────────────────────────────────


async def test_register_with_valid_referral_code_gets_discount(
    client: AsyncClient, published_event, ticket_type, registration
):
    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/register",
        json={
            "items": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
            "buyer_name": "Referred Friend",
            "buyer_email": "friend@example.com",
            "referral_code": str(registration.id),
        },
    )
    assert resp.status_code in (200, 201)
    data = resp.json()["data"]
    expected_discount = float(ticket_type.price) * 0.10
    assert float(data["discount_amount"]) == expected_discount
    assert float(data["total_amount"]) == float(ticket_type.price) - expected_discount


async def test_register_with_self_referral_gets_no_discount(
    client: AsyncClient, published_event, ticket_type, registration
):
    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/register",
        json={
            "items": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
            "buyer_name": "Jane Doe",
            "buyer_email": registration.attendee_email,  # same email as the referrer
            "referral_code": str(registration.id),
        },
    )
    assert resp.status_code in (200, 201)
    data = resp.json()["data"]
    assert float(data["discount_amount"]) == 0
    assert float(data["total_amount"]) == float(ticket_type.price)


async def test_register_with_unknown_referral_code_gets_no_discount(
    client: AsyncClient, published_event, ticket_type
):
    import uuid

    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/register",
        json={
            "items": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
            "buyer_name": "Someone",
            "buyer_email": "someone@example.com",
            "referral_code": str(uuid.uuid4()),
        },
    )
    assert resp.status_code in (200, 201)
    assert float(resp.json()["data"]["discount_amount"]) == 0


async def test_referral_stats_counts_referred_orders(
    client: AsyncClient, published_event, ticket_type, registration
):
    await client.post(
        f"/api/v1/events/{published_event.slug}/register",
        json={
            "items": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
            "buyer_name": "Referred Friend",
            "buyer_email": "friend2@example.com",
            "referral_code": str(registration.id),
        },
    )

    resp = await client.get(f"/api/v1/registrations/{registration.id}/referral-stats")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["referred_count"] == 1
    assert data["discount_percent"] == 10.0
    assert "referral_path" in data
