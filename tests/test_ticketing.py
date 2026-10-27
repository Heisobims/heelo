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
    # Promo validation always returns 200 - invalidity is signalled via `valid`, not
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
            "referral_code": registration.referral_token,
        },
    )
    assert resp.status_code in (200, 201)
    data = resp.json()["data"]
    expected_discount = float(ticket_type.price) * 0.05
    assert float(data["discount_amount"]) == expected_discount
    # Checkout always grosses up on top of the discounted subtotal - the
    # organizer's net (not the buyer's total) is what equals price - discount.
    from decimal import Decimal

    from app.services import payment_service as pay_svc

    subtotal = Decimal(str(ticket_type.price)) - Decimal(str(expected_discount))
    expected_total, _platform_fee, _gateway_fee = pay_svc.gross_up_for_buyer_fees(subtotal, None)
    assert abs(float(data["total_amount"]) - float(expected_total)) < 0.01


async def test_register_with_self_referral_gets_no_discount(
    client: AsyncClient, published_event, ticket_type, registration
):
    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/register",
        json={
            "items": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
            "buyer_name": "Jane Doe",
            "buyer_email": registration.attendee_email,  # same email as the referrer
            "referral_code": registration.referral_token,
        },
    )
    assert resp.status_code in (200, 201)
    data = resp.json()["data"]
    assert float(data["discount_amount"]) == 0
    # Checkout always grosses up - the buyer's total is the ticket price
    # plus Tixdoo's fee plus the estimated gateway fee, not the bare price.
    assert float(data["total_amount"]) > float(ticket_type.price)


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


async def test_registration_id_no_longer_works_as_a_referral_code(
    client: AsyncClient, published_event, ticket_type, registration
):
    """Regression test: registration_id used to double as the public referral
    code (shared in `?ref=` links) *and* the bare capability-token behind
    qr.png/badge.pdf/certificate.pdf - so sharing a referral link leaked
    access to the referrer's own ticket. referral_token now decouples the
    two; the raw id must silently fail to redeem a discount, same as any
    other unrecognized code."""
    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/register",
        json={
            "items": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
            "buyer_name": "Someone",
            "buyer_email": "someone-else@example.com",
            "referral_code": str(registration.id),
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
            "referral_code": registration.referral_token,
        },
    )

    resp = await client.get(f"/api/v1/registrations/{registration.id}/referral-stats")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["referred_count"] == 1
    assert data["discount_percent"] == 5.0
    assert "referral_path" in data


# ── Referral discount fee-split (platform absorbs first) ───────────────────────


async def _make_pending_order(db, published_event, *, total_amount, referral_discount_amount):
    from app.models.ticketing import Order

    order = Order(
        event_id=published_event.id,
        buyer_name="Jane Doe",
        buyer_email="jane@example.com",
        total_amount=total_amount,
        net_amount=total_amount,
        platform_fee=0.0,
        currency="NGN",
        payment_provider="paystack",
        payment_status="pending",
        referral_discount_amount=referral_discount_amount,
    )
    db.add(order)
    await db.flush()
    return order


async def test_referral_discount_zeroes_platform_fee_when_discount_exceeds_it(
    db: AsyncSession,
    published_event,
):
    """This synthetic case's discount (250) exceeds the platform fee it
    would otherwise generate, so the fee floors at 0 and the organizer
    keeps the full discounted total: never a negative fee."""
    from app.services import payment_service
    from app.services import ticketing_service as tk_svc

    order = await _make_pending_order(
        db, published_event, total_amount=4750.0, referral_discount_amount=250.0
    )
    order = await tk_svc.get_order(db, order.id)  # eager-loads .registrations
    await payment_service.confirm_order(db, order)
    assert order.platform_fee == 0.0
    assert order.net_amount == 4750.0


async def test_referral_discount_partially_absorbed_when_smaller_than_fee(
    db: AsyncSession,
    published_event,
):
    """Fee-split formula itself, at a synthetic discount smaller than the
    5% fee it's absorbed into: proves the subtraction (not just the floor)
    is correct."""
    from app.services import payment_service
    from app.services import ticketing_service as tk_svc

    order = await _make_pending_order(
        db, published_event, total_amount=1000.0, referral_discount_amount=10.0
    )
    order = await tk_svc.get_order(db, order.id)  # eager-loads .registrations
    await payment_service.confirm_order(db, order)
    assert order.platform_fee == 40.0  # 1000*0.05 - 10
    assert order.net_amount == 960.0


async def test_register_absorbed_fees_buyer_pays_exact_ticket_price(
    client: AsyncClient, db: AsyncSession, published_event, ticket_type
):
    """When an organizer opts into fee absorption (pass_fees_to_buyer=False),
    the buyer pays the exact ticket price with zero fee markup.
    The 5% platform fee is deducted from the organizer's net."""
    from app.services import payment_service
    from app.services import ticketing_service as tk_svc

    published_event.pass_fees_to_buyer = False
    await db.commit()

    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/register",
        json={
            "items": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
            "buyer_name": "Gala Attendee",
            "buyer_email": "gala@example.com",
        },
    )
    assert resp.status_code in (200, 201)
    data = resp.json()["data"]

    ticket_price = float(ticket_type.price)
    # Total charged to buyer is EXACT ticket price - not grossed up!
    assert float(data["total_amount"]) == ticket_price
    assert data["fees_passed_to_buyer"] is False

    # Confirm order and verify split
    order = await tk_svc.get_order(db, data["id"])
    await payment_service.confirm_order(db, order)

    expected_fee = round(ticket_price * 0.05, 2)
    expected_net = round(ticket_price - expected_fee, 2)
    assert order.platform_fee == expected_fee
    assert order.net_amount == expected_net


async def test_register_pass_fees_to_buyer_grosses_up_total(
    client: AsyncClient, db: AsyncSession, published_event, ticket_type
):
    """When pass_fees_to_buyer=True (default), fees are grossed up so the
    organizer nets 100% of the ticket price."""
    from app.services import payment_service
    from app.services import ticketing_service as tk_svc

    published_event.pass_fees_to_buyer = True
    await db.commit()

    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/register",
        json={
            "items": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
            "buyer_name": "Standard Buyer",
            "buyer_email": "standard@example.com",
        },
    )
    assert resp.status_code in (200, 201)
    data = resp.json()["data"]

    ticket_price = float(ticket_type.price)
    assert float(data["total_amount"]) > ticket_price
    assert data["fees_passed_to_buyer"] is True

    order = await tk_svc.get_order(db, data["id"])
    await payment_service.confirm_order(db, order)

    # Organizer nets the exact ticket face value
    assert order.net_amount == ticket_price
