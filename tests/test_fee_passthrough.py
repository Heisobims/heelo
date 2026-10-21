"""Fee passthrough: checkout always adds Heelo's 5% fee plus an estimated
payment-gateway processing fee on top of the ticket price, so the
organizer's payout always equals exactly the price they set - mandatory
for every non-free order, not an organizer-configurable toggle. Covers the
gross-up math, the register() wiring, and confirm_order using the shared
expected_split() source of truth."""

from __future__ import annotations

from decimal import Decimal

from httpx import AsyncClient

from app.services import payment_service as pay_svc
from app.services import ticketing_service as tk_svc

# ── Pure math: gross_up_for_buyer_fees / gross_up_gateway_fee_only ─────────


def test_gross_up_for_buyer_fees_paystack_reconciles():
    subtotal = Decimal("1000")
    total, platform_fee, gateway_fee = pay_svc.gross_up_for_buyer_fees(subtotal, "paystack")
    assert platform_fee == Decimal("50.00")  # 5% of 1000
    assert total == subtotal + platform_fee + gateway_fee
    assert gateway_fee > 0


def test_gross_up_for_buyer_fees_waives_fixed_fee_below_threshold():
    """Paystack waives its ₦100 flat fee under ₦2,500 - a cheap ticket
    should reflect that, not the fixed-fee-inclusive formula."""
    subtotal = Decimal("500")
    total, platform_fee, gateway_fee = pay_svc.gross_up_for_buyer_fees(subtotal, "paystack")
    assert total == subtotal + platform_fee + gateway_fee
    # 500 + 25 (5%) = 525 base; grossed up at 1.5% only (no +100) stays well under 2500.
    assert total < Decimal("2500")


def test_gross_up_for_buyer_fees_respects_cap():
    """Paystack's fee is capped at ₦2,000 - a very large order shouldn't
    gross up the fee estimate past that cap."""
    subtotal = Decimal("500000")
    total, platform_fee, gateway_fee = pay_svc.gross_up_for_buyer_fees(subtotal, "paystack")
    assert gateway_fee <= Decimal("2000")
    assert total == subtotal + platform_fee + gateway_fee


def test_gross_up_for_buyer_fees_flutterwave_has_no_fixed_component():
    subtotal = Decimal("1000")
    total, platform_fee, gateway_fee = pay_svc.gross_up_for_buyer_fees(subtotal, "flutterwave")
    assert total == subtotal + platform_fee + gateway_fee
    assert gateway_fee > 0


def test_gross_up_for_buyer_fees_falls_back_to_paystack_rates_when_no_provider():
    subtotal = Decimal("1000")
    total, platform_fee, gateway_fee = pay_svc.gross_up_for_buyer_fees(subtotal, None)
    assert total == subtotal + platform_fee + gateway_fee
    assert gateway_fee > 0


def test_gross_up_gateway_fee_only_has_no_platform_fee_component():
    """Plan billing: Heelo is the direct merchant, so only the gateway's own
    fee is grossed up - there's no separate platform cut to add."""
    amount = Decimal("7500")
    total, gateway_fee = pay_svc.gross_up_gateway_fee_only(amount, "paystack")
    assert total == amount + gateway_fee
    assert gateway_fee > 0


# ── expected_split() - the shared source of truth ───────────────────────────


class _FakeOrder:
    def __init__(self, **kw):
        self.total_amount = kw.get("total_amount", 0.0)
        self.net_amount = kw.get("net_amount", 0.0)
        self.referral_discount_amount = kw.get("referral_discount_amount", 0.0)
        self.fees_passed_to_buyer = kw.get("fees_passed_to_buyer", False)


def test_expected_split_passthrough_uses_stored_net_amount():
    order = _FakeOrder(total_amount=1145.0, net_amount=1000.0, fees_passed_to_buyer=True)
    fee, net = pay_svc.expected_split(order)
    assert net == Decimal("1000.00")
    assert fee == Decimal("145.00")


def test_expected_split_non_passthrough_matches_referral_absorption_formula():
    """Still exercised for historical orders placed before the buyer-pays-
    fees model became mandatory - fees_passed_to_buyer=False orders still
    exist in the database and must keep resolving the same way."""
    order = _FakeOrder(
        total_amount=4750.0, referral_discount_amount=250.0, fees_passed_to_buyer=False
    )
    fee, net = pay_svc.expected_split(order)
    assert fee == Decimal("0.00")  # 5% of 4750 (237.5) < 250 discount, fully absorbed
    assert net == Decimal("4750.00")


# ── register() wiring ────────────────────────────────────────────────────────


async def test_register_grossed_up_order_fields_reconcile(
    client: AsyncClient, db, published_event, ticket_type
):
    """Every non-free order grosses up - the organizer's net always equals
    the ticket price, the buyer always pays more."""
    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/register",
        json={
            "items": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
            "buyer_name": "Jane Doe",
            "buyer_email": "jane-reconcile@example.com",
        },
    )
    assert resp.status_code in (200, 201)
    data = resp.json()["data"]
    assert float(data["total_amount"]) > float(ticket_type.price)

    from sqlalchemy import select

    from app.models.ticketing import Order

    order = await db.scalar(select(Order).where(Order.buyer_email == "jane-reconcile@example.com"))
    assert order.fees_passed_to_buyer is True
    assert order.net_amount == float(ticket_type.price)  # organizer's guaranteed net
    # platform_fee is "everything Heelo retains above the organizer's net"
    # (5% cut + gateway fee estimate combined), not just the 5% component,
    # so total = net + platform_fee, and gateway_fee_amount is a breakdown
    # of *part* of platform_fee, not an addition on top of it.
    assert order.platform_fee > 0
    assert order.gateway_fee_amount > 0
    assert order.platform_fee > order.gateway_fee_amount
    assert abs(order.total_amount - (order.net_amount + order.platform_fee)) < 0.01


async def test_free_ticket_never_grosses_up(client: AsyncClient, db, published_event):
    from app.models.ticketing import TicketType

    free_tt = TicketType(
        event_id=published_event.id, name="Free", price=0.0, currency="NGN", quantity=100
    )
    db.add(free_tt)
    await db.flush()

    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/register",
        json={
            "items": [{"ticket_type_id": str(free_tt.id), "quantity": 1}],
            "buyer_name": "Free Guest",
            "buyer_email": "free-guest@example.com",
        },
    )
    assert resp.status_code in (200, 201)
    data = resp.json()["data"]
    assert float(data["total_amount"]) == 0.0


# ── confirm_order uses expected_split (no re-derivation for passthrough) ───


async def test_confirm_order_passthrough_does_not_recompute_fee(
    db, published_event, ticket_type, client: AsyncClient
):
    import uuid

    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/register",
        json={
            "items": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
            "buyer_name": "Jane Doe",
            "buyer_email": "jane-confirm@example.com",
        },
    )
    order_id = uuid.UUID(resp.json()["data"]["id"])

    order = await tk_svc.get_order(db, order_id)
    pre_platform_fee = float(order.platform_fee)
    pre_net_amount = float(order.net_amount)

    await pay_svc.confirm_order(db, order)

    assert abs(float(order.platform_fee) - pre_platform_fee) < 0.01
    assert abs(float(order.net_amount) - pre_net_amount) < 0.01
