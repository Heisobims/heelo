from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import structlog
from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ticketing import (
    Order,
    OrderItem,
    PromoCode,
    Registration,
    RegistrationAnswer,
    RegistrationFormField,
    TicketType,
    Waitlist,
)
from app.schemas.ticketing import (
    FormFieldCreateRequest,
    FormFieldUpdateRequest,
    OrderItemRequest,
    PromoCodeCreateRequest,
    RegisterRequest,
    TicketTypeCreateRequest,
    TicketTypeUpdateRequest,
    WaitlistJoinRequest,
)
from app.utils.auth import create_ticket_qr_token

logger = structlog.get_logger()

# ── Ticket Types ──────────────────────────────────────────────────────────────


async def get_ticket_types(
    db: AsyncSession,
    event_id: uuid.UUID,
    *,
    public_only: bool = False,
) -> list[TicketType]:
    stmt = select(TicketType).where(TicketType.event_id == event_id)
    if public_only:
        stmt = stmt.where(TicketType.is_visible == True)
    stmt = stmt.order_by(TicketType.sort_order, TicketType.created_at)
    result = await db.scalars(stmt)
    return list(result.all())


async def create_ticket_type(
    db: AsyncSession,
    event_id: uuid.UUID,
    data: TicketTypeCreateRequest,
) -> TicketType:
    tt = TicketType(
        event_id=event_id,
        name=data.name,
        description=data.description,
        price=float(data.price),
        currency=data.currency.upper(),
        quantity=data.quantity,
        tier=data.tier,
        sale_start=data.sale_start,
        sale_end=data.sale_end,
        max_per_order=data.max_per_order,
        min_per_order=data.min_per_order,
        is_visible=data.is_visible,
        sort_order=data.sort_order,
    )
    db.add(tt)
    await db.commit()
    await db.refresh(tt)
    return tt


async def copy_ticket_types(
    db: AsyncSession, source_event_id: uuid.UUID, target_event_id: uuid.UUID
) -> None:
    """
    Copy a source event's ticket type structure onto a target event - used by
    event duplication, "start from template", and recurring series generation.
    Copies pricing/tiers/limits only; never sales counters (quantity_sold /
    quantity_reserved always start at 0 on the new event).
    """
    source_tts = await get_ticket_types(db, source_event_id)
    for tt in source_tts:
        db.add(
            TicketType(
                event_id=target_event_id,
                name=tt.name,
                description=tt.description,
                price=tt.price,
                currency=tt.currency,
                quantity=tt.quantity,
                tier=tt.tier,
                sale_start=tt.sale_start,
                sale_end=tt.sale_end,
                max_per_order=tt.max_per_order,
                min_per_order=tt.min_per_order,
                is_visible=tt.is_visible,
                sort_order=tt.sort_order,
            )
        )
    await db.flush()


async def update_ticket_type(
    db: AsyncSession,
    tt: TicketType,
    data: TicketTypeUpdateRequest,
) -> TicketType:
    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if field == "price" and value is not None:
            value = float(value)
        if field == "currency" and value:
            value = value.upper()
        setattr(tt, field, value)
    await db.commit()
    await db.refresh(tt)
    return tt


async def delete_ticket_type(db: AsyncSession, tt: TicketType) -> None:
    if tt.quantity_sold > 0:
        raise HTTPException(400, "Cannot delete a ticket type that has sold tickets.")
    await db.delete(tt)
    await db.commit()


# ── Form Fields ───────────────────────────────────────────────────────────────


async def get_form_fields(
    db: AsyncSession,
    event_id: uuid.UUID,
) -> list[RegistrationFormField]:
    result = await db.scalars(
        select(RegistrationFormField)
        .where(RegistrationFormField.event_id == event_id)
        .order_by(RegistrationFormField.sort_order)
    )
    return list(result.all())


async def create_form_field(
    db: AsyncSession,
    event_id: uuid.UUID,
    data: FormFieldCreateRequest,
) -> RegistrationFormField:
    ff = RegistrationFormField(
        event_id=event_id,
        label=data.label,
        field_type=data.field_type,
        is_required=data.is_required,
        options=data.options,
        sort_order=data.sort_order,
        applies_to_ticket_type_ids=(
            [str(i) for i in data.applies_to_ticket_type_ids]
            if data.applies_to_ticket_type_ids
            else None
        ),
    )
    db.add(ff)
    await db.commit()
    await db.refresh(ff)
    return ff


async def update_form_field(
    db: AsyncSession, ff: RegistrationFormField, data: FormFieldUpdateRequest
) -> RegistrationFormField:
    updates = data.model_dump(exclude_unset=True)
    if "applies_to_ticket_type_ids" in updates:
        ids = updates["applies_to_ticket_type_ids"]
        updates["applies_to_ticket_type_ids"] = [str(i) for i in ids] if ids else None
    for field, value in updates.items():
        setattr(ff, field, value)
    await db.commit()
    await db.refresh(ff)
    return ff


async def delete_form_field(db: AsyncSession, ff: RegistrationFormField) -> None:
    await db.delete(ff)
    await db.commit()


# ── Promo Codes ───────────────────────────────────────────────────────────────


async def get_promo_codes(db: AsyncSession, event_id: uuid.UUID) -> list[PromoCode]:
    result = await db.scalars(
        select(PromoCode)
        .where(PromoCode.event_id == event_id)
        .order_by(PromoCode.created_at.desc())
    )
    return list(result.all())


async def create_promo_code(
    db: AsyncSession,
    event_id: uuid.UUID,
    data: PromoCodeCreateRequest,
) -> PromoCode:
    existing = await db.scalar(
        select(PromoCode).where(PromoCode.event_id == event_id, PromoCode.code == data.code)
    )
    if existing:
        raise HTTPException(409, f"Promo code '{data.code}' already exists for this event.")

    pc = PromoCode(
        event_id=event_id,
        code=data.code,
        discount_type=data.discount_type,
        discount_value=float(data.discount_value),
        max_uses=data.max_uses,
        expires_at=data.expires_at,
        is_active=True,
        applicable_ticket_type_ids=(
            [str(i) for i in data.applicable_ticket_type_ids]
            if data.applicable_ticket_type_ids
            else None
        ),
    )
    db.add(pc)
    await db.commit()
    await db.refresh(pc)
    return pc


async def delete_promo_code(db: AsyncSession, pc: PromoCode) -> None:
    await db.delete(pc)
    await db.commit()


# ── Promo resolution (shared by register + validate endpoint) ─────────────────


async def resolve_promo(
    db: AsyncSession,
    event_id: uuid.UUID,
    code: str | None,
    items: list[OrderItemRequest],
    tt_map: dict[uuid.UUID, TicketType],
) -> tuple[PromoCode | None, Decimal]:
    if not code:
        return None, Decimal("0")

    promo = await db.scalar(
        select(PromoCode).where(
            PromoCode.event_id == event_id,
            PromoCode.code == code.strip().upper(),
            PromoCode.is_active == True,
        )
    )
    if not promo:
        raise HTTPException(400, "Invalid promo code.")

    now = datetime.now(UTC)
    if promo.expires_at and now > promo.expires_at:
        raise HTTPException(400, "This promo code has expired.")
    if promo.max_uses is not None and promo.used_count >= promo.max_uses:
        raise HTTPException(400, "This promo code has reached its usage limit.")

    applicable_ids = set(promo.applicable_ticket_type_ids or [])
    subtotal = Decimal("0")
    for item in items:
        tt = tt_map.get(item.ticket_type_id)
        if not tt:
            continue
        if applicable_ids and str(item.ticket_type_id) not in applicable_ids:
            continue
        subtotal += Decimal(str(tt.price)) * item.quantity

    if promo.discount_type == "percent":
        discount = (subtotal * Decimal(str(promo.discount_value)) / 100).quantize(Decimal("0.01"))
    else:
        discount = min(Decimal(str(promo.discount_value)), subtotal)

    return promo, discount


# ── Registration ──────────────────────────────────────────────────────────────

# Discount applied to a friend's ticket when they register through another
# attendee's referral link. A business/pricing decision, not an engineering
# one: change this constant to adjust the incentive. The platform fee
# absorbs this discount first (see confirm_order in payment_service.py).
# This now equals PLATFORM_FEE_PERCENT exactly, so a referred order's fee
# floors at (or very near) 0 without the organizer absorbing anything;
# raising this above PLATFORM_FEE_PERCENT means the organizer starts
# absorbing the difference too, so keep that in mind before tuning it up.
REFERRAL_DISCOUNT_PERCENT = Decimal("0.05")


async def _resolve_referral(
    db: AsyncSession, event_id: uuid.UUID, referral_code: str | None, buyer_email: str
) -> str | None:
    """
    Validate a referral code (the referrer's own referral_token - a value
    distinct from their registration id, since that id is also the bare
    capability-token behind qr.png/badge.pdf/certificate.pdf and must never be
    something a shared link exposes) for this event. Returns the code itself
    if valid, else None - an unknown, wrong-event, or self-referral code just
    silently drops the discount rather than failing the whole registration.
    """
    if not referral_code:
        return None

    # Check if this matches an organizer promoter/affiliate code for this event
    from app.models.affiliate import EventAffiliate

    aff = await db.scalar(
        select(EventAffiliate).where(
            EventAffiliate.event_id == event_id,
            func.upper(EventAffiliate.affiliate_code) == referral_code.strip().upper(),
            EventAffiliate.is_active.is_(True),
        )
    )
    if aff:
        return aff.affiliate_code

    referrer = await db.scalar(
        select(Registration).where(
            Registration.referral_token == referral_code,
            Registration.event_id == event_id,
            Registration.status.in_(("confirmed", "checked_in")),
        )
    )
    if not referrer or referrer.attendee_email.lower() == buyer_email.lower():
        return None
    return referral_code


async def get_referral_stats(db: AsyncSession, registration_id: uuid.UUID) -> dict:
    """How many orders were referred by this attendee's link."""
    referrer_token = await db.scalar(
        select(Registration.referral_token).where(Registration.id == registration_id)
    )
    if not referrer_token:
        return {"referred_count": 0}
    count = await db.scalar(
        select(func.count(Order.id)).where(Order.referral_code == referrer_token)
    )
    return {"referred_count": count or 0}


async def register(
    db: AsyncSession,
    event,
    data: RegisterRequest,
    *,
    user_id: uuid.UUID | None = None,
) -> Order:
    if event.status not in ("published", "live"):
        raise HTTPException(400, "Registration is not open for this event.")

    tts = await get_ticket_types(db, event.id, public_only=True)
    tt_map = {tt.id: tt for tt in tts}

    now = datetime.now(UTC)
    for item in data.items:
        tt = tt_map.get(item.ticket_type_id)
        if not tt:
            raise HTTPException(404, "Ticket type not found or not available.")
        if tt.sale_start and tt.sale_start.tzinfo and now < tt.sale_start:
            raise HTTPException(400, f"'{tt.name}' tickets are not on sale yet.")
        if tt.sale_end and tt.sale_end.tzinfo and now > tt.sale_end:
            raise HTTPException(400, f"'{tt.name}' ticket sales have ended.")
        if item.quantity < tt.min_per_order:
            raise HTTPException(
                400, f"Minimum {tt.min_per_order} ticket(s) required for '{tt.name}'."
            )
        if item.quantity > tt.max_per_order:
            raise HTTPException(
                400, f"Maximum {tt.max_per_order} ticket(s) per order for '{tt.name}'."
            )

    if event.max_capacity is not None:
        # Best-effort, event-wide cap across all ticket types - a coarser
        # aggregate than the atomic per-ticket-type check below, so a narrow
        # TOCTOU window remains under heavy concurrent checkout at the exact
        # limit. Still far better than the previous behavior, where
        # max_capacity was silently never enforced at all.
        already_held = await db.scalar(
            select(
                func.coalesce(func.sum(TicketType.quantity_sold + TicketType.quantity_reserved), 0)
            ).where(TicketType.event_id == event.id)
        )
        requested = sum(item.quantity for item in data.items)
        if (already_held or 0) + requested > event.max_capacity:
            raise HTTPException(409, f"This event is at capacity ({event.max_capacity} spots).")

    promo, discount_amount = await resolve_promo(db, event.id, data.promo_code, data.items, tt_map)

    raw_total = sum(
        Decimal(str(tt_map[item.ticket_type_id].price)) * item.quantity for item in data.items
    )

    referrer_code = await _resolve_referral(db, event.id, data.referral_code, data.buyer_email)
    # Referral and promo-code discounts don't stack - a promo code takes
    # precedence if the buyer used both; the referral is still recorded for
    # attribution either way, it just doesn't also discount the order.
    referral_discount = (
        (raw_total * REFERRAL_DISCOUNT_PERCENT)
        if (referrer_code and discount_amount == Decimal("0"))
        else Decimal("0")
    )

    # subtotal is what the organizer must net - the ticket price they set,
    # in full.
    subtotal = max(Decimal("0"), raw_total - discount_amount - referral_discount)
    is_free = subtotal == Decimal("0")
    currency = tt_map[data.items[0].ticket_type_id].currency

    total_amount = subtotal
    platform_fee_amount = Decimal("0")
    gateway_fee_amount = Decimal("0")
    fees_passed_to_buyer = False
    net_amount = subtotal

    # Check whether fees are passed to the buyer (default) or absorbed by the organizer (inclusive pricing)
    if not is_free:
        from app.services.payment_service import (
            PLATFORM_FEE_PERCENT,
            gross_up_for_buyer_fees,
            select_provider,
        )

        pass_fees = getattr(event, "pass_fees_to_buyer", True)
        provider = select_provider(currency)

        if pass_fees:
            total_amount, platform_fee_amount, gateway_fee_amount = gross_up_for_buyer_fees(
                subtotal, provider
            )
            fees_passed_to_buyer = True
            net_amount = subtotal
        else:
            # Inclusive pricing: fees absorbed into the ticket price by organizer
            total_amount = subtotal
            fees_passed_to_buyer = False
            platform_fee_amount = (total_amount * PLATFORM_FEE_PERCENT).quantize(Decimal("0.01"))
            gateway_fee_amount = Decimal("0")
            net_amount = (total_amount - platform_fee_amount).quantize(Decimal("0.01"))

    order_id = uuid.uuid4()
    order = Order(
        id=order_id,
        user_id=user_id,
        event_id=event.id,
        buyer_name=data.buyer_name,
        buyer_email=data.buyer_email.lower(),
        buyer_phone=data.buyer_phone,
        whatsapp_consent=data.whatsapp_consent,
        total_amount=float(total_amount),
        net_amount=float(net_amount),
        # For passthrough orders, platform_fee records total - net (platform cut + gateway fee estimate).
        # For fee-absorbed orders, platform_fee is Heelo's flat 5% cut.
        platform_fee=float(
            platform_fee_amount + gateway_fee_amount
            if fees_passed_to_buyer
            else platform_fee_amount
        ),
        currency=currency,
        payment_provider="free" if is_free else None,
        payment_status="paid" if is_free else "pending",
        promo_code_id=promo.id if promo else None,
        discount_amount=float(discount_amount + referral_discount),
        referral_discount_amount=float(referral_discount),
        fees_passed_to_buyer=fees_passed_to_buyer,
        gateway_fee_amount=float(gateway_fee_amount),
        referral_code=referrer_code,
        utm_source=data.utm_source,
        utm_medium=data.utm_medium,
        utm_campaign=data.utm_campaign,
    )
    db.add(order)

    for item in data.items:
        tt = tt_map[item.ticket_type_id]
        unit_price = float(Decimal(str(tt.price)))
        db.add(
            OrderItem(
                order_id=order_id,
                ticket_type_id=item.ticket_type_id,
                quantity=item.quantity,
                unit_price=unit_price,
                subtotal=round(unit_price * item.quantity, 2),
            )
        )

    await db.flush()

    registrations: list[Registration] = []
    attendee_idx = 0

    for item in data.items:
        tt = tt_map[item.ticket_type_id]

        if tt.quantity is not None:
            if is_free:
                result = await db.execute(
                    update(TicketType)
                    .where(
                        TicketType.id == item.ticket_type_id,
                        TicketType.quantity_sold + TicketType.quantity_reserved + item.quantity
                        <= TicketType.quantity,
                    )
                    .values(quantity_sold=TicketType.quantity_sold + item.quantity)
                    .returning(TicketType.id)
                )
            else:
                result = await db.execute(
                    update(TicketType)
                    .where(
                        TicketType.id == item.ticket_type_id,
                        TicketType.quantity_sold + TicketType.quantity_reserved + item.quantity
                        <= TicketType.quantity,
                    )
                    .values(quantity_reserved=TicketType.quantity_reserved + item.quantity)
                    .returning(TicketType.id)
                )
            if result.fetchone() is None:
                await db.rollback()
                raise HTTPException(
                    409, f"Not enough capacity for '{tt.name}'. Please select fewer tickets."
                )
        else:
            if is_free:
                tt.quantity_sold = tt.quantity_sold + item.quantity
            else:
                tt.quantity_reserved = tt.quantity_reserved + item.quantity

        for _ in range(item.quantity):
            if data.attendees and attendee_idx < len(data.attendees):
                att = data.attendees[attendee_idx]
                att_name, att_email, att_phone = att.name, att.email.lower(), att.phone
            else:
                att_name = data.buyer_name
                att_email = data.buyer_email.lower()
                att_phone = data.buyer_phone

            reg_id = uuid.uuid4()
            qr_token = create_ticket_qr_token(str(reg_id), str(event.id))
            reg = Registration(
                id=reg_id,
                event_id=event.id,
                ticket_type_id=item.ticket_type_id,
                order_id=order_id,
                user_id=user_id,
                attendee_name=att_name,
                attendee_email=att_email,
                attendee_phone=att_phone,
                whatsapp_consent=data.whatsapp_consent,
                qr_code=qr_token,
                status="confirmed" if is_free else "pending",
                referral_token=secrets.token_urlsafe(12),
            )
            db.add(reg)
            registrations.append(reg)
            attendee_idx += 1

    if data.form_answers and registrations:
        for field_id_str, value in data.form_answers.items():
            try:
                field_id = uuid.UUID(field_id_str)
            except (ValueError, AttributeError):
                continue
            db.add(
                RegistrationAnswer(
                    registration_id=registrations[0].id,
                    field_id=field_id,
                    value=str(value),
                )
            )

    if promo:
        # Atomic conditional increment - a plain `promo.used_count += 1` here
        # would let two concurrent checkouts both read the same used_count
        # and both pass the max_uses check in resolve_promo() before either
        # commits, redeeming the code more times than allowed. Same pattern
        # as the per-ticket-type inventory check above.
        promo_result = await db.execute(
            update(PromoCode)
            .where(
                PromoCode.id == promo.id,
                or_(PromoCode.max_uses.is_(None), PromoCode.used_count < PromoCode.max_uses),
            )
            .values(used_count=PromoCode.used_count + 1)
            .returning(PromoCode.id)
        )
        if promo_result.fetchone() is None:
            await db.rollback()
            raise HTTPException(409, "This promo code has just reached its usage limit.")

    # Someone who was on the waitlist and just successfully registered has
    # claimed their spot - drop them from the queue so they don't get
    # re-notified or block the position count for people behind them.
    ticket_type_ids = {item.ticket_type_id for item in data.items}
    if ticket_type_ids:
        await db.execute(
            delete(Waitlist).where(
                Waitlist.ticket_type_id.in_(ticket_type_ids),
                Waitlist.email == data.buyer_email.lower(),
            )
        )

    await db.commit()

    loaded = await db.scalar(
        select(Order).where(Order.id == order_id).options(selectinload(Order.registrations))
    )

    # For free orders (already paid), send confirmation notifications immediately.
    # Paid orders are handled by payment_service.confirm_order() after payment verification.
    if loaded and loaded.payment_status == "paid":
        try:
            from app.tasks.email import send_registration_confirmation as _email_conf

            _email_conf.delay(str(loaded.id))
        except Exception as err:
            logger.warning(
                "ticketing.confirmation_email_enqueue_failed",
                order_id=str(loaded.id),
                error=str(err),
            )
        try:
            from app.tasks.whatsapp import send_registration_confirmation as _wa_conf

            _wa_conf.delay(str(loaded.id))
        except Exception as err:
            logger.warning(
                "ticketing.confirmation_whatsapp_enqueue_failed",
                order_id=str(loaded.id),
                error=str(err),
            )

    return loaded


async def get_order(db: AsyncSession, order_id: uuid.UUID) -> Order | None:
    return await db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.registrations).selectinload(Registration.ticket_type))
    )


async def get_registration_by_id(
    db: AsyncSession, reg_id: uuid.UUID, *, for_update: bool = False
) -> Registration | None:
    """
    `for_update` takes a row lock on the registration - use it before
    cancel_registration() so two near-simultaneous cancel requests for the
    same registration can't both pass the status check and both trigger a
    real refund. The second request blocks until the first transaction
    commits, then re-reads the now-updated status.
    """
    stmt = (
        select(Registration)
        .where(Registration.id == reg_id)
        .options(
            selectinload(Registration.ticket_type),
            selectinload(Registration.event),
            selectinload(Registration.order).selectinload(Order.registrations),
        )
    )
    if for_update:
        stmt = stmt.with_for_update(of=Registration)
    return await db.scalar(stmt)


async def cancel_registration(
    db: AsyncSession,
    reg: Registration,
    *,
    refund: bool,
    cancelled_by: str,
) -> Registration:
    """
    Cancel a confirmed/checked-in registration: optionally refund the payment,
    release the ticket capacity it held, and offer the freed spot to the next
    waitlisted person.

    `cancelled_by` is "organizer" or "attendee" - used only for notification copy.
    """
    if reg.status not in ("confirmed", "checked_in"):
        raise HTTPException(400, f"Registration is '{reg.status}' and cannot be cancelled.")

    tt = reg.ticket_type
    order = reg.order

    refunded = False
    if refund and order and order.payment_status in ("paid", "partially_refunded") and tt.price > 0:
        from app.services import payment_service as pay_svc

        refunded = await pay_svc.refund_order_item(order, Decimal(str(tt.price)))
        if not refunded:
            raise HTTPException(
                502,
                "Refund failed via the payment provider. Please try again, or refund manually "
                "from your Paystack/Flutterwave/Stripe dashboard.",
            )

    reg.status = "refunded" if refunded else "cancelled"

    if tt.quantity is not None:
        await db.execute(
            update(TicketType)
            .where(TicketType.id == tt.id)
            .values(quantity_sold=func.greatest(TicketType.quantity_sold - 1, 0))
        )
    else:
        tt.quantity_sold = max(0, tt.quantity_sold - 1)

    if order:
        sibling_statuses = [r.status for r in order.registrations if r.id != reg.id]
        if refunded:
            order.refunded_amount = float(order.refunded_amount or 0) + float(tt.price)
            # Reverse our cut on the refunded portion too - the platform shouldn't
            # keep a fee on money that was given back. Proportional to how the fee
            # was originally computed (a flat % of gross), not the whole order's fee.
            fee_reversed = float(tt.price) * float(pay_svc.PLATFORM_FEE_PERCENT)
            order.platform_fee = max(0.0, float(order.platform_fee or 0) - fee_reversed)
            order.net_amount = float(order.net_amount or 0) + fee_reversed
            order.payment_status = (
                "refunded"
                if all(s in ("cancelled", "refunded") for s in sibling_statuses)
                else "partially_refunded"
            )

    await db.commit()
    await db.refresh(reg)

    try:
        from app.tasks.email import send_registration_cancellation as _email_cancel

        _email_cancel.delay(str(reg.id), cancelled_by)
    except Exception as err:
        logger.warning(
            "ticketing.cancellation_email_enqueue_failed",
            registration_id=str(reg.id),
            error=str(err),
        )
    try:
        from app.tasks.whatsapp import send_registration_cancellation as _wa_cancel

        _wa_cancel.delay(str(reg.id))
    except Exception as err:
        logger.warning(
            "ticketing.cancellation_whatsapp_enqueue_failed",
            registration_id=str(reg.id),
            error=str(err),
        )

    await notify_next_waitlist_entry(db, tt.id)

    return reg


# ── Ticket transfer ──────────────────────────────────────────────────────────
#
# Two-step, claim-link flow (matches the transfer_token/transfer_expires_at
# columns already on Registration): the current holder generates a shareable
# link, and whoever opens it fills in *their own* details to claim the ticket
# - the holder doesn't need to know the recipient's email up front. The
# original registration is locked (status="transfer_pending") the moment a
# transfer is initiated, not when it's claimed, so the original holder can't
# also check in while a transfer is outstanding.

_TRANSFER_EXPIRE_DAYS = 7


async def initiate_transfer(db: AsyncSession, reg: Registration) -> Registration:
    if reg.status != "confirmed":
        raise HTTPException(
            400, f"Registration is '{reg.status}': only a confirmed ticket can be transferred."
        )
    reg.status = "transfer_pending"
    reg.transfer_token = secrets.token_urlsafe(24)
    reg.transfer_expires_at = datetime.now(UTC) + timedelta(days=_TRANSFER_EXPIRE_DAYS)
    await db.commit()
    await db.refresh(reg)
    return reg


async def cancel_transfer(db: AsyncSession, reg: Registration) -> Registration:
    if reg.status != "transfer_pending":
        raise HTTPException(400, "This registration doesn't have a pending transfer.")
    reg.status = "confirmed"
    reg.transfer_token = None
    reg.transfer_expires_at = None
    await db.commit()
    await db.refresh(reg)
    return reg


async def get_registration_by_transfer_token(db: AsyncSession, token: str) -> Registration | None:
    reg = await db.scalar(
        select(Registration)
        .where(Registration.transfer_token == token)
        .options(
            selectinload(Registration.event),
            selectinload(Registration.ticket_type),
        )
    )
    if not reg or reg.status != "transfer_pending":
        return None
    if reg.transfer_expires_at and reg.transfer_expires_at < datetime.now(UTC):
        return None
    return reg


async def claim_transfer(
    db: AsyncSession,
    token: str,
    *,
    new_name: str,
    new_email: str,
    new_phone: str | None,
) -> Registration:
    original = await get_registration_by_transfer_token(db, token)
    if not original:
        raise HTTPException(400, "This transfer link is invalid or has expired.")

    # Atomic claim: two concurrent submissions of the same link (double-click,
    # or the link forwarded to two people) must not both pass the read-only
    # check above and each mint a new registration. Flip the original to
    # "claiming" first - only the request that actually wins this update may
    # proceed to create the new registration.
    claim = await db.execute(
        update(Registration)
        .where(Registration.id == original.id, Registration.status == "transfer_pending")
        .values(status="claiming")
        .returning(Registration.id)
    )
    if claim.fetchone() is None:
        await db.rollback()
        raise HTTPException(400, "This transfer link has already been used.")

    new_reg_id = uuid.uuid4()
    qr_token = create_ticket_qr_token(str(new_reg_id), str(original.event_id))
    new_reg = Registration(
        id=new_reg_id,
        event_id=original.event_id,
        ticket_type_id=original.ticket_type_id,
        order_id=original.order_id,
        attendee_name=new_name,
        attendee_email=new_email.lower(),
        attendee_phone=new_phone,
        qr_code=qr_token,
        status="confirmed",
        transferred_from_id=original.id,
        referral_token=secrets.token_urlsafe(12),
    )
    db.add(new_reg)

    original.status = "transferred"
    original.transfer_token = None  # single-use - the link can't be replayed
    original.transfer_expires_at = None

    await db.commit()
    await db.refresh(new_reg)

    try:
        from app.tasks.email import send_ticket_transfer_confirmation as _email_transfer

        _email_transfer.delay(str(new_reg.id))
    except Exception as err:
        logger.warning(
            "ticketing.transfer_confirmation_email_enqueue_failed",
            registration_id=str(new_reg.id),
            error=str(err),
        )

    return new_reg


async def notify_next_waitlist_entry(
    db: AsyncSession, ticket_type_id: uuid.UUID
) -> Waitlist | None:
    """Offer a just-freed spot to the next un-notified person on the waitlist -
    called automatically when a registration is cancelled, and available for an
    organizer to trigger manually (e.g. after raising capacity by hand)."""
    next_wl = await db.scalar(
        select(Waitlist)
        .where(Waitlist.ticket_type_id == ticket_type_id, Waitlist.notified_at.is_(None))
        .order_by(Waitlist.position)
        .limit(1)
    )
    if not next_wl:
        return None

    next_wl.notified_at = datetime.now(UTC)
    next_wl.offer_expires_at = datetime.now(UTC) + timedelta(hours=24)
    await db.commit()

    try:
        from app.tasks.email import send_waitlist_notification as _email_wl

        _email_wl.delay(str(next_wl.id))
    except Exception as err:
        logger.warning(
            "ticketing.waitlist_email_enqueue_failed", waitlist_id=str(next_wl.id), error=str(err)
        )
    try:
        from app.tasks.whatsapp import send_waitlist_notification as _wa_wl

        _wa_wl.delay(str(next_wl.id))
    except Exception as err:
        logger.warning(
            "ticketing.waitlist_whatsapp_enqueue_failed",
            waitlist_id=str(next_wl.id),
            error=str(err),
        )

    return next_wl


async def list_registrations(
    db: AsyncSession,
    event_id: uuid.UUID,
    *,
    page: int = 1,
    per_page: int = 50,
    status: str | None = None,
) -> tuple[list[Registration], int]:
    stmt = (
        select(Registration)
        .where(Registration.event_id == event_id)
        .options(selectinload(Registration.ticket_type))
    )
    if status:
        stmt = stmt.where(Registration.status == status)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    result = await db.scalars(
        stmt.order_by(Registration.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    return list(result.all()), total


async def get_user_registrations(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    email: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[Registration], int]:
    conditions = []
    if user_id:
        conditions.append(Registration.user_id == user_id)
    if email:
        conditions.append(Registration.attendee_email == email.lower())
    if not conditions:
        return [], 0

    stmt = (
        select(Registration)
        .where(or_(*conditions))
        .where(Registration.status.notin_(["cancelled", "refunded"]))
        .options(
            selectinload(Registration.event),
            selectinload(Registration.ticket_type),
        )
    )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    result = await db.scalars(
        stmt.order_by(Registration.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    return list(result.all()), total


async def join_waitlist(
    db: AsyncSession,
    event_id: uuid.UUID,
    data: WaitlistJoinRequest,
) -> Waitlist:
    existing = await db.scalar(
        select(Waitlist).where(
            Waitlist.ticket_type_id == data.ticket_type_id,
            Waitlist.email == data.email.lower(),
        )
    )
    if existing:
        raise HTTPException(409, "You are already on the waitlist for this ticket type.")

    position = (
        await db.scalar(select(func.count()).where(Waitlist.ticket_type_id == data.ticket_type_id))
        or 0
    ) + 1

    wl = Waitlist(
        event_id=event_id,
        ticket_type_id=data.ticket_type_id,
        email=data.email.lower(),
        phone=data.phone or None,
        name=data.name,
        position=position,
    )
    db.add(wl)
    await db.commit()
    await db.refresh(wl)
    return wl


async def list_waitlist(db: AsyncSession, event_id: uuid.UUID) -> list[Waitlist]:
    stmt = (
        select(Waitlist)
        .where(Waitlist.event_id == event_id)
        .options(selectinload(Waitlist.ticket_type))
        .order_by(Waitlist.ticket_type_id, Waitlist.position)
    )
    result = await db.scalars(stmt)
    return list(result.all())


async def get_waitlist_entry(
    db: AsyncSession, event_id: uuid.UUID, waitlist_id: uuid.UUID
) -> Waitlist:
    entry = await db.scalar(
        select(Waitlist).where(Waitlist.id == waitlist_id, Waitlist.event_id == event_id)
    )
    if not entry:
        raise HTTPException(404, "Waitlist entry not found.")
    return entry


async def remove_from_waitlist(db: AsyncSession, entry: Waitlist) -> None:
    """Remove a person from the waitlist and close the gap in `position` for
    everyone behind them on the same ticket type's queue."""
    ticket_type_id = entry.ticket_type_id
    removed_position = entry.position
    await db.delete(entry)
    await db.execute(
        update(Waitlist)
        .where(
            Waitlist.ticket_type_id == ticket_type_id,
            Waitlist.position > removed_position,
        )
        .values(position=Waitlist.position - 1)
    )
    await db.commit()
