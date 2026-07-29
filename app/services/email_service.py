"""
Email sending service — uses Resend REST API via httpx.

send_sync()  — synchronous, for Celery tasks
send_async() — async, for direct use in FastAPI request handlers

Template rendering uses a dedicated Jinja2 Environment
pointing at app/templates/emails/.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

import httpx
from jinja2 import Environment, FileSystemLoader

from app.config import settings

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "emails"
_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)


# ── Rendering ─────────────────────────────────────────────────────────────────

def render(template_name: str, **ctx) -> str:
    ctx.setdefault("frontend_url", settings.FRONTEND_URL)
    return _env.get_template(template_name).render(**ctx)


def gcal_url(event) -> str:
    """Build a Google Calendar add-event URL from an Event model instance."""
    fmt = "%Y%m%dT%H%M%SZ"
    start = event.start_datetime.strftime(fmt) if event.start_datetime else ""
    end = event.end_datetime.strftime(fmt) if event.end_datetime else ""
    dates = f"{start}/{end}" if start and end else start
    params = {
        "action": "TEMPLATE",
        "text": event.title,
        "dates": dates,
        "location": getattr(event, "location", "") or "",
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(params)


# ── Sending ───────────────────────────────────────────────────────────────────

def _payload(to: str | list[str], subject: str, html: str) -> dict:
    return {
        "from": f"{settings.RESEND_FROM_NAME} <{settings.RESEND_FROM_EMAIL}>",
        "to": [to] if isinstance(to, str) else to,
        "subject": subject,
        "html": html,
    }


def send_sync(to: str | list[str], subject: str, html: str) -> None:
    """Blocking send via httpx — for use inside Celery tasks."""
    if not settings.RESEND_API_KEY:
        return  # no-op in dev when key not configured
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            "https://api.resend.com/emails",
            json=_payload(to, subject, html),
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
        )
        resp.raise_for_status()


async def send_async(to: str | list[str], subject: str, html: str) -> None:
    """Non-blocking send — for use inside async FastAPI handlers."""
    if not settings.RESEND_API_KEY:
        return
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            json=_payload(to, subject, html),
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
        )
        resp.raise_for_status()
