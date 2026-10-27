"""
Meta WhatsApp Business Cloud API client.

Platform-level: one WhatsApp Business number (configured in settings)
sends on behalf of all Tixdoo organizers.

send_*_sync()  - blocking httpx, for Celery tasks
send_*_async() - async httpx, for FastAPI handlers
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any

import httpx

from app.config import settings

_BASE_URL = "https://graph.facebook.com/v18.0"


# ── Webhook signature verification ────────────────────────────────────────────


def verify_whatsapp_signature(body: bytes, signature: str) -> bool:
    """
    Verify Meta's `X-Hub-Signature-256: sha256=<hex>` header over the raw
    request body, same fail-closed convention as verify_flutterwave_signature
    - an unconfigured secret must reject, not silently accept everything.
    """
    if not settings.WHATSAPP_APP_SECRET:
        return False
    prefix = "sha256="
    if not signature.startswith(prefix):
        return False
    expected = hmac.new(
        settings.WHATSAPP_APP_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature[len(prefix) :])


# ── Phone number normalization ────────────────────────────────────────────────


def format_phone(phone: str | None) -> str | None:
    """
    Return E.164 digits without '+' suitable for WhatsApp API.
    Returns None if the number cannot be parsed.

    Examples:
      '+2348012345678' → '2348012345678'
      '08012345678'   → '2348012345678'  (Nigerian local format)
      '2348012345678' → '2348012345678'
    """
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 10:
        return None
    # Nigerian local format: 0XXX (11 digits) → 234XXX
    if len(digits) == 11 and digits.startswith("0"):
        digits = "234" + digits[1:]
    return digits


# ── Low-level send helpers ────────────────────────────────────────────────────


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }


def _url() -> str:
    return f"{_BASE_URL}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"


def _text_payload(to: str, body: str) -> dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }


def _image_payload(to: str, image_url: str, caption: str = "") -> dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "image",
        "image": {"link": image_url, "caption": caption},
    }


def _template_payload(
    to: str,
    template_name: str,
    language_code: str,
    components: list[dict],
) -> dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": components,
        },
    }


def _guard() -> bool:
    """Return True when WhatsApp is configured; skip silently otherwise."""
    return bool(settings.WHATSAPP_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID)


def send_text_sync(to: str, body: str) -> None:
    if not _guard():
        return
    with httpx.Client(timeout=15.0) as client:
        client.post(_url(), json=_text_payload(to, body), headers=_headers())


async def send_text_async(to: str, body: str) -> None:
    if not _guard():
        return
    async with httpx.AsyncClient(timeout=15.0) as client:
        await client.post(_url(), json=_text_payload(to, body), headers=_headers())


def send_image_sync(to: str, image_url: str, caption: str = "") -> None:
    if not _guard():
        return
    with httpx.Client(timeout=15.0) as client:
        client.post(_url(), json=_image_payload(to, image_url, caption), headers=_headers())


async def send_image_async(to: str, image_url: str, caption: str = "") -> None:
    if not _guard():
        return
    async with httpx.AsyncClient(timeout=15.0) as client:
        await client.post(_url(), json=_image_payload(to, image_url, caption), headers=_headers())


# ── High-level notification helpers ──────────────────────────────────────────


def date_label(event) -> str:
    if not event.start_datetime:
        return ""
    return event.start_datetime.strftime("%a, %b %-d at %-I:%M %p")


def date_only_label(event) -> str:
    if not event.start_datetime:
        return "TBD"
    return event.start_datetime.strftime("%a, %b %-d, %Y")


def time_only_label(event) -> str:
    if not event.start_datetime:
        return "TBD"
    return event.start_datetime.strftime("%-I:%M %p")


def location_label(event) -> str:
    """
    Plain-text location line for WhatsApp messages.
    Event has no single `location` field - this composes it from the venue
    (in-person/hybrid) or virtual platform fields, matching the display
    logic already used in app/templates/events/public.html.
    """
    if event.format == "virtual":
        platform = event.virtual_platform.title() if event.virtual_platform else "Online"
        return f"{platform} event - link shared closer to the date"
    parts = [p for p in (event.venue_name, event.venue_city) if p]
    return ", ".join(parts) if parts else "TBA"


def send_registration_cancellation_sync(
    phone: str,
    attendee_name: str,
    event,
    ticket_type_name: str,
    refunded: bool,
) -> None:
    wa_phone = format_phone(phone)
    if not wa_phone:
        return

    lines = [
        f"Hi {attendee_name},",
        "",
        f"Your ticket ({ticket_type_name}) for *{event.title}* has been cancelled.",
    ]
    if refunded:
        lines += ["", "Your payment has been refunded - it may take a few days to reflect."]
    send_text_sync(wa_phone, "\n".join(lines))


def send_registration_confirmation_sync(
    phone: str,
    buyer_name: str,
    event,
    registrations: list[dict],
    attendee_name: str | None = None,
) -> None:
    """
    Send registration confirmation + QR codes via WhatsApp.

    `registrations` is a list of dicts:
        {"registration_id": str, "attendee_name": str, "ticket_type": str}
    """
    wa_phone = format_phone(phone)
    if not wa_phone:
        return

    if not attendee_name:
        if registrations and registrations[0].get("attendee_name"):
            attendee_name = registrations[0]["attendee_name"]
        else:
            attendee_name = buyer_name

    greeting = f"Hi {attendee_name}," if attendee_name else "Hi,"

    lines = [
        greeting,
        "",
        f"You're confirmed for *{event.title}*",
        "",
        f"Date: {date_only_label(event)}",
        f"Venue: {location_label(event)}",
        f"Time: {time_only_label(event)}",
        "",
        (
            "Your QR code is below - show it at the entrance."
            if len(registrations) <= 1
            else "Your QR codes are below - one per ticket. Show them at the entrance."
        ),
        "",
        "Reply *TICKET* any time to see your tickets.",
    ]

    send_text_sync(wa_phone, "\n".join(lines))

    # Send one QR image per registration
    for reg in registrations:
        qr_url = f"{settings.FRONTEND_URL}/api/v1/registrations/{reg['registration_id']}/qr.png"
        caption = f"{reg['attendee_name']} · {reg['ticket_type']} - {event.title}"
        send_image_sync(wa_phone, qr_url, caption)


def _reminder_headline(hours_before: float) -> str:
    if hours_before >= 12:
        return "is tomorrow!"
    if hours_before >= 2:
        return f"starts in about {round(hours_before)} hours!"
    return "starts soon!"


def send_event_reminder_sync(
    phone: str,
    attendee_name: str,
    event,
    registration_id: str,
    hours_before: float = 24,
) -> None:
    from urllib.parse import quote_plus

    wa_phone = format_phone(phone)
    if not wa_phone:
        return

    headline = _reminder_headline(hours_before)
    lines = [
        f"Hi {attendee_name},",
        "",
        f"*{event.title}* {headline}",
    ]
    if event.start_datetime:
        lines.append(f"Date: {date_label(event)}")
        time_str = event.start_datetime.strftime("%I:%M %p")
        if getattr(event, "timezone", None):
            time_str += f" ({event.timezone})"
        lines.append(f"Time: {time_str}")

    if event.format in ("virtual", "hybrid") and event.virtual_url:
        platform = event.virtual_platform.title() if event.virtual_platform else "Online"
        join_url = f"{settings.FRONTEND_URL}/api/v1/registrations/{registration_id}/join"
        lines.append(f"Venue: {platform} Event")
        lines.append(f"Join Link: {join_url}")
    else:
        venue_str = location_label(event)
        lines.append(f"Venue: {venue_str}")
        venue_parts = [
            getattr(event, "venue_name", None),
            getattr(event, "venue_address", None),
            getattr(event, "venue_city", None),
        ]
        venue_query = " ".join([p for p in venue_parts if p])
        if venue_query:
            maps_url = f"https://www.google.com/maps/search/?api=1&query={quote_plus(venue_query)}"
            lines.append(f"Venue Directions: {maps_url}")

    ticket_pdf_url = f"{settings.FRONTEND_URL}/api/v1/registrations/{registration_id}/ticket.pdf"
    lines += [
        f"Ticket Link: {ticket_pdf_url}",
        "",
        "Here is your QR code for quick check-in:",
    ]
    send_text_sync(wa_phone, "\n".join(lines))

    qr_url = f"{settings.FRONTEND_URL}/api/v1/registrations/{registration_id}/qr.png"
    send_image_sync(wa_phone, qr_url, f"QR code for {event.title}")


def send_event_cancellation_sync(
    phone: str,
    attendee_name: str,
    event,
    cancellation_note: str = "",
) -> None:
    wa_phone = format_phone(phone)
    if not wa_phone:
        return

    lines = [
        f"Hi {attendee_name},",
        "",
        f"*{event.title}* has been cancelled.",
    ]
    if cancellation_note:
        lines += ["", cancellation_note]
    lines += [
        "",
        "If you paid for a ticket, reach out to the organizer about a refund.",
    ]
    send_text_sync(wa_phone, "\n".join(lines))


def send_event_update_sync(
    phone: str,
    attendee_name: str,
    event,
    changes: list[dict],
) -> None:
    wa_phone = format_phone(phone)
    if not wa_phone:
        return

    lines = [
        f"Hi {attendee_name},",
        "",
        f"*{event.title}* has updated details:",
        "",
    ]
    for c in changes:
        lines.append(f"*{c['field']}*: {c['old']} -> {c['new']}")
    lines += [
        "",
        f"Date: {date_label(event)}",
        f"Venue: {location_label(event)}",
    ]
    send_text_sync(wa_phone, "\n".join(lines))


def send_waitlist_notification_sync(
    phone: str,
    name: str,
    event,
    ticket_type_name: str,
    register_url: str,
) -> None:
    wa_phone = format_phone(phone)
    if not wa_phone:
        return

    lines = [
        f"Good news, {name}!",
        "",
        f"A *{ticket_type_name}* spot just opened up for *{event.title if event else 'the event'}*.",
        "",
        f"Claim it now before it's gone: {register_url}",
    ]
    send_text_sync(wa_phone, "\n".join(lines))


# ── Bot reply builder ─────────────────────────────────────────────────────────


def build_ticket_status_reply(registrations: list) -> str:
    """Build a WhatsApp text reply listing the caller's current tickets."""
    if not registrations:
        return (
            "No active tickets found for this number.\n"
            "Visit tixdoo.com to register for an event.\n\n"
            "Reply *HELP* for commands."
        )

    lines = ["Here are your tickets:\n"]
    for reg in registrations:
        tt = reg.ticket_type.name if reg.ticket_type else "General"

        status_label = (
            "[Confirmed]" if reg.status == "confirmed" else "[Checked In]" if reg.status == "checked_in" else "[Pending]"
        )
        event_title = getattr(reg, "_event_title", "Event")
        lines.append(f"  {status_label} {event_title}\n     Ticket: {tt} - {reg.status.title()}")

    lines.append("\nReply *HELP* for commands.")
    return "\n".join(lines)


HELP_TEXT = (
    "*Tixdoo WhatsApp Bot*\n\n"
    "Commands:\n"
    "  *TICKET* - see your registered tickets\n"
    "  *HELP*   - show this message\n\n"
    'You can also just ask things like "where is it", "what time", '
    'or "can I bring a guest" about your most recent event.\n\n'
    "For support, visit tixdoo.com or contact the event organizer."
)
