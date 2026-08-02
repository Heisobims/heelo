"""
WhatsApp-native attendee flow: location/date formatting (regression test for the
event.location AttributeError bug), reminder interval config, structured keyword
Q&A bot, and consent persistence through registration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from httpx import AsyncClient

from app.services import whatsapp_service as wa
from app.tasks import whatsapp as wa_tasks


def _fake_event(**overrides) -> SimpleNamespace:
    defaults = {
        "title": "Afrobeats Night",
        "format": "in_person",
        "venue_name": "Eko Hotel",
        "venue_city": "Lagos",
        "virtual_url": None,
        "virtual_platform": None,
        "start_datetime": datetime(2027, 3, 15, 19, 0, tzinfo=UTC),
        "extras": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ── location_label / date_label — regression tests for the event.location bug ─


def test_location_label_in_person_uses_venue_fields():
    event = _fake_event()
    assert wa.location_label(event) == "Eko Hotel, Lagos"


def test_location_label_falls_back_to_city_only():
    event = _fake_event(venue_name=None)
    assert wa.location_label(event) == "Lagos"


def test_location_label_virtual_event():
    event = _fake_event(format="virtual", venue_name=None, venue_city=None, virtual_platform="Zoom")
    assert "Zoom" in wa.location_label(event)


def test_location_label_virtual_no_platform_defaults_to_online():
    event = _fake_event(format="virtual", venue_name=None, venue_city=None)
    assert wa.location_label(event) == "Online event — link shared closer to the date"


def test_location_label_no_venue_data_returns_tba():
    event = _fake_event(venue_name=None, venue_city=None)
    assert wa.location_label(event) == "TBA"


def test_date_label_formats_start_datetime():
    event = _fake_event()
    assert "Mar" in wa.date_label(event)


def test_date_label_empty_when_no_start_datetime():
    event = _fake_event(start_datetime=None)
    assert wa.date_label(event) == ""


# ── send_registration_confirmation_sync / send_event_reminder_sync no longer crash ─


def test_send_registration_confirmation_does_not_raise(monkeypatch):
    sent = {}
    monkeypatch.setattr(wa, "send_text_sync", lambda to, body: sent.update(text=body))
    monkeypatch.setattr(wa, "send_image_sync", lambda *a, **k: None)

    wa.send_registration_confirmation_sync(
        phone="+2348012345678",
        buyer_name="Jane",
        event=_fake_event(),
        registrations=[{"registration_id": "r1", "attendee_name": "Jane", "ticket_type": "GA"}],
    )
    assert "Eko Hotel, Lagos" in sent["text"]


def test_send_event_reminder_headline_varies_by_offset(monkeypatch):
    sent = {}
    monkeypatch.setattr(wa, "send_text_sync", lambda to, body: sent.update(text=body))
    monkeypatch.setattr(wa, "send_image_sync", lambda *a, **k: None)

    wa.send_event_reminder_sync(
        phone="+2348012345678",
        attendee_name="Jane",
        event=_fake_event(),
        registration_id="r1",
        hours_before=1,
    )
    assert "soon" in sent["text"]

    wa.send_event_reminder_sync(
        phone="+2348012345678",
        attendee_name="Jane",
        event=_fake_event(),
        registration_id="r1",
        hours_before=24,
    )
    assert "tomorrow" in sent["text"]


# ── send_event_reminder_sync — virtual join link delivery ──────────────────────


def test_send_event_reminder_includes_virtual_link(monkeypatch):
    sent = {}
    monkeypatch.setattr(wa, "send_text_sync", lambda to, body: sent.update(text=body))
    monkeypatch.setattr(wa, "send_image_sync", lambda *a, **k: None)

    event = _fake_event(
        format="virtual",
        venue_name=None,
        venue_city=None,
        virtual_platform="Zoom",
        virtual_url="https://zoom.us/j/123456789",
    )
    wa.send_event_reminder_sync(
        phone="+2348012345678", attendee_name="Jane", event=event, registration_id="r1"
    )
    # The message links to the join-redirect endpoint (which records attendance
    # before bouncing to the real meeting URL), not the raw virtual_url directly.
    assert "/api/v1/registrations/r1/join" in sent["text"]
    assert "link shared closer to the date" not in sent["text"]


def test_send_event_reminder_hybrid_includes_virtual_link(monkeypatch):
    sent = {}
    monkeypatch.setattr(wa, "send_text_sync", lambda to, body: sent.update(text=body))
    monkeypatch.setattr(wa, "send_image_sync", lambda *a, **k: None)

    event = _fake_event(
        format="hybrid", virtual_platform="Zoom", virtual_url="https://zoom.us/j/123456789"
    )
    wa.send_event_reminder_sync(
        phone="+2348012345678", attendee_name="Jane", event=event, registration_id="r1"
    )
    assert "/api/v1/registrations/r1/join" in sent["text"]


def test_send_event_reminder_in_person_omits_virtual_link(monkeypatch):
    sent = {}
    monkeypatch.setattr(wa, "send_text_sync", lambda to, body: sent.update(text=body))
    monkeypatch.setattr(wa, "send_image_sync", lambda *a, **k: None)

    wa.send_event_reminder_sync(
        phone="+2348012345678", attendee_name="Jane", event=_fake_event(), registration_id="r1"
    )
    assert "Join:" not in sent["text"]
    assert "Eko Hotel, Lagos" in sent["text"]


def test_send_event_reminder_virtual_without_url_omits_join_line(monkeypatch):
    sent = {}
    monkeypatch.setattr(wa, "send_text_sync", lambda to, body: sent.update(text=body))
    monkeypatch.setattr(wa, "send_image_sync", lambda *a, **k: None)

    event = _fake_event(format="virtual", venue_name=None, venue_city=None, virtual_url=None)
    wa.send_event_reminder_sync(
        phone="+2348012345678", attendee_name="Jane", event=event, registration_id="r1"
    )
    assert "Join:" not in sent["text"]
    assert "link shared closer to the date" in sent["text"]


# ── Reminder interval configuration (Event.extras) ─────────────────────────────


def test_reminder_hours_defaults_when_no_extras():
    assert wa_tasks._reminder_hours(_fake_event(extras=None)) == [24, 1]


def test_reminder_hours_reads_event_extras():
    event = _fake_event(extras={"whatsapp_reminder_hours": [48, 6, 1]})
    assert wa_tasks._reminder_hours(event) == [48, 6, 1]


def test_reminder_hours_ignores_invalid_values():
    event = _fake_event(extras={"whatsapp_reminder_hours": ["not-a-number", -5, 12]})
    assert wa_tasks._reminder_hours(event) == [12]


def test_reminder_hours_empty_list_falls_back_to_default():
    event = _fake_event(extras={"whatsapp_reminder_hours": []})
    assert wa_tasks._reminder_hours(event) == [24, 1]


# ── Structured keyword Q&A bot (no LLM) ─────────────────────────────────────────


def _mock_db_with(reg, event, ticket_type=None):
    """Fake a sync SQLAlchemy Session whose .query(...) chain returns fixed objects."""
    db = MagicMock()

    def query(model):
        q = MagicMock()
        model_name = getattr(model, "__name__", "")
        if model_name == "Registration":
            q.filter.return_value.order_by.return_value.first.return_value = reg
        elif model_name in ("Event", "EventModel"):
            q.filter.return_value.first.return_value = event
        elif model_name == "TicketType":
            q.filter.return_value.first.return_value = ticket_type
        return q

    db.query.side_effect = query
    return db


def test_structured_reply_location_keyword():
    event = _fake_event()
    reg = SimpleNamespace(ticket_type_id="tt1", event_id="ev1", created_at=datetime.now(UTC))
    db = _mock_db_with(reg, event)

    reply = wa_tasks._structured_reply(db, "+2348012345678", "Where is it?")
    assert "Eko Hotel, Lagos" in reply


def test_structured_reply_time_keyword():
    event = _fake_event()
    reg = SimpleNamespace(ticket_type_id="tt1", event_id="ev1", created_at=datetime.now(UTC))
    db = _mock_db_with(reg, event)

    reply = wa_tasks._structured_reply(db, "+2348012345678", "what time does it start")
    assert "starts" in reply.lower()


def test_structured_reply_guest_keyword_group_tickets_allowed():
    event = _fake_event()
    reg = SimpleNamespace(ticket_type_id="tt1", event_id="ev1", created_at=datetime.now(UTC))
    tt = SimpleNamespace(max_per_order=5)
    db = _mock_db_with(reg, event, ticket_type=tt)

    reply = wa_tasks._structured_reply(db, "+2348012345678", "can I bring a guest?")
    assert "Group tickets" in reply


def test_structured_reply_guest_keyword_single_ticket_only():
    event = _fake_event()
    reg = SimpleNamespace(ticket_type_id="tt1", event_id="ev1", created_at=datetime.now(UTC))
    tt = SimpleNamespace(max_per_order=1)
    db = _mock_db_with(reg, event, ticket_type=tt)

    reply = wa_tasks._structured_reply(db, "+2348012345678", "can I bring a friend?")
    assert "own ticket" in reply.lower()


def test_structured_reply_unmatched_text_falls_back_to_help():
    event = _fake_event()
    reg = SimpleNamespace(ticket_type_id="tt1", event_id="ev1", created_at=datetime.now(UTC))
    db = _mock_db_with(reg, event)

    reply = wa_tasks._structured_reply(db, "+2348012345678", "thanks so much!")
    assert reply == wa.HELP_TEXT


def test_structured_reply_no_registration_found_falls_back_to_help():
    db = _mock_db_with(None, None)
    reply = wa_tasks._structured_reply(db, "+2348012345678", "where is it")
    assert reply == wa.HELP_TEXT


# ── Consent persists through the registration API ───────────────────────────────


async def test_register_persists_whatsapp_consent_true(
    client: AsyncClient, db, published_event, ticket_type
):
    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/register",
        json={
            "buyer_name": "Ada Lovelace",
            "buyer_email": "ada@example.com",
            "buyer_phone": "+2348012345678",
            "whatsapp_consent": True,
            "items": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
        },
    )
    assert resp.status_code == 200

    from sqlalchemy import select

    from app.models.ticketing import Order, Registration

    order = await db.scalar(select(Order).where(Order.buyer_email == "ada@example.com"))
    assert order.whatsapp_consent is True

    reg = await db.scalar(select(Registration).where(Registration.order_id == order.id))
    assert reg.whatsapp_consent is True


async def test_register_defaults_whatsapp_consent_false(
    client: AsyncClient, db, published_event, ticket_type
):
    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/register",
        json={
            "buyer_name": "Grace Hopper",
            "buyer_email": "grace@example.com",
            "buyer_phone": "+2348012345678",
            "items": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
        },
    )
    assert resp.status_code == 200

    from sqlalchemy import select

    from app.models.ticketing import Order

    order = await db.scalar(select(Order).where(Order.buyer_email == "grace@example.com"))
    assert order.whatsapp_consent is False
