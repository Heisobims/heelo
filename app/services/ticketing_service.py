from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, or_, select, update
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
    OrderItemRequest,
    PromoCodeCreateRequest,
    RegisterRequest,
    TicketTypeCreateRequest,
    TicketTypeUpdateRequest,
    WaitlistJoinRequest,
)
from app.utils.auth import create_ticket_qr_token


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
            if data.applies_to_ticket_type_ids else None
        ),
    )
    db.add(ff)
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
            if data.applicable_ticket_type_ids else None
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

    now = datetime.now(timezone.utc)
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

    now = datetime.now(timezone.utc)
    for item in data.items:
        tt = tt_map.get(item.ticket_type_id)
        if not tt:
            raise HTTPException(404, "Ticket type not found or not available.")
        if tt.sale_start and tt.sale_start.tzinfo and now < tt.sale_start:
            raise HTTPException(400, f"'{tt.name}' tickets are not on sale yet.")
        if tt.sale_end and tt.sale_end.tzinfo and now > tt.sale_end:
            raise HTTPException(400, f"'{tt.name}' ticket sales have ended.")
        if item.quantity < tt.min_per_order:
            raise HTTPException(400, f"Minimum {tt.min_per_order} ticket(s) required for '{tt.name}'.")
        if item.quantity > tt.max_per_order:
            raise HTTPException(400, f"Maximum {tt.max_per_order} ticket(s) per order for '{tt.name}'.")

    promo, discount_amount = await resolve_promo(db, event.id, data.promo_code, data.items, tt_map)

    raw_total = sum(
        Decimal(str(tt_map[item.ticket_type_id].price)) * item.quantity
        for item in data.items
    )
    total_amount = max(Decimal("0"), raw_total - discount_amount)
    is_free = total_amount == Decimal("0")
    currency = tt_map[data.items[0].ticket_type_id].currency

    order_id = uuid.uuid4()
    order = Order(
        id=order_id,
        user_id=user_id,
        event_id=event.id,
        buyer_name=data.buyer_name,
        buyer_email=data.buyer_email.lower(),
        buyer_phone=data.buyer_phone,
        total_amount=float(total_amount),
        net_amount=float(total_amount),
        platform_fee=0.0,
        currency=currency,
        payment_provider="free" if is_free else None,
        payment_status="paid" if is_free else "pending",
        promo_code_id=promo.id if promo else None,
        discount_amount=float(discount_amount),
        utm_source=data.utm_source,
        utm_medium=data.utm_medium,
        utm_campaign=data.utm_campaign,
    )
    db.add(order)

    for item in data.items:
        tt = tt_map[item.ticket_type_id]
        unit_price = float(Decimal(str(tt.price)))
        db.add(OrderItem(
            order_id=order_id,
            ticket_type_id=item.ticket_type_id,
            quantity=item.quantity,
            unit_price=unit_price,
            subtotal=round(unit_price * item.quantity, 2),
        ))

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
                raise HTTPException(409, f"Not enough capacity for '{tt.name}'. Please select fewer tickets.")
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
                qr_code=qr_token,
                status="confirmed" if is_free else "pending",
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
            db.add(RegistrationAnswer(
                registration_id=registrations[0].id,
                field_id=field_id,
                value=str(value),
            ))

    if promo:
        promo.used_count += 1

    await db.commit()

    loaded = await db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.registrations))
    )

    # For free orders (already paid), send confirmation notifications immediately.
    # Paid orders are handled by payment_service.confirm_order() after payment verification.
    if loaded and loaded.payment_status == "paid":
        try:
            from app.tasks.email import send_registration_confirmation as _email_conf
            _email_conf.delay(str(loaded.id))
        except Exception:
            pass
        try:
            from app.tasks.whatsapp import send_registration_confirmation as _wa_conf
            _wa_conf.delay(str(loaded.id))
        except Exception:
            pass

    return loaded


async def get_order(db: AsyncSession, order_id: uuid.UUID) -> Order | None:
    return await db.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.registrations).selectinload(Registration.ticket_type)
        )
    )


async def get_registration_by_id(db: AsyncSession, reg_id: uuid.UUID) -> Registration | None:
    return await db.scalar(
        select(Registration)
        .where(Registration.id == reg_id)
        .options(selectinload(Registration.ticket_type))
    )


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
        stmt.order_by(Registration.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
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
        stmt.order_by(Registration.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
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
        await db.scalar(
            select(func.count()).where(Waitlist.ticket_type_id == data.ticket_type_id)
        ) or 0
    ) + 1

    wl = Waitlist(
        event_id=event_id,
        ticket_type_id=data.ticket_type_id,
        email=data.email.lower(),
        name=data.name,
        position=position,
    )
    db.add(wl)
    await db.commit()
    await db.refresh(wl)
    return wl
