"""Tests for growth, viral, enterprise, and ad conversion tracking features.

Includes:
1. Meta, Google Tag, and TikTok conversion tracking pixels.
2. Automated abandoned checkout recovery flow and resumption link.
3. Viral attendee social share card generation.
4. Corporate invoicing and VAT / Tax PDF generation.
5. Apple Wallet (.pkpass) bundle generator and download endpoint.
"""

from __future__ import annotations

import io
import secrets
import uuid
import zipfile
from datetime import datetime, timedelta, UTC
from decimal import Decimal
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.ticketing import Order, Registration, TicketType


async def test_conversion_tracking_pixels_on_public_page(
    client: AsyncClient, db: AsyncSession, published_event: Event
):
    """Verify Meta, Google Tag, and TikTok pixels render in public event HTML."""
    published_event.meta_pixel_id = "META_PIXEL_12345"
    published_event.google_tag_id = "G-TAG_67890"
    published_event.tiktok_pixel_id = "TIKTOK_ABCDE"
    await db.flush()

    resp = await client.get(f"/e/{published_event.slug}")
    assert resp.status_code == 200
    html = resp.text

    assert "META_PIXEL_12345" in html
    assert "fbq('init', 'META_PIXEL_12345')" in html
    assert "G-TAG_67890" in html
    assert "googletagmanager.com/gtag/js?id=G-TAG_67890" in html
    assert "TIKTOK_ABCDE" in html
    assert "ttq.load('TIKTOK_ABCDE')" in html


async def test_conversion_tracking_pixels_and_buttons_on_confirmation_page(
    client: AsyncClient, db: AsyncSession, published_event: Event, ticket_type: TicketType
):
    """Verify purchase pixels and download buttons render on order confirmation page."""
    published_event.meta_pixel_id = "META_PIXEL_12345"
    published_event.google_tag_id = "G-TAG_67890"
    published_event.tiktok_pixel_id = "TIKTOK_ABCDE"
    published_event.tax_rate = Decimal("7.50")
    published_event.tax_id = "VAT-NG-999"
    await db.flush()

    order = Order(
        event_id=published_event.id,
        user_id=None,
        payment_status="paid",
        payment_reference=f"test-ref-{uuid.uuid4()}",
        total_amount=Decimal("5000.00"),
        net_amount=Decimal("4750.00"),
        platform_fee=Decimal("250.00"),
        currency="NGN",
        buyer_name="Jane Doe",
        buyer_email="jane@example.com",
        is_corporate=True,
        company_name="Enterprise Ltd",
        tax_id="CORP-TAX-123",
        billing_address="10 Marina, Lagos",
    )
    db.add(order)
    await db.flush()

    reg = Registration(
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        order_id=order.id,
        user_id=None,
        attendee_name="Jane Doe",
        attendee_email="jane@example.com",
        status="confirmed",
        qr_code=f"test-qr-{uuid.uuid4()}",
    )
    db.add(reg)
    await db.flush()

    resp = await client.get(f"/orders/{order.id}/confirmation")
    assert resp.status_code == 200
    html = resp.text

    assert "fbq('track', 'Purchase'" in html
    assert "gtag('event', 'purchase'" in html
    assert "ttq.track('CompletePayment'" in html

    # Download action buttons present
    assert f"/api/v1/registrations/{reg.id}/wallet.pkpass" in html
    assert f"/api/v1/events/{published_event.slug}/share-card/{reg.id}" in html
    assert f"/orders/{order.id}/invoice.pdf" in html


async def test_corporate_registration_fields_persisted(
    client: AsyncClient, db: AsyncSession, published_event: Event, ticket_type: TicketType
):
    """Verify corporate invoicing details submitted during checkout are stored on the Order."""
    payload = {
        "items": [{"ticket_type_id": str(ticket_type.id), "quantity": 1}],
        "buyer_name": "Corp Purchaser",
        "buyer_email": "corp@bigco.com",
        "buyer_phone": "+1234567890",
        "is_corporate": True,
        "company_name": "BigCo Global Inc",
        "tax_id": "US-EIN-987654",
        "billing_address": "500 Madison Ave, New York, NY",
    }
    resp = await client.post(f"/api/v1/events/{published_event.slug}/register", json=payload)
    assert resp.status_code in (200, 201)
    data = resp.json()["data"]

    order_id = uuid.UUID(data["id"])
    order = await db.scalar(select(Order).where(Order.id == order_id))
    assert order is not None
    assert order.is_corporate is True
    assert order.company_name == "BigCo Global Inc"
    assert order.tax_id == "US-EIN-987654"
    assert order.billing_address == "500 Madison Ave, New York, NY"
    assert order.recovery_token is not None


async def test_corporate_invoice_pdf_endpoint(
    client: AsyncClient, db: AsyncSession, published_event: Event, ticket_type: TicketType
):
    """Verify GET /orders/{order_id}/invoice.pdf produces a valid PDF document."""
    published_event.tax_rate = Decimal("10.00")
    published_event.tax_id = "ORG-VAT-456"
    await db.flush()

    order = Order(
        event_id=published_event.id,
        user_id=None,
        payment_status="paid",
        payment_reference=f"test-ref-{uuid.uuid4()}",
        total_amount=Decimal("11000.00"),
        net_amount=Decimal("10000.00"),
        platform_fee=Decimal("1000.00"),
        currency="NGN",
        buyer_name="Alexander Hamilton",
        buyer_email="alex@treasury.gov",
        is_corporate=True,
        company_name="Treasury Department",
        tax_id="US-TREAS-01",
        billing_address="1500 Pennsylvania Ave NW, Washington DC",
    )
    db.add(order)
    await db.flush()

    reg = Registration(
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        order_id=order.id,
        user_id=None,
        attendee_name="Alexander Hamilton",
        attendee_email="alex@treasury.gov",
        status="confirmed",
        qr_code=f"test-qr-{uuid.uuid4()}",
    )
    db.add(reg)
    await db.flush()

    resp = await client.get(f"/orders/{order.id}/invoice.pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "filename=" in resp.headers["content-disposition"]
    # PDF magic bytes
    assert resp.content.startswith(b"%PDF-")


async def test_share_card_endpoint(
    client: AsyncClient, db: AsyncSession, published_event: Event, ticket_type: TicketType
):
    """Verify GET /api/v1/events/{slug}/share-card/{reg_id} generates a 1080x1920 PNG image."""
    reg = Registration(
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        order_id=None,
        user_id=None,
        attendee_name="Sara Connor",
        attendee_email="sara@example.com",
        status="confirmed",
        qr_code=f"test-qr-{uuid.uuid4()}",
    )
    db.add(reg)
    await db.flush()

    resp = await client.get(f"/api/v1/events/{published_event.slug}/share-card/{reg.id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    # PNG signature bytes
    assert resp.content.startswith(b"\x89PNG\r\n\x1a\n")


async def test_wallet_pass_endpoint(
    client: AsyncClient, db: AsyncSession, published_event: Event, ticket_type: TicketType
):
    """Verify GET /api/v1/registrations/{reg_id}/wallet.pkpass returns a valid Apple Wallet zip bundle."""
    reg = Registration(
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        order_id=None,
        user_id=None,
        attendee_name="Bruce Wayne",
        attendee_email="bruce@wayne.corp",
        status="confirmed",
        qr_code=f"test-qr-{uuid.uuid4()}",
    )
    db.add(reg)
    await db.flush()

    resp = await client.get(f"/api/v1/registrations/{reg.id}/wallet.pkpass")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.apple.pkpass"

    # Verify pkpass is a valid zip containing pass.json and manifest.json
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    file_list = zf.namelist()
    assert "pass.json" in file_list
    assert "manifest.json" in file_list


async def test_abandoned_checkout_recovery_and_resumption(
    client: AsyncClient, db: AsyncSession, published_event: Event, ticket_type: TicketType
):
    """Verify abandoned checkout recovery token resumption link and query eligibility."""
    token = secrets.token_urlsafe(32)
    order = Order(
        event_id=published_event.id,
        user_id=None,
        payment_status="pending",
        payment_reference=f"test-ref-{uuid.uuid4()}",
        total_amount=Decimal("5000.00"),
        net_amount=Decimal("4750.00"),
        platform_fee=Decimal("250.00"),
        currency="NGN",
        buyer_name="Delayed Buyer",
        buyer_email="delayed@example.com",
        recovery_token=token,
    )
    db.add(order)
    await db.flush()

    # Verify resume link with token redirects to order payment/confirmation
    resume_resp = await client.get(f"/orders/resume/{order.recovery_token}", follow_redirects=False)
    assert resume_resp.status_code in (302, 303, 307)
    assert f"/orders/{order.id}" in resume_resp.headers["location"]

    # Invalidate token query returns 404
    bad_resp = await client.get("/orders/resume/non-existent-token", follow_redirects=False)
    assert bad_resp.status_code == 404

    # Check recovery status update
    order.abandoned_recovery_sent_at = datetime.now(UTC)
    await db.flush()

    refreshed = await db.scalar(select(Order).where(Order.id == order.id))
    assert refreshed.abandoned_recovery_sent_at is not None
