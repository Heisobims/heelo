from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import select

from app import plans
from app.dependencies import CurrentUser, DBSession, OrgAccess
from app.models.ticketing import PromoCode, TicketType
from app.permissions import Permission, require_permission
from app.schemas.ticketing import (
    FormFieldCreateRequest,
    FormFieldOut,
    FormFieldUpdateRequest,
    OrderOut,
    PromoCodeCreateRequest,
    PromoCodeOut,
    PromoValidateRequest,
    PromoValidateResponse,
    RegisterRequest,
    TicketTypeCreateRequest,
    TicketTypeOut,
    TicketTypeUpdateRequest,
    WaitlistJoinRequest,
    WaitlistOut,
)
from app.services import checkin_service as ci_svc
from app.services import ticketing_service as tk_svc
from app.utils.calendar_file import build_ics
from app.utils.qr_code import generate_qr_png

# ── Organizer API (under org/event scope) ─────────────────────────────────────

TicketingManageAccess = Annotated[tuple, Depends(require_permission(Permission.TICKETING_MANAGE))]
RegistrationsManageAccess = Annotated[
    tuple, Depends(require_permission(Permission.REGISTRATIONS_MANAGE))
]

router_org = APIRouter(
    prefix="/api/v1/organizations/{slug}/events/{event_id}",
    tags=["ticketing-organizer"],
)


async def _get_event_for_org(db, event_id: str, org_id: uuid.UUID):
    from app.models.event import Event

    try:
        eid = uuid.UUID(event_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid event ID.") from err
    event = await db.scalar(select(Event).where(Event.id == eid, Event.org_id == org_id))
    if not event:
        raise HTTPException(404, "Event not found.")
    return event


# Ticket types
@router_org.get("/ticket-types", response_model=list[TicketTypeOut])
async def list_ticket_types(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    return await tk_svc.get_ticket_types(db, event.id)


@router_org.post("/ticket-types", response_model=TicketTypeOut, status_code=201)
async def create_ticket_type(
    slug: str,
    event_id: str,
    data: TicketTypeCreateRequest,
    db: DBSession,
    org_access: TicketingManageAccess,
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    return await tk_svc.create_ticket_type(db, event.id, data)


@router_org.patch("/ticket-types/{tt_id}", response_model=TicketTypeOut)
async def update_ticket_type(
    slug: str,
    event_id: str,
    tt_id: str,
    data: TicketTypeUpdateRequest,
    db: DBSession,
    org_access: TicketingManageAccess,
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    try:
        tid = uuid.UUID(tt_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid ticket type ID.") from err
    tt = await db.scalar(
        select(TicketType).where(TicketType.id == tid, TicketType.event_id == event.id)
    )
    if not tt:
        raise HTTPException(404, "Ticket type not found.")
    return await tk_svc.update_ticket_type(db, tt, data)


@router_org.delete("/ticket-types/{tt_id}", status_code=204)
async def delete_ticket_type(
    slug: str, event_id: str, tt_id: str, db: DBSession, org_access: TicketingManageAccess
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    try:
        tid = uuid.UUID(tt_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid ticket type ID.") from err
    tt = await db.scalar(
        select(TicketType).where(TicketType.id == tid, TicketType.event_id == event.id)
    )
    if not tt:
        raise HTTPException(404, "Ticket type not found.")
    await tk_svc.delete_ticket_type(db, tt)


@router_org.post("/ticket-types/{tt_id}/toggle-visibility", response_model=TicketTypeOut)
async def toggle_visibility(
    slug: str, event_id: str, tt_id: str, db: DBSession, org_access: TicketingManageAccess
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    try:
        tid = uuid.UUID(tt_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid ticket type ID.") from err
    tt = await db.scalar(
        select(TicketType).where(TicketType.id == tid, TicketType.event_id == event.id)
    )
    if not tt:
        raise HTTPException(404, "Ticket type not found.")
    tt.is_visible = not tt.is_visible
    await db.commit()
    await db.refresh(tt)
    return tt


# Form fields
@router_org.get("/form-fields", response_model=list[FormFieldOut])
async def list_form_fields(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    return await tk_svc.get_form_fields(db, event.id)


@router_org.post("/form-fields", response_model=FormFieldOut, status_code=201)
async def create_form_field(
    slug: str,
    event_id: str,
    data: FormFieldCreateRequest,
    db: DBSession,
    org_access: TicketingManageAccess,
):
    org, role, is_owner = org_access
    plans.require_feature(org.plan, plans.PlanFeature.CUSTOM_FORM_FIELDS)
    event = await _get_event_for_org(db, event_id, org.id)
    return await tk_svc.create_form_field(db, event.id, data)


@router_org.patch("/form-fields/{ff_id}", response_model=FormFieldOut)
async def update_form_field(
    slug: str,
    event_id: str,
    ff_id: str,
    data: FormFieldUpdateRequest,
    db: DBSession,
    org_access: TicketingManageAccess,
):
    from app.models.ticketing import RegistrationFormField

    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    ff = await db.scalar(
        select(RegistrationFormField).where(
            RegistrationFormField.id == uuid.UUID(ff_id),
            RegistrationFormField.event_id == event.id,
        )
    )
    if not ff:
        raise HTTPException(404, "Form field not found.")
    return await tk_svc.update_form_field(db, ff, data)


@router_org.delete("/form-fields/{ff_id}", status_code=204)
async def delete_form_field(
    slug: str, event_id: str, ff_id: str, db: DBSession, org_access: TicketingManageAccess
):
    from app.models.ticketing import RegistrationFormField

    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    ff = await db.scalar(
        select(RegistrationFormField).where(
            RegistrationFormField.id == uuid.UUID(ff_id),
            RegistrationFormField.event_id == event.id,
        )
    )
    if not ff:
        raise HTTPException(404, "Form field not found.")
    await tk_svc.delete_form_field(db, ff)


# Promo codes
@router_org.get("/promo-codes", response_model=list[PromoCodeOut])
async def list_promo_codes(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    return await tk_svc.get_promo_codes(db, event.id)


@router_org.post("/promo-codes", response_model=PromoCodeOut, status_code=201)
async def create_promo_code(
    slug: str,
    event_id: str,
    data: PromoCodeCreateRequest,
    db: DBSession,
    org_access: TicketingManageAccess,
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    await plans.check_active_promo_code_limit(db, org.id, event.id, org.plan)
    return await tk_svc.create_promo_code(db, event.id, data)


@router_org.delete("/promo-codes/{pc_id}", status_code=204)
async def delete_promo_code(
    slug: str, event_id: str, pc_id: str, db: DBSession, org_access: TicketingManageAccess
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    pc = await db.scalar(
        select(PromoCode).where(PromoCode.id == uuid.UUID(pc_id), PromoCode.event_id == event.id)
    )
    if not pc:
        raise HTTPException(404, "Promo code not found.")
    await tk_svc.delete_promo_code(db, pc)


# Registrations
@router_org.get("/registrations")
async def list_registrations(
    slug: str,
    event_id: str,
    db: DBSession,
    org_access: OrgAccess,
    page: int = 1,
    status: str | None = None,
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    items, total = await tk_svc.list_registrations(db, event.id, page=page, status=status)
    return {
        "success": True,
        "data": {
            "items": [
                {
                    "id": str(r.id),
                    "attendee_name": r.attendee_name,
                    "attendee_email": r.attendee_email,
                    "attendee_phone": r.attendee_phone,
                    "ticket_type": r.ticket_type.name if r.ticket_type else None,
                    "status": r.status,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "checked_in_at": r.checked_in_at.isoformat() if r.checked_in_at else None,
                }
                for r in items
            ],
            "total": total,
            "page": page,
        },
    }


class CancelRegistrationRequest(BaseModel):
    refund: bool = True


@router_org.post("/registrations/{reg_id}/cancel")
async def cancel_registration(
    slug: str,
    event_id: str,
    reg_id: str,
    body: CancelRegistrationRequest,
    db: DBSession,
    org_access: RegistrationsManageAccess,
):
    org, role, is_owner = org_access

    event = await _get_event_for_org(db, event_id, org.id)

    try:
        rid = uuid.UUID(reg_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid registration ID.") from err

    reg = await tk_svc.get_registration_by_id(db, rid, for_update=True)
    if not reg or reg.event_id != event.id:
        raise HTTPException(404, "Registration not found.")

    reg = await tk_svc.cancel_registration(db, reg, refund=body.refund, cancelled_by="organizer")
    return {"success": True, "data": {"id": str(reg.id), "status": reg.status}}


def _waitlist_out(entry) -> dict:
    return WaitlistOut(
        id=entry.id,
        ticket_type_id=entry.ticket_type_id,
        ticket_type_name=entry.ticket_type.name if entry.ticket_type else None,
        name=entry.name,
        email=entry.email,
        phone=entry.phone,
        position=entry.position,
        notified_at=entry.notified_at,
        offer_expires_at=entry.offer_expires_at,
        created_at=entry.created_at,
    ).model_dump(mode="json")


@router_org.get("/waitlist")
async def list_waitlist(slug: str, event_id: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    entries = await tk_svc.list_waitlist(db, event.id)
    return {"success": True, "data": [_waitlist_out(e) for e in entries]}


@router_org.delete("/waitlist/{waitlist_id}", status_code=204)
async def remove_waitlist_entry(
    slug: str, event_id: str, waitlist_id: str, db: DBSession, org_access: RegistrationsManageAccess
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    try:
        wid = uuid.UUID(waitlist_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid waitlist entry ID.") from err
    entry = await tk_svc.get_waitlist_entry(db, event.id, wid)
    await tk_svc.remove_from_waitlist(db, entry)


@router_org.post("/ticket-types/{tt_id}/waitlist/notify-next")
async def notify_next_waitlist(
    slug: str, event_id: str, tt_id: str, db: DBSession, org_access: RegistrationsManageAccess
):
    org, role, is_owner = org_access
    event = await _get_event_for_org(db, event_id, org.id)
    try:
        ttid = uuid.UUID(tt_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid ticket type ID.") from err

    tt = await db.scalar(
        select(TicketType).where(TicketType.id == ttid, TicketType.event_id == event.id)
    )
    if not tt:
        raise HTTPException(404, "Ticket type not found.")

    entry = await tk_svc.notify_next_waitlist_entry(db, ttid)
    if not entry:
        return {"success": True, "data": None, "message": "Nobody is waiting for this ticket type."}
    return {"success": True, "data": _waitlist_out(entry)}


# ── Public API ────────────────────────────────────────────────────────────────

router_public = APIRouter(prefix="/api/v1/events", tags=["ticketing-public"])


async def _get_public_event(db, event_slug: str):
    from app.models.event import Event

    event = await db.scalar(
        select(Event).where(Event.slug == event_slug, Event.deleted_at.is_(None))
    )
    if not event or event.status == "draft":
        raise HTTPException(404, "Event not found.")
    return event


@router_public.get("/{event_slug}/ticket-types", response_model=list[TicketTypeOut])
async def public_ticket_types(event_slug: str, db: DBSession):
    event = await _get_public_event(db, event_slug)
    return await tk_svc.get_ticket_types(db, event.id, public_only=True)


@router_public.post("/{event_slug}/register")
async def register_for_event(
    event_slug: str,
    data: RegisterRequest,
    db: DBSession,
    request: Request,
):
    from jose import JWTError

    from app.utils.auth import decode_access_token

    user_id: uuid.UUID | None = None
    token = request.cookies.get("heelo_access")
    if token:
        try:
            payload = decode_access_token(token)
            user_id = uuid.UUID(payload["sub"])
        except (JWTError, KeyError, ValueError):
            pass

    event = await _get_public_event(db, event_slug)
    if event.status not in ("published", "live"):
        raise HTTPException(400, "Registration is not open for this event.")

    order = await tk_svc.register(db, event, data, user_id=user_id)
    order_out = OrderOut.model_validate(order)

    if order.payment_status == "pending":
        from app.models.organization import Organization
        from app.services import payment_service as pay_svc

        org = await db.scalar(select(Organization).where(Organization.id == event.org_id))
        try:
            order_out.payment_url = await pay_svc.initialize_payment(db, order, event, org)
        except HTTPException:
            # Surface payment init failures as a field on the response, not a 5xx -
            # the order is already created; the attendee can retry via confirmation page.
            order_out.payment_url = None

    return {"success": True, "data": order_out.model_dump()}


@router_public.post("/{event_slug}/promo-codes/validate", response_model=PromoValidateResponse)
async def validate_promo_code(event_slug: str, data: PromoValidateRequest, db: DBSession):
    event = await _get_public_event(db, event_slug)
    tts = await tk_svc.get_ticket_types(db, event.id, public_only=True)
    tt_map = {tt.id: tt for tt in tts}

    try:
        promo, discount = await tk_svc.resolve_promo(db, event.id, data.code, data.items, tt_map)
    except HTTPException as exc:
        return PromoValidateResponse(valid=False, message=exc.detail)

    if not promo:
        return PromoValidateResponse(valid=False, message="Invalid promo code.")

    return PromoValidateResponse(
        valid=True,
        discount_type=promo.discount_type,
        discount_value=Decimal(str(promo.discount_value)),
        discount_amount=discount,
        message="Promo code applied successfully.",
    )


@router_public.post("/{event_slug}/waitlist", status_code=201)
async def join_event_waitlist(event_slug: str, data: WaitlistJoinRequest, db: DBSession):
    event = await _get_public_event(db, event_slug)
    wl = await tk_svc.join_waitlist(db, event.id, data)
    return {"success": True, "data": {"position": wl.position}}


# ── Registration resources ────────────────────────────────────────────────────

router_registrations = APIRouter(prefix="/api/v1/registrations", tags=["registrations"])


@router_registrations.get("/{registration_id}/qr.png")
async def registration_qr_image(registration_id: str, db: DBSession):
    try:
        reg_id = uuid.UUID(registration_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid registration ID.") from err

    reg = await tk_svc.get_registration_by_id(db, reg_id)
    if not reg:
        raise HTTPException(404, "Registration not found.")
    if reg.status not in ("confirmed", "checked_in"):
        raise HTTPException(403, "Ticket is not confirmed.")

    qr_bytes = generate_qr_png(reg.qr_code)
    return Response(
        content=qr_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


@router_registrations.get("/{registration_id}/calendar.ics")
async def registration_calendar_ics(registration_id: str, db: DBSession):
    try:
        reg_id = uuid.UUID(registration_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid registration ID.") from err

    reg = await tk_svc.get_registration_by_id(db, reg_id)
    if not reg:
        raise HTTPException(404, "Registration not found.")
    if reg.status not in ("confirmed", "checked_in"):
        raise HTTPException(403, "Ticket is not confirmed.")
    if not reg.event:
        raise HTTPException(404, "Event not found.")

    ics_bytes = build_ics(reg.event, uid=reg.id)
    return Response(
        content=ics_bytes,
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{reg.event.slug}.ics"'},
    )


@router_registrations.get("/{registration_id}/join")
async def join_virtual_event(registration_id: str, db: DBSession):
    """
    The actual link attendees click from reminder emails/WhatsApp for virtual and
    hybrid events. Records a lightweight "attendee opened this link" attendance
    signal (reusing check-in, so virtual events show up in the same analytics
    in-person events already get) before bouncing straight to the real meeting URL.
    """
    try:
        reg_id = uuid.UUID(registration_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid registration ID.") from err

    reg = await ci_svc.mark_virtual_join(db, reg_id)
    if not reg or not reg.event:
        raise HTTPException(404, "Registration not found.")

    if reg.event.virtual_url:
        return RedirectResponse(reg.event.virtual_url)
    return RedirectResponse(f"/e/{reg.event.slug}")


@router_registrations.get("/{registration_id}/referral-stats")
async def registration_referral_stats(registration_id: str, db: DBSession):
    """
    Powers the "bring a friend" card on an attendee's ticket page - their
    shareable link and how many people have registered through it so far.
    """
    try:
        reg_id = uuid.UUID(registration_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid registration ID.") from err

    reg = await tk_svc.get_registration_by_id(db, reg_id)
    if not reg or not reg.event:
        raise HTTPException(404, "Registration not found.")

    stats = await tk_svc.get_referral_stats(db, reg_id)
    return {
        "success": True,
        "data": {
            "referral_path": f"/e/{reg.event.slug}?ref={reg.referral_token}",
            "referred_count": stats["referred_count"],
            "discount_percent": float(tk_svc.REFERRAL_DISCOUNT_PERCENT) * 100,
        },
    }


@router_registrations.post("/{registration_id}/cancel")
async def cancel_my_registration(
    registration_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    """Attendee self-service cancellation of their own ticket."""
    try:
        reg_id = uuid.UUID(registration_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid registration ID.") from err

    reg = await tk_svc.get_registration_by_id(db, reg_id, for_update=True)
    if not reg:
        raise HTTPException(404, "Registration not found.")

    owns_ticket = str(reg.user_id) == str(current_user.id) or (
        reg.attendee_email and reg.attendee_email.lower() == current_user.email.lower()
    )
    if not owns_ticket:
        raise HTTPException(403, "This isn't your ticket.")

    reg = await tk_svc.cancel_registration(db, reg, refund=True, cancelled_by="attendee")
    return {"success": True, "data": {"id": str(reg.id), "status": reg.status}}


# ── Ticket transfer ────────────────────────────────────────────────────────────


class ClaimTransferRequest(BaseModel):
    name: str
    email: str
    phone: str | None = None


@router_registrations.post("/{registration_id}/transfer")
async def transfer_my_registration(
    registration_id: str,
    db: DBSession,
    current_user: CurrentUser,
    request: Request,
):
    """Attendee-initiated - generates a shareable claim link for someone
    else to take over this ticket. Locks the ticket (can't be checked in)
    until the transfer is claimed or cancelled."""
    try:
        reg_id = uuid.UUID(registration_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid registration ID.") from err

    reg = await tk_svc.get_registration_by_id(db, reg_id, for_update=True)
    if not reg:
        raise HTTPException(404, "Registration not found.")

    owns_ticket = str(reg.user_id) == str(current_user.id) or (
        reg.attendee_email and reg.attendee_email.lower() == current_user.email.lower()
    )
    if not owns_ticket:
        raise HTTPException(403, "This isn't your ticket.")

    reg = await tk_svc.initiate_transfer(db, reg)
    transfer_url = f"{str(request.base_url).rstrip('/')}/transfer/{reg.transfer_token}"
    return {
        "success": True,
        "data": {
            "id": str(reg.id),
            "status": reg.status,
            "transfer_url": transfer_url,
            "expires_at": reg.transfer_expires_at,
        },
    }


@router_registrations.post("/{registration_id}/transfer/cancel")
async def cancel_my_transfer(
    registration_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    """Revoke an unclaimed transfer link and restore the ticket."""
    try:
        reg_id = uuid.UUID(registration_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid registration ID.") from err

    reg = await tk_svc.get_registration_by_id(db, reg_id, for_update=True)
    if not reg:
        raise HTTPException(404, "Registration not found.")

    owns_ticket = str(reg.user_id) == str(current_user.id) or (
        reg.attendee_email and reg.attendee_email.lower() == current_user.email.lower()
    )
    if not owns_ticket:
        raise HTTPException(403, "This isn't your ticket.")

    reg = await tk_svc.cancel_transfer(db, reg)
    return {"success": True, "data": {"id": str(reg.id), "status": reg.status}}


@router_registrations.get("/transfer/{token}")
async def get_transfer_details(token: str, db: DBSession):
    """Public, unauthenticated - the claim link itself is the capability,
    same pattern as qr.png/badge.pdf. Lets the claim page show what's being
    transferred before the recipient fills in their details."""
    reg = await tk_svc.get_registration_by_transfer_token(db, token)
    if not reg:
        raise HTTPException(404, "This transfer link is invalid or has expired.")
    return {
        "success": True,
        "data": {
            "event_title": reg.event.title if reg.event else "",
            "ticket_type": reg.ticket_type.name if reg.ticket_type else "General",
            "from_attendee_name": reg.attendee_name,
            "expires_at": reg.transfer_expires_at,
        },
    }


@router_registrations.post("/transfer/{token}/claim")
async def claim_transfer(token: str, body: ClaimTransferRequest, db: DBSession):
    """Public, unauthenticated - same capability-URL reasoning as above."""
    new_reg = await tk_svc.claim_transfer(
        db, token, new_name=body.name, new_email=body.email, new_phone=body.phone
    )
    return {"success": True, "data": {"id": str(new_reg.id), "status": new_reg.status}}
