"""
Tests for the public Heelo AI Support Chatbot.

Verifies:
1. Public chat endpoint (/api/v1/support/chat) responses for platform questions.
2. Pricing, fees, event creation, vendor marketplace, and digital passes knowledge.
3. Live database grounding for published upcoming events.
4. Conversation history handling and input validation.
5. HTML widget injection into base template pages.
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event


async def test_support_chat_event_creation(client: AsyncClient):
    """Verify chatbot answers questions about creating an event."""
    resp = await client.post(
        "/api/v1/support/chat",
        json={"message": "How do I create and publish an event on Heelo?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    reply = data["data"]["reply"]
    assert "Create Event" in reply or "how to create" in reply.lower()
    assert len(data["data"]["suggestions"]) > 0


async def test_support_chat_pricing_and_fees(client: AsyncClient):
    """Verify chatbot explains free tier, 3.5% fee pass-through, and plans."""
    resp = await client.post(
        "/api/v1/support/chat",
        json={"message": "What are your fees and pricing plans?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    reply = data["data"]["reply"]
    assert "3.5%" in reply
    assert "Free" in reply
    assert "Growth" in reply or "Pro" in reply


async def test_support_chat_payouts_and_gateways(client: AsyncClient):
    """Verify chatbot explains Paystack, Flutterwave, Stripe and automated bank payouts."""
    resp = await client.post(
        "/api/v1/support/chat",
        json={"message": "How do payouts work and what payment gateways are supported?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    reply = data["data"]["reply"]
    assert "Paystack" in reply or "Flutterwave" in reply or "Stripe" in reply
    assert "payout" in reply.lower()


async def test_support_chat_vendor_marketplace(client: AsyncClient):
    """Verify chatbot explains the vendor marketplace, escrow protection, and categories."""
    resp = await client.post(
        "/api/v1/support/chat",
        json={"message": "Can I hire photographers or caterers for my event?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    reply = data["data"]["reply"]
    assert "Vendor" in reply or "vendors" in reply
    assert "/vendors" in reply or "escrow" in reply.lower()


async def test_support_chat_apple_wallet_and_checkin(client: AsyncClient):
    """Verify chatbot explains Box Office check-in and Apple Wallet passes."""
    resp = await client.post(
        "/api/v1/support/chat",
        json={"message": "How do attendees check in and do you support Apple Wallet?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    reply = data["data"]["reply"]
    assert "check-in" in reply.lower() or "box office" in reply.lower()
    assert "wallet" in reply.lower() or "qr" in reply.lower()


async def test_support_chat_live_database_grounding(
    client: AsyncClient, db: AsyncSession, published_event: Event
):
    """Verify chatbot fetches and recommends live upcoming events from the database."""
    published_event.title = "AfroTech Summit Lagos 2026"
    published_event.slug = "afrotech-summit-lagos-2026"
    published_event.start_datetime = datetime.now(UTC) + timedelta(days=14)
    published_event.venue_city = "Lagos"
    await db.flush()

    resp = await client.post(
        "/api/v1/support/chat",
        json={"message": "What upcoming events are happening?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    reply = data["data"]["reply"]
    assert "AfroTech Summit Lagos 2026" in reply
    assert "/e/afrotech-summit-lagos-2026" in reply


async def test_support_chat_conversation_history(client: AsyncClient):
    """Verify chat endpoint accepts multi-turn conversation history."""
    resp = await client.post(
        "/api/v1/support/chat",
        json={
            "message": "Can I also track Facebook and TikTok ad conversions?",
            "history": [
                {"role": "user", "content": "How do I create an event?"},
                {"role": "assistant", "content": "You can create an event in your dashboard."},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    reply = data["data"]["reply"]
    assert "pixel" in reply.lower() or "meta" in reply.lower() or "tiktok" in reply.lower()


async def test_support_chat_validation_error(client: AsyncClient):
    """Verify overly long message returns 422 validation error."""
    resp = await client.post(
        "/api/v1/support/chat",
        json={"message": "x" * 1500},
    )
    assert resp.status_code == 422


async def test_ai_chat_widget_rendered_in_templates(client: AsyncClient):
    """Verify AI chatbot widget is embedded in pages extending base.html."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "heelo-ai-widget-root" in resp.text
    assert "heeloAiChat()" in resp.text
    assert "Heelo AI Assistant" in resp.text

    resp_pricing = await client.get("/pricing")
    assert resp_pricing.status_code == 200
    assert "heelo-ai-widget-root" in resp_pricing.text


async def test_support_chat_events_this_weekend_with_location_context(
    client: AsyncClient, db: AsyncSession, published_event: Event, ticket_type
):
    """Verify chatbot answers 'is there any event this weekend' grounded in the DB by location."""
    from zoneinfo import ZoneInfo
    from app.services.chatbot_service import parse_temporal_intent

    bounds = parse_temporal_intent("this weekend", "Africa/Lagos")
    assert bounds is not None
    start_bound, end_bound, _ = bounds

    published_event.title = "Lagos Creator Weekend Fest"
    published_event.slug = "lagos-creator-weekend-fest"
    published_event.venue_city = "Lagos"
    published_event.venue_name = "Landmark Centre"
    published_event.start_datetime = start_bound + timedelta(hours=14)
    published_event.end_datetime = start_bound + timedelta(hours=20)
    await db.flush()

    resp = await client.post(
        "/api/v1/support/chat",
        json={
            "message": "is there any event this weekend",
            "client_context": {"timezone": "Africa/Lagos"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    reply = data["data"]["reply"]
    assert "Lagos Creator Weekend Fest" in reply
    assert "/e/lagos-creator-weekend-fest" in reply
    assert "weekend" in reply.lower()
    assert "Lagos" in reply
    assert "\u2014" not in reply


async def test_support_chat_events_location_filter_mismatch(
    client: AsyncClient, db: AsyncSession, published_event: Event
):
    """Verify chatbot handles query for location with no events for that timeframe gracefully."""
    from app.services.chatbot_service import parse_temporal_intent

    bounds = parse_temporal_intent("this weekend", "UTC")
    assert bounds is not None
    start_bound, end_bound, _ = bounds

    published_event.title = "Lagos Tech Gathering"
    published_event.slug = "lagos-tech-gathering"
    published_event.venue_city = "Lagos"
    published_event.start_datetime = start_bound + timedelta(hours=12)
    published_event.end_datetime = start_bound + timedelta(hours=16)
    await db.flush()

    resp = await client.post(
        "/api/v1/support/chat",
        json={"message": "are there any events in London this weekend?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    reply = data["data"]["reply"]
    assert "London" in reply
    assert "\u2014" not in reply


async def test_support_chat_no_emojis_and_no_em_dashes(client: AsyncClient):
    """Verify chatbot responses never contain emojis or em dashes."""
    test_queries = [
        "is there any event this weekend",
        "What are your fees?",
        "How do payouts work?",
        "Can I hire vendors?",
        "How do I check in attendees?",
    ]
    for q in test_queries:
        resp = await client.post("/api/v1/support/chat", json={"message": q})
        assert resp.status_code == 200
        reply = resp.json()["data"]["reply"]
        assert "\u2014" not in reply, f"Em dash found in reply for '{q}'"
        for ch in reply:
            if ord(ch) > 127 and ch not in "₦£€":
                assert ord(ch) < 0x1F000, f"Emoji character {ch} found in reply for '{q}'"


