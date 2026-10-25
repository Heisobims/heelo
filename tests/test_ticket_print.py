import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.organization import Organization
from app.models.ticketing import Order, Registration, TicketType
from app.models.user import User
from tests.conftest import _make_token


@pytest.mark.asyncio
async def test_ticket_view_page_responsive_nav_and_single_page_print(
    client: AsyncClient, db: AsyncSession, published_event: Event, ticket_type: TicketType, user: User, org: Organization
):
    """Verify ticket view (/my-tickets/{id}) contains the responsive top navigation bar,
    the authentic previous card design with terracotta accents and cutouts, and single-page print rules."""
    reg = Registration(
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        user_id=user.id,
        attendee_name="Ada Lovelace",
        attendee_email=user.email,
        qr_code="QR-ADA-99120",
        status="confirmed",
    )
    db.add(reg)
    await db.flush()

    token = _make_token(str(user.id))
    resp = await client.get(
        f"/my-tickets/{reg.id}",
        cookies={"heelo_access": token},
    )
    assert resp.status_code == 200
    html = resp.text

    # Responsive navigation bar elements
    assert "tv-nav" in html
    assert "tv-nav-inner" in html
    assert "tv-nav-back" in html
    assert "tv-nav-brand" in html
    assert "tv-nav-print-btn" in html

    # Authentic ticket design elements
    assert "Ada Lovelace" in html
    assert published_event.title in html
    assert "ticket-perf" in html
    assert "ticket-head" in html
    assert "ticket-stub" in html
    assert f"/api/v1/registrations/{reg.id}/qr.png" in html

    # Single page print stylesheet rules
    assert "@media print" in html
    assert "@page" in html
    assert "page-break-inside: avoid !important;" in html
    assert "page-break-after: avoid !important;" in html
    assert ".tv-nav," in html
    assert ".tv-actions," in html


@pytest.mark.asyncio
async def test_order_confirmation_page_returns_ok_with_tickets(
    client: AsyncClient, db: AsyncSession, published_event: Event, ticket_type: TicketType, org: Organization
):
    """Verify order confirmation page (/orders/{id}/confirmation) renders ticket stubs correctly."""
    order = Order(
        event_id=published_event.id,
        buyer_name="Kwame Nkrumah",
        buyer_email="kwame@example.com",
        payment_status="paid",
        currency="NGN",
        total_amount=5000,
        net_amount=4500,
        platform_fee=350,
        gateway_fee_amount=150,
        fees_passed_to_buyer=True,
    )
    db.add(order)
    await db.flush()

    reg = Registration(
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        order_id=order.id,
        attendee_name="Kwame Nkrumah",
        attendee_email="kwame@example.com",
        qr_code="QR-KWAME-77192",
        status="confirmed",
    )
    db.add(reg)
    await db.flush()

    resp = await client.get(f"/orders/{order.id}/confirmation")
    assert resp.status_code == 200
    html = resp.text

    assert published_event.title in html
    assert "Kwame Nkrumah" in html
    assert f"/api/v1/registrations/{reg.id}/qr.png" in html
    assert "ticket-stub" in html
    assert "no-print" in html


def test_global_main_css_print_optimization():
    """Verify app/static/css/main.css provides global print rules hiding AI chatbot and cookie consent."""
    with open("app/static/css/main.css", "r", encoding="utf-8") as f:
        content = f.read()

    assert "@media print" in content
    assert ".heelo-ai-widget-root" in content
    assert "#heelo-cookie-consent" in content
    assert ".no-print" in content
    assert "break-inside: avoid !important;" in content
