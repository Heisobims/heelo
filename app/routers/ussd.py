"""
Africa's Talking USSD callback handler for Heelo check-in via mobile shortcode.

Flow:
  *XXX# → CON Welcome! Enter your phone-linked check-in.
         → Looks up attendee phone number against active registrations.
         → Shows active events; attendee selects or auto-selects.
         → Checks in. Confirms via USSD end message.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import DBSession
from app.services import checkin_service as ci_svc

router_ussd = APIRouter(prefix="/api/v1/ussd", tags=["ussd"])


def _normalize_phone(phone: str) -> str:
    """Strip everything except digits and return the last 10 digits."""
    digits = "".join(c for c in phone if c.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


@router_ussd.post("/checkin", response_class=PlainTextResponse)
async def ussd_checkin_handler(
    request: Request,
    db: DBSession,
    sessionId: str = Form(...),
    serviceCode: str = Form(...),
    phoneNumber: str = Form(...),
    text: str = Form(""),
    networkCode: str = Form(""),
):
    """Africa's Talking USSD gateway callback."""
    parts = text.split("*") if text else []
    step = len(parts)

    phone_last10 = _normalize_phone(phoneNumber)

    # ── Step 0: first dial ────────────────────────────────────────────────────
    if step == 0 or text == "":
        registrations = await ci_svc.find_by_phone(db, phone_last10=phone_last10)
        if not registrations:
            return "END Sorry, no tickets found for this phone number. Visit heelo.io to register."

        if len(registrations) == 1:
            reg = registrations[0]
            if reg.status == "checked_in":
                t = reg.checked_in_at.strftime("%I:%M %p") if reg.checked_in_at else "earlier"
                return f"END You are already checked in (at {t}).\nWelcome, {reg.attendee_name}!"
            return (
                f"CON Welcome, {reg.attendee_name}!\n"
                f"Ticket: {reg.ticket_type.name if reg.ticket_type else 'General'}\n"
                "1. Check in now\n"
                "2. Cancel"
            )

        # Multiple tickets — show a menu
        menu = "CON Your tickets:\n"
        for i, reg in enumerate(registrations[:4], 1):
            tt = reg.ticket_type.name if reg.ticket_type else "General"
            menu += f"{i}. {tt} — {reg.status}\n"
        return menu

    # ── Step 1: user made a selection ────────────────────────────────────────
    registrations = await ci_svc.find_by_phone(db, _all_events=True, phone_last10=phone_last10)

    if not registrations:
        return "END No tickets found. Visit heelo.io to register."

    if len(registrations) == 1:
        choice = parts[0].strip()
        reg = registrations[0]

        if choice == "1":
            try:
                reg = await ci_svc.check_in_by_id(db, reg.id)
                return (
                    f"END Checked in! Welcome, {reg.attendee_name}.\n"
                    f"Ticket: {reg.ticket_type.name if reg.ticket_type else 'General'}\n"
                    f"Enjoy the event!"
                )
            except ci_svc.AlreadyCheckedInError as e:
                t = e.reg.checked_in_at.strftime("%I:%M %p") if e.reg.checked_in_at else "earlier"
                return f"END Already checked in at {t}. Enjoy the event, {e.reg.attendee_name}!"
            except Exception:
                return "END Check-in failed. Please scan your QR code or ask event staff for help."
        else:
            return "END Check-in cancelled. See you at the event!"

    # Multiple registrations — resolve choice to an index
    if step >= 1:
        try:
            idx = int(parts[0].strip()) - 1
            if idx < 0 or idx >= len(registrations):
                return "END Invalid selection. Please try again."
        except ValueError:
            return "END Invalid input. Please try again."

        reg = registrations[idx]
        if step == 1:
            if reg.status == "checked_in":
                t = reg.checked_in_at.strftime("%I:%M %p") if reg.checked_in_at else "earlier"
                return f"END Already checked in at {t}. Enjoy the event!"
            tt = reg.ticket_type.name if reg.ticket_type else "General"
            return (
                f"CON {reg.attendee_name} — {tt}\n"
                "1. Check in now\n"
                "2. Cancel"
            )

        if step >= 2:
            action = parts[1].strip()
            if action == "1":
                try:
                    reg = await ci_svc.check_in_by_id(db, reg.id)
                    return (
                        f"END Checked in! Welcome, {reg.attendee_name}.\n"
                        f"Ticket: {reg.ticket_type.name if reg.ticket_type else 'General'}\n"
                        "Enjoy the event!"
                    )
                except ci_svc.AlreadyCheckedInError as e:
                    t = e.reg.checked_in_at.strftime("%I:%M %p") if e.reg.checked_in_at else "earlier"
                    return f"END Already checked in at {t}. Enjoy the event!"
                except Exception:
                    return "END Check-in failed. Please scan your QR code or ask event staff."
            else:
                return "END Check-in cancelled. See you at the event!"

    return "END Something went wrong. Please try again or visit heelo.io."
