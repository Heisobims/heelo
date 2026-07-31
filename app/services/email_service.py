"""
Email sending service — used by Celery tasks for registration confirmations,
reminders, and waitlist notices.

Sends over SMTP via app.utils.email.send_smtp (the same transport used for
OTP/password-reset/welcome/invite emails) rather than a separate provider —
one SMTP account configures every outbound email in the app.

send_sync()  — synchronous, for Celery tasks
send_async() — async, for direct use in FastAPI request handlers (runs the
               blocking smtplib call in a thread so it doesn't block the loop)

Template rendering uses a dedicated Jinja2 Environment
pointing at app/templates/emails/.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.config import settings
from app.utils.calendar_file import google_calendar_url
from app.utils.email import send_smtp

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "emails"
_env = Environment(loader=FileSystemLoader(str(_TEMPLATES_DIR)), autoescape=True)


# ── Rendering ─────────────────────────────────────────────────────────────────


def render(template_name: str, **ctx) -> str:
    ctx.setdefault("frontend_url", settings.FRONTEND_URL)
    return _env.get_template(template_name).render(**ctx)


def gcal_url(event) -> str:
    """Build a Google Calendar add-event URL from an Event model instance."""
    return google_calendar_url(event)


# ── Sending ───────────────────────────────────────────────────────────────────


def send_sync(to: str | list[str], subject: str, html: str) -> None:
    """Blocking send via smtplib — for use inside Celery tasks."""
    send_smtp(to, subject, html)


async def send_async(to: str | list[str], subject: str, html: str) -> None:
    """Non-blocking send — for use inside async FastAPI handlers."""
    await asyncio.to_thread(send_smtp, to, subject, html)
