from __future__ import annotations

import asyncio
import hashlib
import hmac
import uuid
from collections import Counter
from decimal import Decimal

import httpx
import structlog
from fastapi import HTTPException
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.payment import PlanInvoice
from app.models.ticketing import Order, Registration, TicketType

logger = structlog.get_logger()

PLATFORM_FEE_PERCENT = Decimal("0.05")


def select_provider(currency: str) -> str | None:
    """Smart global provider selection:
    - Global/Western currencies (USD, EUR, GBP, CAD, AUD, etc.) route to Stripe for seamless Apple Pay/Google Pay/Card checkout.
    - African currencies with native Paystack rails (NGN, GHS, ZAR, KES, EGP) route to Paystack.
    - Pan-African & alternative corridors route to Flutterwave.
    - Falls back to whichever provider is configured.
    """
    curr = (currency or "USD").upper()
    # 1. Global / International currencies prefer Stripe
    if settings.STRIPE_SECRET_KEY and curr in (
        "USD", "EUR", "GBP", "CAD", "AUD", "NZD", "CHF", "SGD", "JPY", "SEK", "NOK", "DKK", "PLN", "HKD", "BRL", "MXN", "INR"
    ):
        return "stripe"
    # 2. African currencies with direct Paystack domestic rails
    if settings.PAYSTACK_SECRET_KEY and curr in ("NGN", "GHS", "ZAR", "KES", "EGP"):
        return "paystack"
    # 3. Flutterwave for Pan-African corridors
    if settings.FLUTTERWAVE_SECRET_KEY:
        return "flutterwave"
    # 4. Fallbacks
    if settings.STRIPE_SECRET_KEY:
        return "stripe"
    if settings.PAYSTACK_SECRET_KEY:
        return "paystack"
    return None


# Published local-card headline rates - used only to *estimate* the buyer-
# facing "processing fee" line before checkout starts. The provider's real
# deducted fee depends on the payment method the buyer picks on its own
# hosted checkout page (card vs bank transfer vs USSD all cost differently),
# which isn't knowable until after this amount is fixed and charged. Any gap
# between this estimate and the real fee is absorbed by Heelo - the
# organizer's net and the buyer's charged total are both already fixed by
# the time that gap could be known, so neither of them can absorb it.
_GATEWAY_FEE_RATES: dict[str, dict[str, Decimal | None]] = {
    "paystack": {
        "rate": Decimal("0.015"),
        "fixed": Decimal("100"),
        "fixed_waived_below": Decimal("2500"),
        "cap": Decimal("2000"),
    },
    "flutterwave": {
        "rate": Decimal("0.014"),
        "fixed": Decimal("0"),
        "fixed_waived_below": Decimal("0"),
        "cap": None,
    },
    "stripe": {
        "rate": Decimal("0.029"),
        "fixed": Decimal("0.30"),
        "fixed_waived_below": Decimal("0"),
        "cap": None,
    },
}


def _gross_up_base(base: Decimal, provider: str | None) -> Decimal:
    """Solve `total = base + provider_fee(total)` for total - the provider's
    own fee is a function of the amount being charged, not just `base`."""
    cfg = _GATEWAY_FEE_RATES.get(provider or "paystack", _GATEWAY_FEE_RATES["paystack"])
    rate: Decimal = cfg["rate"]  # type: ignore[assignment]
    fixed: Decimal = cfg["fixed"]  # type: ignore[assignment]

    total = (base + fixed) / (Decimal("1") - rate)
    if fixed > 0 and total < cfg["fixed_waived_below"]:  # type: ignore[operator]
        total = base / (Decimal("1") - rate)

    cap = cfg["cap"]
    if cap is not None and (total - base) > cap:
        total = base + cap

    return total.quantize(Decimal("0.01"))


def gross_up_for_buyer_fees(
    subtotal: Decimal, provider: str | None
) -> tuple[Decimal, Decimal, Decimal]:
    """Given `subtotal` (the amount the organizer must net, already net of
    any discounts), return (total_to_charge, platform_fee, gateway_fee)
    such that total = subtotal + platform_fee + gateway_fee.

    platform_fee is Heelo's flat 5%; gateway_fee is a gross-up estimate of
    what `provider` will deduct from a charge of `total` (fee-inclusive
    pricing).
    """
    platform_fee = (subtotal * PLATFORM_FEE_PERCENT).quantize(Decimal("0.01"))
    total = _gross_up_base(subtotal + platform_fee, provider)
    gateway_fee = (total - subtotal - platform_fee).quantize(Decimal("0.01"))
    return total, platform_fee, gateway_fee


def gross_up_gateway_fee_only(amount: Decimal, provider: str | None) -> tuple[Decimal, Decimal]:
    """Same gross-up, without a platform-fee component - for charges where
    Heelo is directly the merchant (org plan billing), so there's no
    separate "platform cut" to add on top of itself, only the payment
    gateway's own processing fee. Returns (total_to_charge, gateway_fee)."""
    total = _gross_up_base(amount, provider)
    gateway_fee = (total - amount).quantize(Decimal("0.01"))
    return total, gateway_fee


def fee_estimate_config(currency: str) -> dict:
    """JSON-friendly gateway-fee config for whichever provider would
    actually be used for `currency` - lets the checkout page mirror
    gross_up_for_buyer_fees() client-side to show a live running total
    (including the estimated processing fee) as the buyer picks tickets,
    before the real server-computed total is confirmed at submission.
    Falls back to Paystack's rates when no provider is configured yet,
    matching gross_up_for_buyer_fees()'s own fallback - so the client-side
    preview and the server-computed charge always agree, even in a fresh
    environment with no payment provider keys set."""
    provider = select_provider(currency)
    cfg = _GATEWAY_FEE_RATES.get(provider or "paystack", _GATEWAY_FEE_RATES["paystack"])
    return {
        "provider": provider,
        "rate": float(cfg["rate"]),  # type: ignore[arg-type]
        "fixed": float(cfg["fixed"]),  # type: ignore[arg-type]
        "fixed_waived_below": float(cfg["fixed_waived_below"]),  # type: ignore[arg-type]
        "cap": float(cfg["cap"]) if cfg["cap"] is not None else None,  # type: ignore[arg-type]
    }


def expected_split(order: Order) -> tuple[Decimal, Decimal]:
    """The single source of truth for "how much of this order's total_amount
    is Heelo's cut vs. the organizer's net" - used both to tell the payment
    provider how to split the real transaction (at initialize time) and to
    finalize our own bookkeeping (at confirm time), so the two can never
    drift apart. Returns (platform_fee, net_amount)."""
    total = Decimal(str(float(order.total_amount)))
    if order.fees_passed_to_buyer:
        # platform_fee + gateway_fee_amount were already fixed at order
        # creation (ticketing_service.register()) - net_amount is the
        # organizer's guaranteed, discount-adjusted ticket subtotal.
        net = Decimal(str(float(order.net_amount)))
        fee = total - net
        return fee.quantize(Decimal("0.01")), net.quantize(Decimal("0.01"))

    referral_discount = Decimal(str(float(order.referral_discount_amount or 0)))
    fee = max(Decimal("0"), (total * PLATFORM_FEE_PERCENT) - referral_discount).quantize(
        Decimal("0.01")
    )
    net = (total - fee).quantize(Decimal("0.01"))
    return fee, net


# ── Payment initialization ────────────────────────────────────────────────────


async def initialize_payment(
    db: AsyncSession,
    order: Order,
    event,
    org,
) -> str:
    """Initialize payment for a pending order. Returns checkout/redirect URL."""
    provider = select_provider(org.currency)

    if provider == "paystack":
        url = await _initialize_paystack(db, order, event, org)
        order.payment_provider = "paystack"
        await db.commit()
        return url

    if provider == "flutterwave":
        url = await _initialize_flutterwave(db, order, event, org)
        order.payment_provider = "flutterwave"
        await db.commit()
        return url

    if provider == "stripe":
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
        platform_fee, _net = expected_split(order)
        # Floor of 1 kobo (not 0) even when platform_fee computes to exactly
        # 0 (e.g. a referral discount that fully absorbed it) - Paystack's
        # split relationship needs a genuinely nonzero transaction_charge to
        # be reliably established; the difference is immaterial.
        platform_cut_kobo = max(int(float(platform_fee) * 100), 1)
        payload["subaccount"] = account.provider_account_id
        payload["transaction_charge"] = platform_cut_kobo
        # "account" (Heelo), not "subaccount" (organizer) - Paystack's own
        # processing fee comes out of Heelo's cut, so the organizer always
        # receives exactly the net amount computed above regardless of
        # which payment method the buyer used or how accurate our gateway-
        # fee estimate turned out to be.
        payload["bearer"] = "account"
        order.auto_split_applied = True

    try:
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
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            502,
            f"Payment gateway connection error: {exc}",
        ) from exc

    if not body.get("status"):
        raise HTTPException(
            502,
            f"Payment gateway error: {body.get('message', 'Could not initialize payment.')}",
        )

    return body["data"]["authorization_url"]


async def _initialize_flutterwave(db: AsyncSession, order: Order, event, org) -> str:
    from app.services.payment_account_service import get_default_payment_account

    cover = getattr(event, "cover_image_url", None) or ""

    payload: dict = {
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

    account = await get_default_payment_account(db, org.id, "flutterwave")
    if account:
        platform_fee, _net = expected_split(order)
        # Per-transaction override of the subaccount's default split (set at
        # subaccount creation in create_flutterwave_subaccount) - needed so
        # the organizer's actual cut tracks this specific order's discount/
        # fee-passthrough math instead of always taking a flat percentage.
        # NB: "transaction_charge" here is what Flutterwave routes to the
        # *platform* (Heelo), mirroring Paystack's field of the same name -
        # verify this against Flutterwave's current API docs before
        # depending on it in production; if the platform's own Flutterwave
        # account isn't itself a subaccount reference, this is the standard
        # shape, but Flutterwave's subaccount API has changed shape before.
        platform_fee_amount = float(platform_fee) if float(platform_fee) > 0 else 0.01
        payload["subaccounts"] = [
            {
                "id": account.provider_account_id,
                "transaction_charge_type": "flat",
                "transaction_charge": platform_fee_amount,
            }
        ]
        order.auto_split_applied = True

    try:
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
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            502,
            f"Payment gateway connection error: {exc}",
        ) from exc

    if body.get("status") != "success":
        raise HTTPException(
            502,
            f"Payment gateway error: {body.get('message', 'Could not initialize payment.')}",
        )

    return body["data"]["link"]


async def _initialize_stripe(db: AsyncSession, order: Order, event, org) -> str:
    import stripe  # type: ignore

    from app.services.payment_account_service import get_default_payment_account

    start_label = ""
    if event.start_datetime:
        start_label = event.start_datetime.strftime("%b %d, %Y")

    session_kwargs: dict = {
        "api_key": settings.STRIPE_SECRET_KEY,
        "payment_method_types": ["card"],
        "mode": "payment",
        "client_reference_id": str(order.id),
        "customer_email": order.buyer_email,
        "line_items": [
            {
                "price_data": {
                    "currency": (org.currency or "USD").lower(),
                    "unit_amount": int(float(order.total_amount) * 100),
                    "product_data": {
                        "name": f"Tickets: {event.title}",
                        "description": f"{event.title}"
                        + (f" · {start_label}" if start_label else ""),
                    },
                },
                "quantity": 1,
            }
        ],
        "success_url": (
            f"{settings.FRONTEND_URL}/payments/stripe/return" "?session_id={CHECKOUT_SESSION_ID}"
        ),
        "cancel_url": f"{settings.FRONTEND_URL}/orders/{order.id}/confirmation?cancelled=1",
        "metadata": {"order_id": str(order.id)},
    }

    account = await get_default_payment_account(db, org.id, "stripe")
    if account and account.is_verified:
        platform_fee, _net = expected_split(order)
        # Destination charge: the charge stays owned by Heelo's platform
        # account (no on_behalf_of), so Stripe's own processing fee comes
        # out of Heelo's application_fee_amount, never the organizer's
        # transfer - same "bearer=account" semantics as Paystack, so the
        # organizer's net is exactly what expected_split() computed
        # regardless of Stripe's real fee.
        session_kwargs["payment_intent_data"] = {
            "application_fee_amount": max(int(float(platform_fee) * 100), 1),
            "transfer_data": {"destination": account.provider_account_id},
        }
        order.auto_split_applied = True

    def _create_session():
        return stripe.checkout.Session.create(**session_kwargs)

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

    paid_kobo = int(body["data"].get("amount") or 0)
    expected_kobo = max(int(float(order.total_amount) * 100), 100)
    if paid_kobo != expected_kobo or body["data"].get("currency") != order.currency:
        logger.error(
            "payment.amount_mismatch",
            order_id=str(order.id),
            paid_kobo=paid_kobo,
            expected_kobo=expected_kobo,
        )
        return None

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

    paid_amount = Decimal(str(body["data"].get("amount") or 0))
    if (
        paid_amount != Decimal(str(float(order.total_amount)))
        or body["data"].get("currency") != order.currency
    ):
        logger.error(
            "payment.amount_mismatch",
            order_id=str(order.id),
            paid_amount=str(paid_amount),
            expected_amount=str(order.total_amount),
        )
        return None

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


# ── Plan billing (org plan upgrades/renewals) ─────────────────────────────────
#
# Parallel to the ticket-order functions above, not a refactor of them - the
# ticket-order path has heavy test coverage and real production traffic
# implications; a shared/generalized "payable" abstraction would touch both
# to save a modest amount of duplication for comparatively little benefit.
# Reference format is `heelo_plan_{invoice.id}` (ticket orders use
# `heelo_{order.id}`) so the two are never ambiguous to a webhook handler.


async def initialize_plan_payment(db: AsyncSession, invoice: PlanInvoice, org) -> str:
    """Initialize payment for a pending plan invoice. Returns checkout/redirect URL."""
    currency = (org.currency or "NGN").upper()

    if settings.PAYSTACK_SECRET_KEY and currency in ("NGN", "GHS", "ZAR", "KES", "EGP"):
        url = await _initialize_paystack_plan(invoice, org)
        invoice.provider = "paystack"
        await db.commit()
        return url

    if settings.FLUTTERWAVE_SECRET_KEY:
        url = await _initialize_flutterwave_plan(invoice, org)
        invoice.provider = "flutterwave"
        await db.commit()
        return url

    if settings.STRIPE_SECRET_KEY:
        url = await _initialize_stripe_plan(invoice, org)
        invoice.provider = "stripe"
        await db.commit()
        return url

    raise HTTPException(503, "No payment provider is configured. Please contact support.")


async def _initialize_paystack_plan(invoice: PlanInvoice, org) -> str:
    reference = f"heelo_plan_{invoice.id}"
    amount_kobo = max(int(float(invoice.amount) * 100), 100)

    payload: dict = {
        "email": org.contact_email or _org_billing_email(org),
        "amount": amount_kobo,
        "reference": reference,
        "callback_url": f"{settings.FRONTEND_URL}/billing/callback?reference={reference}",
        "currency": invoice.currency,
        "metadata": {
            "invoice_id": str(invoice.id),
            "org_id": str(org.id),
            "kind": "plan_invoice",
            "plan": invoice.plan,
        },
    }

    try:
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
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            502,
            f"Payment gateway connection error: {exc}",
        ) from exc

    if not body.get("status"):
        raise HTTPException(
            502,
            f"Payment gateway error: {body.get('message', 'Could not initialize payment.')}",
        )

    return body["data"]["authorization_url"]


async def _initialize_flutterwave_plan(invoice: PlanInvoice, org) -> str:
    payload = {
        "tx_ref": f"heelo_plan_{invoice.id}",
        "amount": float(invoice.amount),
        "currency": invoice.currency,
        "redirect_url": f"{settings.FRONTEND_URL}/billing/flutterwave/callback",
        "customer": {"email": org.contact_email or _org_billing_email(org), "name": org.name},
        "meta": {"invoice_id": str(invoice.id), "org_id": str(org.id), "kind": "plan_invoice"},
        "customizations": {
            "title": f"Heelo {invoice.plan.capitalize()} plan",
            "description": f"{invoice.plan.capitalize()} plan (30 days)",
        },
    }

    try:
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
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            502,
            f"Payment gateway connection error: {exc}",
        ) from exc

    if body.get("status") != "success":
        raise HTTPException(
            502,
            f"Payment gateway error: {body.get('message', 'Could not initialize payment.')}",
        )

    return body["data"]["link"]


async def _initialize_stripe_plan(invoice: PlanInvoice, org) -> str:
    import stripe  # type: ignore

    def _create_session():
        return stripe.checkout.Session.create(
            api_key=settings.STRIPE_SECRET_KEY,
            payment_method_types=["card"],
            mode="payment",
            customer_email=org.contact_email or _org_billing_email(org),
            line_items=[
                {
                    "price_data": {
                        "currency": (invoice.currency or "USD").lower(),
                        "unit_amount": int(float(invoice.amount) * 100),
                        "product_data": {
                            "name": f"Heelo {invoice.plan.capitalize()} plan (30 days)",
                        },
                    },
                    "quantity": 1,
                }
            ],
            success_url=(
                f"{settings.FRONTEND_URL}/billing/stripe/return?session_id={{CHECKOUT_SESSION_ID}}"
            ),
            cancel_url=f"{settings.FRONTEND_URL}/org/{org.slug}/plan?payment_failed=1",
            metadata={"invoice_id": str(invoice.id), "org_id": str(org.id), "kind": "plan_invoice"},
        )

    session = await asyncio.to_thread(_create_session)
    return session.url


def _org_billing_email(org) -> str:
    """Best-effort billing email when the org has no contact_email set -
    Paystack/Stripe require *some* email on the checkout session."""
    return f"billing+{org.slug}@heelo.io"


async def verify_paystack_plan(db: AsyncSession, reference: str) -> PlanInvoice | None:
    """Verify a Paystack plan payment by reference. Idempotent - does not
    itself confirm the invoice; caller applies the plan change."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
            timeout=15.0,
        )

    body = resp.json()
    if not body.get("status") or body["data"]["status"] != "success":
        return None

    invoice = await _plan_invoice_from_reference(db, reference)
    if not invoice:
        return None

    paid_kobo = int(body["data"].get("amount") or 0)
    expected_kobo = max(int(float(invoice.amount) * 100), 100)
    if paid_kobo != expected_kobo or body["data"].get("currency") != invoice.currency:
        logger.error(
            "billing.plan_amount_mismatch",
            invoice_id=str(invoice.id),
            paid_kobo=paid_kobo,
            expected_kobo=expected_kobo,
        )
        return None

    invoice.provider_reference = body["data"]["reference"]
    return invoice


async def verify_flutterwave_plan(db: AsyncSession, transaction_id: int) -> PlanInvoice | None:
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
    invoice = await _plan_invoice_from_reference(db, tx_ref)
    if not invoice:
        return None

    paid_amount = Decimal(str(body["data"].get("amount") or 0))
    if (
        paid_amount != Decimal(str(float(invoice.amount)))
        or body["data"].get("currency") != invoice.currency
    ):
        logger.error(
            "billing.plan_amount_mismatch",
            invoice_id=str(invoice.id),
            paid_amount=str(paid_amount),
            expected_amount=str(invoice.amount),
        )
        return None

    invoice.provider_reference = str(transaction_id)
    return invoice


async def verify_stripe_plan_session(db: AsyncSession, session_id: str) -> PlanInvoice | None:
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

    metadata = session.metadata or {}
    if metadata.get("kind") != "plan_invoice":
        return None
    invoice_id_str = metadata.get("invoice_id")
    if not invoice_id_str:
        return None

    try:
        invoice_id = uuid.UUID(invoice_id_str)
    except ValueError:
        return None

    invoice = await db.get(PlanInvoice, invoice_id)
    if not invoice:
        return None

    invoice.provider_reference = session.payment_intent or session.id
    return invoice


async def _plan_invoice_from_reference(db: AsyncSession, reference: str) -> PlanInvoice | None:
    """Extract invoice_id from a heelo_plan_{uuid} reference string."""
    if not reference.startswith("heelo_plan_"):
        return None
    try:
        invoice_id = uuid.UUID(reference[len("heelo_plan_") :])
    except ValueError:
        return None
    return await db.get(PlanInvoice, invoice_id)


# ── Confirm order ─────────────────────────────────────────────────────────────


async def confirm_order(db: AsyncSession, order: Order) -> None:
    """Mark order as paid, update ticket quantities, confirm registrations. Idempotent."""
    # Atomic claim, not a plain read-then-write - a webhook and the browser
    # redirect callback can both call this for the same order at nearly the
    # same moment. This UPDATE takes a row lock immediately; a concurrent
    # call blocks until the first commits, then re-evaluates the WHERE
    # clause against the now-'paid' row and correctly no-ops below.
    claim = await db.execute(
        update(Order)
        .where(Order.id == order.id, Order.payment_status != "paid")
        .values(payment_status="paid")
        .returning(Order.id)
    )
    if claim.fetchone() is None:
        return
    order.payment_status = "paid"  # keep the in-memory object consistent

    # expected_split() is the same function that told the payment provider
    # how to split this exact transaction at initialize time (see
    # _initialize_paystack/_initialize_flutterwave) - reusing it here
    # instead of re-deriving the numbers guarantees our bookkeeping can
    # never drift from what was actually sent to the provider.
    fee, net = expected_split(order)
    order.platform_fee = float(fee)
    order.net_amount = float(net)

    registrations: list[Registration] = order.registrations or []
    tt_counts = Counter(reg.ticket_type_id for reg in registrations if reg.status == "pending")

    if registrations and not tt_counts:
        # Every registration on this order is already non-pending - most
        # likely the stale-reservation reaper (app/tasks/ticketing.py)
        # cancelled them before this (late) payment confirmation arrived.
        # Leaving the order 'paid' with cancelled registrations means a
        # customer paid and got no ticket, so best-effort restore them
        # instead - accepting a small residual overselling risk in this
        # already-rare window - and log loudly so it surfaces for follow-up.
        logger.error(
            "payment.confirmed_after_reservation_expired",
            order_id=str(order.id),
            registration_ids=[str(r.id) for r in registrations],
        )
        tt_counts = Counter(reg.ticket_type_id for reg in registrations)
        for reg in registrations:
            reg.status = "pending"  # so the loop below re-confirms them

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

    # Attribute ticket sale to promoter / affiliate if referral_code is present
    if order.referral_code:
        try:
            from app.services import affiliate_service as aff_svc

            ticket_qty = len(registrations) or 1
            await aff_svc.attribute_order_to_affiliate(
                db,
                event_id=order.event_id,
                referral_code=order.referral_code,
                order_amount=float(order.total_amount),
                tickets_count=ticket_qty,
            )
        except Exception as exc:
            logger.warning("affiliate.attribution_failed", order_id=str(order.id), error=str(exc))

    await db.commit()

    # Enqueue confirmation email + WhatsApp - fire-and-forget, never block on failure.
    try:
        from app.tasks.email import send_registration_confirmation as _email_conf

        _email_conf.delay(str(order.id))
    except Exception as err:
        logger.warning(
            "payment.confirmation_email_enqueue_failed", order_id=str(order.id), error=str(err)
        )
    try:
        from app.tasks.whatsapp import send_registration_confirmation as _wa_conf

        _wa_conf.delay(str(order.id))
    except Exception as err:
        logger.warning(
            "payment.confirmation_whatsapp_enqueue_failed", order_id=str(order.id), error=str(err)
        )
    try:
        from app.services import webhook_service as _wh_svc

        event_obj = (
            order.registrations[0].event
            if (order.registrations and order.registrations[0].event)
            else None
        )
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
    except Exception as err:
        logger.warning("payment.order_paid_webhook_failed", order_id=str(order.id), error=str(err))


# ── Refunds ───────────────────────────────────────────────────────────────────


async def refund_order_item(order: Order, amount: Decimal) -> bool:
    """Refund `amount` (gross, in order.currency) via the order's payment provider.

    Returns True on success. A False return means nothing was refunded - the
    caller must not treat the ticket as refunded.
    """
    if not order.payment_provider or order.payment_provider == "free":
        return True  # nothing was ever charged

    try:
        if order.payment_provider == "paystack":
            return await _refund_paystack(order, amount)
        if order.payment_provider == "flutterwave":
            return await _refund_flutterwave(order, amount)
        if order.payment_provider == "stripe":
            return await _refund_stripe(order, amount)
    except Exception as exc:
        logger.error(
            "payment.refund_failed",
            order_id=str(order.id),
            provider=order.payment_provider,
            error=str(exc),
        )
        return False

    logger.warning("payment.refund_unknown_provider", provider=order.payment_provider)
    return False


async def _refund_paystack(order: Order, amount: Decimal) -> bool:
    if not order.payment_reference:
        return False
    amount_kobo = max(int(float(amount) * 100), 100)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.paystack.co/refund",
            json={"transaction": order.payment_reference, "amount": amount_kobo},
            headers={
                "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )
    body = resp.json()
    return bool(body.get("status"))


async def _refund_flutterwave(order: Order, amount: Decimal) -> bool:
    if not order.payment_reference:
        return False

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.flutterwave.com/v3/transactions/{order.payment_reference}/refund",
            json={"amount": float(amount)},
            headers={
                "Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )
    body = resp.json()
    return body.get("status") == "success"


async def _refund_stripe(order: Order, amount: Decimal) -> bool:
    import stripe  # type: ignore

    payment_intent = order.payment_reference
    if not payment_intent:
        return False

    # Older orders may have stored the checkout session ID instead of the
    # payment intent - resolve it before attempting the refund.
    if payment_intent.startswith("cs_"):
        session = await asyncio.to_thread(
            stripe.checkout.Session.retrieve, payment_intent, api_key=settings.STRIPE_SECRET_KEY
        )
        payment_intent = session.payment_intent
        if not payment_intent:
            return False

    amount_cents = int(float(amount) * 100)

    def _create_refund():
        return stripe.Refund.create(
            payment_intent=payment_intent,
            amount=amount_cents,
            api_key=settings.STRIPE_SECRET_KEY,
        )

    refund = await asyncio.to_thread(_create_refund)
    return refund.status in ("succeeded", "pending")


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
