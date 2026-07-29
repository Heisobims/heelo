from __future__ import annotations

import asyncio
import hashlib
import hmac
import uuid
from collections import Counter
from decimal import Decimal

import httpx
from fastapi import HTTPException
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.ticketing import Order, Registration, TicketType

PLATFORM_FEE_PERCENT = Decimal("0.03")


# ── Payment initialization ────────────────────────────────────────────────────

async def initialize_payment(
    db: AsyncSession,
    order: Order,
    event,
    org,
) -> str:
    """Initialize payment for a pending order. Returns checkout/redirect URL."""
    currency = (org.currency or "NGN").upper()

    if settings.PAYSTACK_SECRET_KEY and currency in ("NGN", "GHS", "ZAR", "KES", "EGP"):
        url = await _initialize_paystack(db, order, event, org)
        order.payment_provider = "paystack"
        await db.commit()
        return url

    if settings.FLUTTERWAVE_SECRET_KEY:
        url = await _initialize_flutterwave(db, order, event, org)
        order.payment_provider = "flutterwave"
        await db.commit()
        return url

    if settings.STRIPE_SECRET_KEY:
        url = await _initialize_stripe(db, order, event, org)
        order.payment_provider = "stripe"
        await db.commit()
        return url

    raise HTTPException(
        503,
        "No payment provider is configured for this event. Please contact the organizer.",
    )


async def _initialize_paystack(db: AsyncSession, order: Order, event, org) -> str:
    from app.services.payment_account_service import get_default_payment_account

    reference = f"heelo_{order.id}"
    amount_kobo = max(int(float(order.total_amount) * 100), 100)

    payload: dict = {
        "email": order.buyer_email,
        "amount": amount_kobo,
        "reference": reference,
        "callback_url": f"{settings.FRONTEND_URL}/payments/callback?reference={reference}",
        "currency": org.currency or "NGN",
        "metadata": {
            "order_id": str(order.id),
            "event_id": str(event.id),
            "event_title": event.title,
            "buyer_name": order.buyer_name or "",
        },
    }

    account = await get_default_payment_account(db, org.id, "paystack")
    if account:
        platform_cut_kobo = max(int(amount_kobo * 0.03), 100)
        payload["subaccount"] = account.provider_account_id
        payload["transaction_charge"] = platform_cut_kobo
        payload["bearer"] = "subaccount"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.paystack.co/transaction/initialize",
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )

    body = resp.json()
    if not body.get("status"):
        raise HTTPException(
            502,
            f"Payment gateway error: {body.get('message', 'Could not initialize payment.')}",
        )

    return body["data"]["authorization_url"]


async def _initialize_flutterwave(db: AsyncSession, order: Order, event, org) -> str:
    cover = getattr(event, "cover_image_url", None) or ""

    payload = {
        "tx_ref": f"heelo_{order.id}",
        "amount": float(order.total_amount),
        "currency": org.currency or "NGN",
        "redirect_url": f"{settings.FRONTEND_URL}/payments/flutterwave/callback",
        "customer": {
            "email": order.buyer_email,
            "name": order.buyer_name or order.buyer_email,
        },
        "meta": {
            "order_id": str(order.id),
            "event_id": str(event.id),
        },
        "customizations": {
            "title": event.title,
            "description": f"Tickets for {event.title}",
            "logo": cover,
        },
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.flutterwave.com/v3/payments",
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )

    body = resp.json()
    if body.get("status") != "success":
        raise HTTPException(
            502,
            f"Payment gateway error: {body.get('message', 'Could not initialize payment.')}",
        )

    return body["data"]["link"]


async def _initialize_stripe(db: AsyncSession, order: Order, event, org) -> str:
    import stripe  # type: ignore

    start_label = ""
    if event.start_datetime:
        start_label = event.start_datetime.strftime("%b %d, %Y")

    def _create_session():
        return stripe.checkout.Session.create(
            api_key=settings.STRIPE_SECRET_KEY,
            payment_method_types=["card"],
            mode="payment",
            client_reference_id=str(order.id),
            customer_email=order.buyer_email,
            line_items=[
                {
                    "price_data": {
                        "currency": (org.currency or "USD").lower(),
                        "unit_amount": int(float(order.total_amount) * 100),
                        "product_data": {
                            "name": f"Tickets — {event.title}",
                            "description": f"{event.title}" + (f" · {start_label}" if start_label else ""),
                        },
                    },
                    "quantity": 1,
                }
            ],
            success_url=(
                f"{settings.FRONTEND_URL}/payments/stripe/return"
                "?session_id={CHECKOUT_SESSION_ID}"
            ),
            cancel_url=(
                f"{settings.FRONTEND_URL}/orders/{order.id}/confirmation?cancelled=1"
            ),
            metadata={"order_id": str(order.id)},
        )

    session = await asyncio.to_thread(_create_session)
    return session.url


# ── Verification ──────────────────────────────────────────────────────────────

async def verify_paystack(db: AsyncSession, reference: str) -> Order | None:
    """Verify a Paystack payment by reference and confirm the order. Idempotent."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
            timeout=15.0,
        )

    body = resp.json()
    if not body.get("status") or body["data"]["status"] != "success":
        return None

    order = await _order_from_reference(db, reference)
    if not order:
        return None

    if order.payment_status == "paid":
        return order

    order.payment_reference = body["data"]["reference"]
    await confirm_order(db, order)
    return order


async def verify_flutterwave(db: AsyncSession, transaction_id: int) -> Order | None:
    """Verify a Flutterwave transaction by ID and confirm the order. Idempotent."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.flutterwave.com/v3/transactions/{transaction_id}/verify",
            headers={"Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}"},
            timeout=15.0,
        )

    body = resp.json()
    if body.get("status") != "success" or body["data"]["status"] != "successful":
        return None

    tx_ref = body["data"].get("tx_ref", "")
    order = await _order_from_reference(db, tx_ref)
    if not order or order.payment_status == "paid":
        return order

    order.payment_reference = str(transaction_id)
    await confirm_order(db, order)
    return order


async def verify_stripe_session(db: AsyncSession, session_id: str) -> Order | None:
    """Retrieve a Stripe checkout session and confirm the order if paid. Idempotent."""
    import stripe  # type: ignore

    try:
        session = await asyncio.to_thread(
            stripe.checkout.Session.retrieve,
            session_id,
            api_key=settings.STRIPE_SECRET_KEY,
        )
    except Exception:
        return None

    if session.payment_status != "paid":
        return None

    order_id_str = (session.metadata or {}).get("order_id")
    if not order_id_str:
        return None

    try:
        order_id = uuid.UUID(order_id_str)
    except ValueError:
        return None

    from app.services.ticketing_service import get_order
    order = await get_order(db, order_id)
    if not order or order.payment_status == "paid":
        return order

    order.payment_reference = session.payment_intent or session.id
    await confirm_order(db, order)
    return order


async def _order_from_reference(db: AsyncSession, reference: str) -> Order | None:
    """Extract order_id from a heelo_{uuid} reference string and return the order."""
    if not reference.startswith("heelo_"):
        return None
    try:
        order_id = uuid.UUID(reference[6:])
    except ValueError:
        return None

    from app.services.ticketing_service import get_order
    return await get_order(db, order_id)


# ── Confirm order ─────────────────────────────────────────────────────────────

async def confirm_order(db: AsyncSession, order: Order) -> None:
    """Mark order as paid, update ticket quantities, confirm registrations. Idempotent."""
    if order.payment_status == "paid":
        return

    total = Decimal(str(float(order.total_amount)))
    fee = (total * PLATFORM_FEE_PERCENT).quantize(Decimal("0.01"))

    order.payment_status = "paid"
    order.platform_fee = float(fee)
    order.net_amount = float(total - fee)

    registrations: list[Registration] = order.registrations or []
    tt_counts = Counter(
        reg.ticket_type_id for reg in registrations if reg.status == "pending"
    )

    for tt_id, count in tt_counts.items():
        await db.execute(
            update(TicketType)
            .where(TicketType.id == tt_id)
            .values(
                quantity_sold=TicketType.quantity_sold + count,
                quantity_reserved=func.greatest(TicketType.quantity_reserved - count, 0),
            )
        )

    for reg in registrations:
        if reg.status == "pending":
            reg.status = "confirmed"

    await db.commit()

    # Enqueue confirmation email + WhatsApp — fire-and-forget, never block on failure.
    try:
        from app.tasks.email import send_registration_confirmation as _email_conf
        _email_conf.delay(str(order.id))
    except Exception:
        pass
    try:
        from app.tasks.whatsapp import send_registration_confirmation as _wa_conf
        _wa_conf.delay(str(order.id))
    except Exception:
        pass
    try:
        from app.services import webhook_service as _wh_svc
        event_obj = order.registrations[0].event if (order.registrations and order.registrations[0].event) else None
        _org_id = event_obj.org_id if event_obj else None
        if _org_id:
            await _wh_svc.fire_event(
                db,
                org_id=_org_id,
                event_type="order.paid",
                payload={
                    "event": "order.paid",
                    "order_id": str(order.id),
                    "total_amount": float(order.total_amount),
                    "net_amount": float(order.net_amount or 0),
                    "currency": order.currency,
                    "registration_count": len(registrations),
                },
            )
    except Exception:
        pass


# ── Signature verification ────────────────────────────────────────────────────

def verify_paystack_signature(body: bytes, signature: str) -> bool:
    expected = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode(),
        body,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_flutterwave_signature(signature: str) -> bool:
    secret = getattr(settings, "FLUTTERWAVE_WEBHOOK_SECRET", "")
    if not secret:
        return False
    return hmac.compare_digest(secret, signature)
