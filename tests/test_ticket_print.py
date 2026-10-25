from io import BytesIO
import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.organization import Organization
from app.models.ticketing import Order, Registration, TicketType
from app.models.user import User
from tests.conftest import _make_token


@pytest.mark.asyncio
async def test_ticket_view_page_responsive_and_print_elements(
    client: AsyncClient, db: AsyncSession, published_event: Event, ticket_type: TicketType, user: User, org: Organization
):
    """Verify the dedicated ticket view (/my-tickets/{id}) contains responsive elements,
    branded QR code integration, and print-optimized styles with web noise omitted."""
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

    # Core ticket information
    assert "Ada Lovelace" in html
    assert published_event.title in html
    assert "TICKET ID:" in html
    assert str(reg.id) in html
    assert f"/api/v1/registrations/{reg.id}/qr.png" in html

    # Responsive and print classes
    assert "tv-actions" in html
    assert "ticket-print-instruction" in html
    assert "@media print" in html
    assert "Present this QR code on arrival for admission." in html

    # Irrelevant noise hidden in print styles
    assert ".tv-actions," in html
    assert ".tv-nav," in html
    assert ".tv-referral-card," in html
    assert ".heelo-ai-widget-root," in html


@pytest.mark.asyncio
async def test_order_confirmation_print_ticket_stubs_and_clean_header(
    client: AsyncClient, db: AsyncSession, published_event: Event, ticket_type: TicketType, org: Organization
):
    """Verify order confirmation page (/orders/{id}/confirmation) features a clean
    print-only order header, responsive ticket stubs, and hides billing fee details in print."""
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

    # Core ticket elements
    assert "print-order-header" in html
    assert "HEELO TICKET PASS" in html
    assert published_event.title in html
    assert "Kwame Nkrumah" in html
    assert f"/api/v1/registrations/{reg.id}/qr.png" in html

    # Screen elements classified for print exclusion
    assert "conf-billing" in html
    assert "conf-hero" in html
    assert "conf-actions" in html

    # Print stylesheet verification
    assert "@media print" in html
    assert ".conf-billing," in html
    assert ".conf-hero," in html
    assert "ticket-stub" in html


def test_global_main_css_print_optimization():
    """Verify app/static/css/main.css provides global print rules hiding AI chatbot and cookie consent."""
    with open("app/static/css/main.css", "r", encoding="utf-8") as f:
        content = f.read()

    assert "@media print" in content
    assert ".heelo-ai-widget-root" in content
    assert "#heelo-cookie-consent" in content
    assert ".no-print" in content
    assert "break-inside: avoid !important;" in content

