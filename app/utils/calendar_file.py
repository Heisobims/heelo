from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import quote

from app.models.event import Event


def _fold(line: str) -> str:
    """RFC 5545 line folding - lines over 75 octets get continued with a leading space."""
    if len(line) <= 75:
        return line
    parts = [line[:75]]
    rest = line[75:]
    while rest:
        parts.append(" " + rest[:74])
        rest = rest[74:]
    return "\r\n".join(parts)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _location(event: Event) -> str:
    if event.format == "virtual":
        return event.virtual_url or "Online"
    parts = [p for p in (event.venue_name, event.venue_address, event.venue_city) if p]
    return ", ".join(parts) or "TBA"


def build_ics(event: Event, *, uid: uuid.UUID) -> bytes:
    """Build a minimal RFC 5545 .ics file for a single event, for an attendee's calendar."""
    fmt = "%Y%m%dT%H%M%SZ"
    now = datetime.now(UTC).strftime(fmt)
    dtstart = event.start_datetime.astimezone(UTC).strftime(fmt)
    dtend = event.end_datetime.astimezone(UTC).strftime(fmt)

    description = (event.description or "").strip()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Heelo//Event Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}@heelo.io",
        f"DTSTAMP:{now}",
        f"DTSTART:{dtstart}",
        f"DTEND:{dtend}",
        f"SUMMARY:{_escape(event.title)}",
        f"LOCATION:{_escape(_location(event))}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")

    folded = "\r\n".join(_fold(line) for line in lines)
    return (folded + "\r\n").encode("utf-8")


def google_calendar_url(event: Event) -> str:
    """Build a 'https://calendar.google.com/...' add-event link - no file download needed."""
    fmt = "%Y%m%dT%H%M%SZ"
    start = event.start_datetime.astimezone(UTC).strftime(fmt)
    end = event.end_datetime.astimezone(UTC).strftime(fmt)
    dates = f"{start}/{end}"
    params = {
        "action": "TEMPLATE",
        "text": event.title,
        "dates": dates,
        "details": (event.description or "").strip(),
        "location": _location(event),
    }
    query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    return f"https://calendar.google.com/calendar/render?{query}"
