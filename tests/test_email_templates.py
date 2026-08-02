"""Tests for Jinja email template rendering behavior that isn't covered by hitting a
live route — specifically, that the event reminder email actually reveals the virtual
join link (previously it only ever showed the platform name, never the real URL).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services import email_service as em
from app.utils.color import contrasting_text_color


def _fake_event(**overrides) -> SimpleNamespace:
    defaults = {
        "title": "Afrobeats Night",
        "format": "in_person",
        "venue_name": "Eko Hotel",
        "venue_city": "Lagos",
        "virtual_url": None,
        "virtual_platform": None,
        "start_datetime": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _render_reminder(event) -> str:
    return em.render(
        "event_reminder.html",
        event=event,
        org_name="Heelo",
        attendee_name="Jane",
        reminder_headline="is tomorrow!",
        registration_id="reg-1",
        frontend_url="http://localhost:8000",
        gcal_url="http://example.com/gcal",
    )


def test_reminder_shows_virtual_link_for_virtual_event():
    event = _fake_event(
        format="virtual",
        venue_name=None,
        venue_city=None,
        virtual_platform="zoom",
        virtual_url="https://zoom.us/j/123456789",
    )
    html = _render_reminder(event)
    # The real URL is still shown as visible link text (so attendees can see
    # where they're going), but the href routes through the join-redirect
    # endpoint first, which records attendance before bouncing them onward.
    assert "https://zoom.us/j/123456789" in html
    assert 'href="http://localhost:8000/api/v1/registrations/reg-1/join"' in html


def test_reminder_shows_both_venue_and_virtual_link_for_hybrid_event():
    event = _fake_event(
        format="hybrid", virtual_platform="zoom", virtual_url="https://zoom.us/j/123456789"
    )
    html = _render_reminder(event)
    assert "https://zoom.us/j/123456789" in html
    assert 'href="http://localhost:8000/api/v1/registrations/reg-1/join"' in html
    assert "Eko Hotel" in html


def test_reminder_omits_virtual_line_for_in_person_event():
    html = _render_reminder(_fake_event())
    assert "zoom.us" not in html
    assert "Eko Hotel" in html


def test_reminder_virtual_event_without_url_shows_platform_only():
    event = _fake_event(format="virtual", venue_name=None, venue_city=None, virtual_platform="zoom")
    html = _render_reminder(event)
    assert "Zoom event" in html
    assert 'href="https://' not in html


# ── Org branding ──────────────────────────────────────────────────────────────


def test_contrasting_text_color_picks_black_for_light_background():
    assert contrasting_text_color("#FFFFFF") == "#000000"


def test_contrasting_text_color_picks_white_for_dark_background():
    assert contrasting_text_color("#000000") == "#ffffff"


def test_contrasting_text_color_falls_back_to_default_when_missing():
    assert contrasting_text_color(None, default="#123456") == "#123456"
    assert contrasting_text_color("not-a-color", default="#123456") == "#123456"


def test_reminder_uses_org_brand_color_when_set():
    html = _render_reminder(_fake_event())
    branded = em.render(
        "event_reminder.html",
        event=_fake_event(),
        attendee_name="Jane",
        reminder_headline="is tomorrow!",
        registration_id="reg-1",
        frontend_url="http://localhost:8000",
        gcal_url="http://example.com/gcal",
        org_name="Afrobeats Ltd",
        brand_color="#FF5500",
    )
    assert "#FF5500" in branded
    # Unbranded rendering falls back to Heelo's own black/cyan.
    assert "#FF5500" not in html


def test_reminder_falls_back_to_heelo_colors_when_org_has_no_brand_color():
    html = _render_reminder(_fake_event())
    assert "#000000" in html


def test_base_header_shows_org_logo_when_set():
    html = em.render(
        "event_reminder.html",
        event=_fake_event(),
        attendee_name="Jane",
        reminder_headline="is tomorrow!",
        registration_id="reg-1",
        frontend_url="http://localhost:8000",
        gcal_url="http://example.com/gcal",
        org_name="Afrobeats Ltd",
        org_logo_url="https://example.com/logo.png",
        brand_color="#FF5500",
    )
    assert 'src="https://example.com/logo.png"' in html


def test_platform_wide_cta_stays_unbranded_regardless_of_org_color():
    html = em.render(
        "event_cancelled.html",
        event=_fake_event(),
        attendee_name="Jane",
        cancellation_note="",
        org_name="Afrobeats Ltd",
        brand_color="#FF5500",
    )
    # The org's card header picks up the brand color...
    assert "#FF5500" in html
    # ...but the platform-wide "Discover Other Events" CTA intentionally stays
    # Heelo cyan, since it links off to the whole platform, not this org.
    assert "#00FFF3" in html
