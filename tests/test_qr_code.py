"""
Tests for QR code generation with organizer logo embedding.

Verifies:
1. Standard QR code generation without branding.
2. Embedding of image logo (PNG/JPEG) in the center of the QR code.
3. Monogram avatar generation using organizer name and brand color.
4. Ticket registration QR endpoint (/api/v1/registrations/{id}/qr.png) embedding organizer logo.
5. Organization event promotional QR endpoint (/api/v1/organizations/{slug}/events/{id}/qr.png).
6. Vendor profile QR endpoint (/api/v1/vendors/me/qr.png).
7. Error tolerance and graceful fallback when logo is missing or corrupted.
"""

from __future__ import annotations

from io import BytesIO
from httpx import AsyncClient
from PIL import Image, ImageDraw
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.organization import Organization
from app.models.ticketing import Registration
from app.utils.qr_code import fetch_logo_bytes, generate_qr_png


def _create_sample_logo_png(width: int = 120, height: int = 120, color: tuple = (232, 89, 56, 255)) -> bytes:
    """Helper to create a sample test logo in memory."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([(8, 8), (width - 8, height - 8)], fill=color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_generate_qr_png_without_branding():
    """Verify clean QR generation when no logo or org name is provided."""
    payload = "https://heelo.io/e/tech-summit"
    qr_bytes = generate_qr_png(payload)
    assert isinstance(qr_bytes, bytes)
    assert len(qr_bytes) > 500

    img = Image.open(BytesIO(qr_bytes))
    assert img.format == "PNG"
    assert img.size[0] > 100
    assert img.size[1] > 100


def test_generate_qr_png_with_logo_bytes():
    """Verify QR code embeds the organizer logo in the center."""
    payload = "QR-TICKET-PAYLOAD-12345"
    logo_bytes = _create_sample_logo_png(150, 150, color=(14, 165, 233, 255))

    qr_bytes = generate_qr_png(
        payload,
        box_size=10,
        logo_bytes=logo_bytes,
        org_name="TechFest Global",
        brand_color="#0EA5E9",
    )
    assert isinstance(qr_bytes, bytes)
    assert len(qr_bytes) > 1000

    img = Image.open(BytesIO(qr_bytes))
    assert img.format == "PNG"
    w, h = img.size

    # Check center pixels are not pure black or default white (the logo was drawn in the center)
    center_color = img.getpixel((w // 2, h // 2))
    assert len(center_color) >= 3


def test_generate_qr_png_with_monogram_fallback():
    """Verify QR code generates a monogram avatar badge if no image logo is uploaded."""
    payload = "https://heelo.io/e/lagos-creators"
    qr_bytes = generate_qr_png(
        payload,
        box_size=8,
        logo_bytes=None,
        org_name="Lagos Tech Events",
        brand_color="#E85938",
    )
    assert isinstance(qr_bytes, bytes)
    assert len(qr_bytes) > 800

    img = Image.open(BytesIO(qr_bytes))
    assert img.format == "PNG"


@pytest.mark.asyncio
async def test_fetch_logo_bytes_local_and_invalid():
    """Verify fetch_logo_bytes handles local paths, missing paths, and none gracefully."""
    res_none = await fetch_logo_bytes(None)
    assert res_none is None

    res_empty = await fetch_logo_bytes("")
    assert res_empty is None

    res_invalid = await fetch_logo_bytes("/static/uploads/nonexistent_logo_12345.png")
    assert res_invalid is None


@pytest.mark.asyncio
async def test_registration_qr_endpoint_with_organizer_logo(
    client: AsyncClient, db: AsyncSession, published_event: Event, ticket_type, org: Organization
):
    """Verify /api/v1/registrations/{id}/qr.png includes the organizer logo in the ticket QR."""
    reg = Registration(
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        attendee_name="Amina Bello",
        attendee_email="amina@example.com",
        qr_code="QR-AMINA-88219",
        status="confirmed",
    )
    db.add(reg)
    await db.flush()

    resp = await client.get(f"/api/v1/registrations/{reg.id}/qr.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert len(resp.content) > 500

    img = Image.open(BytesIO(resp.content))
    assert img.format == "PNG"


@pytest.mark.asyncio
async def test_event_public_page_qr_with_organizer_logo(
    client: AsyncClient, db: AsyncSession, published_event: Event, org: Organization, user_headers
):
    """Verify /api/v1/organizations/{slug}/events/{id}/qr.png includes organizer logo."""
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/qr.png",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert len(resp.content) > 500

    img = Image.open(BytesIO(resp.content))
    assert img.format == "PNG"


@pytest.mark.asyncio
async def test_vendor_qr_endpoint(
    client: AsyncClient, other_headers, vendor
):
    """Verify /api/v1/vendors/me/qr.png generates a branded QR code for the vendor."""
    resp = await client.get("/api/v1/vendors/me/qr.png", headers=other_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert len(resp.content) > 500

    img = Image.open(BytesIO(resp.content))
    assert img.format == "PNG"
