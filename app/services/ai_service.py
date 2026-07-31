"""
Anthropic AI helpers used by the AI router (async, FastAPI)
and the ai_tasks Celery task (sync).

All functions degrade gracefully when ANTHROPIC_API_KEY is not set —
they return empty strings / empty generators so the rest of the app keeps working.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.config import settings

_MODEL_FAST = "claude-haiku-4-5-20251001"
_MODEL_SMART = "claude-sonnet-4-6"


# ── Lazy client factories ─────────────────────────────────────────────────────


def _async_client():
    from anthropic import AsyncAnthropic

    return AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)


def _sync_client():
    from anthropic import Anthropic

    return Anthropic(api_key=settings.ANTHROPIC_API_KEY)


# ── Event description generator (streaming) ───────────────────────────────────


async def stream_event_description(
    *,
    title: str,
    format: str = "in_person",
    location: str = "",
    tags: list[str] | None = None,
    existing: str = "",
) -> AsyncIterator[str]:
    if not settings.ANTHROPIC_API_KEY:
        return

    format_label = {"in_person": "in-person", "virtual": "virtual", "hybrid": "hybrid"}.get(
        format, "in-person"
    )
    tag_line = f"Topics/tags: {', '.join(tags)}" if tags else ""
    loc_line = f"Location: {location}" if location else ""
    refine_line = f"\n\nExisting draft (improve it):\n{existing}" if existing else ""

    prompt = f"""Write a compelling event description for the following event.

Event title: {title}
Format: {format_label}
{loc_line}
{tag_line}{refine_line}

Requirements:
- 2-4 short paragraphs, conversational and energetic
- Start with a hook that captures why this event matters
- Mention what attendees will learn, experience, or gain
- End with a clear call to action (register now, secure your spot, etc.)
- No markdown headers, no bullet lists — flowing prose only
- Suitable for an African audience but globally professional

Write the description now:"""

    async with _async_client().messages.stream(
        model=_MODEL_FAST,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        async for text in stream.text_stream:
            yield text


# ── Campaign copy generator (streaming) ──────────────────────────────────────


async def stream_campaign_copy(
    *,
    channel: str,
    event_title: str,
    event_date: str = "",
    event_description: str = "",
    goal: str = "reminder",
    org_name: str = "",
) -> AsyncIterator[str]:
    if not settings.ANTHROPIC_API_KEY:
        return

    goal_labels = {
        "reminder": "remind registered attendees about the upcoming event",
        "last_tickets": "create urgency — tickets are almost sold out",
        "thank_you": "thank attendees after the event and keep them engaged",
        "early_bird": "promote early-bird ticket pricing",
        "announcement": "announce the event and drive registrations",
    }
    goal_text = goal_labels.get(goal, goal)
    date_line = f"Event date: {event_date}" if event_date else ""
    desc_line = f"Event description: {event_description[:400]}" if event_description else ""
    org_line = f"Organizer: {org_name}" if org_name else ""

    if channel == "email":
        format_instruction = """Return in this exact format (no extra text):
SUBJECT: [one compelling subject line, max 60 chars]
BODY:
[email body, 3-4 short paragraphs, uses {{name}}, {{event_name}}, {{event_date}}, {{org_name}} as template variables where natural]"""
        max_tokens = 700
    else:
        format_instruction = """Return only the WhatsApp message (no label, no subject).
Max 800 characters. Uses {{name}} and {{event_name}} where natural. End with a clear call to action or link placeholder."""
        max_tokens = 350

    prompt = f"""Write a {channel} campaign message for the following event.

Goal: {goal_text}
Event: {event_title}
{date_line}
{desc_line}
{org_line}

{format_instruction}

Write it now:"""

    async with _async_client().messages.stream(
        model=_MODEL_FAST,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        async for text in stream.text_stream:
            yield text


# ── Analytics insights (non-streaming) ───────────────────────────────────────


async def generate_analytics_insights(
    summary: dict,
    ticket_breakdown: list[dict],
) -> str:
    if not settings.ANTHROPIC_API_KEY:
        return ""

    top_ticket = max(ticket_breakdown, key=lambda t: t.get("sold", 0)) if ticket_breakdown else {}

    prompt = f"""You are analyzing event performance data for an organizer on Heelo (Africa's event platform).

Stats:
- Total registrations: {summary.get('total_registrations', 0)}
- Confirmed: {summary.get('total_confirmed', 0)}
- Checked in: {summary.get('total_checked_in', 0)}
- Pending payment: {summary.get('pending_registrations', 0)}
- Net revenue: {summary.get('net_revenue', 0)} ({summary.get('currency', 'NGN')})
- Check-in rate: {summary.get('checkin_rate', 0)}%
- Avg order value: {summary.get('avg_order_value', 0)}
{f"- Top ticket: {top_ticket.get('name')} — {top_ticket.get('sold', 0)} sold ({top_ticket.get('sold_pct', 0)}% of capacity)" if top_ticket else ""}

Give exactly 3 bullet points, each on its own line starting with "•":
• What's going well (be specific with numbers)
• What needs attention or is a concern
• One concrete actionable recommendation the organizer can do right now

Be direct, specific, and practical. No intro text, no headers — just the 3 bullets."""

    response = await _async_client().messages.create(
        model=_MODEL_SMART,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


# ── WhatsApp reply suggestion (sync, for Celery) ──────────────────────────────


def suggest_whatsapp_reply_sync(
    *,
    message_text: str,
    attendee_name: str = "",
    org_name: str = "",
    event_context: str = "",
) -> str:
    if not settings.ANTHROPIC_API_KEY:
        return ""

    name_line = f"Attendee name: {attendee_name}" if attendee_name else ""
    org_line = f"Organization: {org_name}" if org_name else "Organization: Heelo"
    ctx_line = f"Relevant event: {event_context}" if event_context else ""

    prompt = f"""You are a helpful WhatsApp assistant for an event organizer on Heelo.
{org_line}
{name_line}
{ctx_line}

An attendee sent this message:
"{message_text}"

Write a friendly, helpful WhatsApp reply (max 300 characters). Be warm, concise, and solve their problem or direct them to the right resource. Do not use markdown. Reply in plain text only."""

    response = _sync_client().messages.create(
        model=_MODEL_FAST,
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()
