"""Tests for Jinja email template rendering behavior that isn't covered by hitting a
live route - specifically, that the event reminder email actually reveals the virtual
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
    """Regression test: confirm fallback CTA button uses Heelo's terracotta brand color."""
    html = _render_reminder(_fake_event())
    assert "background-color:#E85938;color:#FFFFFF;" in html


def test_feedback_request_button_defaults_to_cyan_with_black_text():
    html = em.render(
        "feedback_request.html",
        event=_fake_event(),
        attendee_name="Jane",
        registration_id="reg-1",
        frontend_url="http://localhost:8000",
        org_name="Heelo",
    )
    assert "background-color:#E85938;color:#FFFFFF;" in html


def test_interest_nudge_button_defaults_to_cyan_with_black_text():
    html = em.render(
        "interest_nudge.html",
        event=_fake_event(),
        frontend_url="http://localhost:8000",
        org_name="Heelo",
    )
    assert "background-color:#E85938;color:#FFFFFF;" in html


def test_registration_confirmation_button_defaults_to_cyan_with_black_text():
    order = SimpleNamespace(id="order-1")
    registrations = [
        {"attendee_name": "Jane", "ticket_type": "GA", "registration_id": "r1", "qr_url": "x"}
    ]
    html = em.render(
        "registration_confirmation.html",
        event=_fake_event(),
        order=order,
        registrations=registrations,
        buyer_name="Jane",
        gcal_url="http://example.com/gcal",
        frontend_url="http://localhost:8000",
        org_name="Heelo",
    )
    assert "background-color:#E85938;color:#FFFFFF;" in html


def test_email_cta_buttons_use_branded_colors_when_org_has_one():
    """The four CTA-button templates all default to cyan/black - confirm
    they also correctly pick up a custom brand color when one is set,
    rather than the default just happening to always win."""
    order = SimpleNamespace(id="order-1")
    registrations = [
        {"attendee_name": "Jane", "ticket_type": "GA", "registration_id": "r1", "qr_url": "x"}
    ]
    common = {
        "frontend_url": "http://localhost:8000",
        "org_name": "Afrobeats Ltd",
        "brand_color": "#6C2BD9",
    }

    reminder = em.render(
        "event_reminder.html",
        event=_fake_event(),
        attendee_name="Jane",
        reminder_headline="is tomorrow!",
        registration_id="reg-1",
        gcal_url="http://example.com/gcal",
        **common,
    )
    feedback = em.render(
        "feedback_request.html",
        event=_fake_event(),
        attendee_name="Jane",
        registration_id="reg-1",
        **common,
    )
    nudge = em.render("interest_nudge.html", event=_fake_event(), **common)
    confirmation = em.render(
        "registration_confirmation.html",
        event=_fake_event(),
        order=order,
        registrations=registrations,
        buyer_name="Jane",
        gcal_url="http://example.com/gcal",
        **common,
    )

    for html in (reminder, feedback, nudge, confirmation):
        assert "background-color:#6C2BD9;" in html
        assert "#00FFF3" not in html  # brand color fully replaces the cyan default


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
    # Heelo terracotta, since it links off to the whole platform, not this org.
    assert "#E85938" in html


def test_vendor_marketplace_email_templates_render_successfully():
    """Verify that all vendor and organizer transactional email templates
    render with expected variables and without Jinja errors."""
    
    # 1. Vendor Quote Request
    html_rfq = em.render(
        "vendor_quote_request.html",
        business_name="Lagos Lens Co.",
        requester_name="Alex Morgan",
        event_name="Tech Leaders Gala 2026",
        event_date="November 20, 2026",
        event_location="Eko Hotel, Lagos",
        expected_attendance=300,
        budget_min=150000.0,
        budget_max=400000.0,
        currency="NGN",
        requirements="Need 2 photographers and full drone coverage.",
        frontend_url="https://heelo.io",
        dashboard_url="https://heelo.io/my-vendor-dashboard?tab=inquiries",
    )
    assert "Tech Leaders Gala 2026" in html_rfq
    assert "Lagos Lens Co." in html_rfq
    assert "Alex Morgan" in html_rfq
    assert "Review Inquiry" in html_rfq

    # 2. Organizer Quote Request Submitted
    html_org_rfq = em.render(
        "organizer_quote_request_submitted.html",
        requester_name="Alex Morgan",
        event_name="Tech Leaders Gala 2026",
        service_category="photography",
        event_date="November 20, 2026",
        vendor_count=2,
        vendors_list="Lagos Lens Co., Prime Media",
        frontend_url="https://heelo.io",
    )
    assert "Your Quote Request Has Been Dispatched!" in html_org_rfq
    assert "Lagos Lens Co., Prime Media" in html_org_rfq

    # 3. Vendor Quotation Submitted
    html_quote = em.render(
        "vendor_quotation_submitted.html",
        requester_name="Alex Morgan",
        vendor_name="Lagos Lens Co.",
        vendor_slug="lagos-lens",
        event_name="Tech Leaders Gala 2026",
        quotation_title="Executive Photography Package",
        total_amount=250000.0,
        currency="NGN",
        valid_until="November 10, 2026",
        scope_of_work="Includes 8 hours coverage, 2 shooters, and editing.",
        attachment_url="/static/uploads/vendors/quote_123.pdf",
        attachment_name="LagosLens_Proposal_v2.pdf",
        frontend_url="https://heelo.io",
        booking_url="https://heelo.io/vendors/lagos-lens",
    )
    assert "Quotation Received: Lagos Lens Co." in html_quote
    assert "250,000.00" in html_quote
    assert "Heelo Escrow Protection" in html_quote
    assert "LagosLens_Proposal_v2.pdf" in html_quote
    assert "/static/uploads/vendors/quote_123.pdf" in html_quote

    # 4. Vendor Booking Confirmed
    html_v_book = em.render(
        "vendor_booking_confirmed.html",
        business_name="Lagos Lens Co.",
        booking_reference="VB-12345",
        event_name="Tech Leaders Gala 2026",
        event_date="November 20, 2026",
        event_location="Eko Hotel, Lagos",
        client_name="Alex Morgan",
        client_email="alex@tech.org",
        client_phone="+2348012345678",
        total_amount=250000.0,
        commission_rate=10.0,
        commission_amount=25000.0,
        vendor_earnings=225000.0,
        currency="NGN",
        frontend_url="https://heelo.io",
    )
    assert "New Confirmed Booking!" in html_v_book
    assert "VB-12345" in html_v_book
    assert "225,000.00" in html_v_book

    # 5. Organizer Booking Confirmed
    html_org_book = em.render(
        "organizer_booking_confirmed.html",
        requester_name="Alex Morgan",
        vendor_name="Lagos Lens Co.",
        vendor_slug="lagos-lens",
        booking_reference="VB-12345",
        event_name="Tech Leaders Gala 2026",
        event_date="November 20, 2026",
        event_location="Eko Hotel, Lagos",
        total_amount=250000.0,
        currency="NGN",
        payment_reference="pay_ref_999",
        frontend_url="https://heelo.io",
    )
    assert "Your Vendor Booking is Confirmed!" in html_org_book
    assert "VB-12345" in html_org_book
    assert "Escrow Protection Guarantee" in html_org_book

    # 6. Vendor Booking Completed
    html_v_comp = em.render(
        "vendor_booking_completed.html",
        business_name="Lagos Lens Co.",
        booking_reference="VB-12345",
        event_name="Tech Leaders Gala 2026",
        vendor_earnings=225000.0,
        payable_balance=500000.0,
        currency="NGN",
        frontend_url="https://heelo.io",
    )
    assert "Job Completed &amp; Payout Credited!" in html_v_comp
    assert "225,000.00" in html_v_comp

    # 7. Organizer Booking Completed
    html_org_comp = em.render(
        "organizer_booking_completed.html",
        requester_name="Alex Morgan",
        vendor_name="Lagos Lens Co.",
        vendor_slug="lagos-lens",
        booking_reference="VB-12345",
        event_name="Tech Leaders Gala 2026",
        frontend_url="https://heelo.io",
    )
    assert "Service Completed for Tech Leaders Gala 2026" in html_org_comp
    assert "Leave a Review" in html_org_comp

    # 8. Vendor Payout Requested
    html_p_req = em.render(
        "vendor_payout_requested.html",
        business_name="Lagos Lens Co.",
        amount=200000.0,
        currency="NGN",
        bank_name="GTBank",
        account_number="0123456789",
        account_name="Lagos Lens Enterprises",
        frontend_url="https://heelo.io",
    )
    assert "Withdrawal Request Received" in html_p_req
    assert "200,000.00" in html_p_req
    assert "GTBank" in html_p_req

    # 9. Vendor Payout Completed
    html_p_comp = em.render(
        "vendor_payout_completed.html",
        business_name="Lagos Lens Co.",
        amount=200000.0,
        currency="NGN",
        bank_name="GTBank",
        account_number="0123456789",
        provider_reference="TRF-887766",
        frontend_url="https://heelo.io",
    )
    assert "Payout Successfully Disbursed!" in html_p_comp
    assert "TRF-887766" in html_p_comp

