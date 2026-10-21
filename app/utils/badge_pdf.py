"""
Attendee badge PDF generation via reportlab.

reportlab (not weasyprint) is used deliberately: weasyprint needs native
system libraries (Pango/cairo/gobject) that aren't guaranteed to be present
on the host, while reportlab is pure-Python and draws with its own built-in
base14 fonts - no font files or system packages required at all.

Pure drawing logic only - no I/O. Callers (badge_service.py) fetch the org
logo and generate the QR code beforehand and pass in raw bytes, so this
module stays trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from reportlab.lib.colors import HexColor, white
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

BADGE_WIDTH = 4 * inch
BADGE_HEIGHT = 6 * inch

_DEFAULT_ACCENT = "#E85938"  # Heelo brand terracotta
_INK = "#0A0A0A"  # Heelo brand near-black - the badge's other brand color


@dataclass
class BadgeData:
    attendee_name: str
    ticket_type_name: str
    event_title: str
    org_name: str
    brand_color: str | None = None
    logo_bytes: bytes | None = None
    qr_bytes: bytes | None = None
    show_powered_by: bool = True
    attendee_email: str | None = None


def _accent(data: BadgeData):
    if data.brand_color:
        try:
            return HexColor(data.brand_color)
        except ValueError:
            pass
    return HexColor(_DEFAULT_ACCENT)


def _fit_text(
    c: canvas.Canvas, text: str, font: str, max_size: int, min_size: int, max_width: float
) -> int:
    """Largest font size (down to min_size) that keeps `text` within max_width."""
    size = max_size
    while size > min_size and c.stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def _corner_brackets(
    c: canvas.Canvas, x: float, y: float, w: float, h: float, arm: float, color
) -> None:
    """Four small L-shaped marks at the corners of a rect - a "scan target"
    accent around the QR code instead of a plain border."""
    c.setStrokeColor(color)
    c.setLineWidth(1.6)
    corners = [(x, y, 1, 1), (x + w, y, -1, 1), (x, y + h, 1, -1), (x + w, y + h, -1, -1)]
    for cx, cy, dx, dy in corners:
        p = c.beginPath()
        p.moveTo(cx, cy + dy * arm)
        p.lineTo(cx, cy)
        p.lineTo(cx + dx * arm, cy)
        c.drawPath(p, stroke=1, fill=0)


def _draw_badge(c: canvas.Canvas, data: BadgeData) -> None:
    accent = _accent(data)
    ink = HexColor(_INK)
    corner_r = 18.0
    content_width = BADGE_WIDTH - 0.5 * inch

    # ── Clip outer perimeter to rounded rectangle ─────────────────────────────
    c.saveState()
    clip_p = c.beginPath()
    clip_p.roundRect(0, 0, BADGE_WIDTH, BADGE_HEIGHT, corner_r)
    c.clipPath(clip_p, stroke=0)

    # Base white canvas
    c.setFillColor(white)
    c.rect(0, 0, BADGE_WIDTH, BADGE_HEIGHT, fill=1, stroke=0)

    # ── Top Header Section (Grid Texture & Branding) ─────────────────────────
    header_height = 1.38 * inch
    header_bottom = BADGE_HEIGHT - header_height

    # Soft warm pastel background tint for the header
    c.saveState()
    c.setFillColor(accent)
    c.setFillAlpha(0.08)
    c.rect(0, header_bottom, BADGE_WIDTH, header_height, fill=1, stroke=0)
    c.restoreState()

    # Subtle geometric grid pattern across the header
    c.saveState()
    c.setStrokeColor(accent)
    c.setStrokeAlpha(0.22)
    c.setLineWidth(0.65)
    step = 13.0
    # Vertical grid lines
    gx = step
    while gx < BADGE_WIDTH:
        c.line(gx, header_bottom, gx, BADGE_HEIGHT)
        gx += step
    # Horizontal grid lines
    gy = header_bottom
    while gy < BADGE_HEIGHT:
        c.line(0, gy, BADGE_WIDTH, gy)
        gy += step
    c.restoreState()

    # Stadium-shaped lanyard hole slot (centered horizontally)
    slot_w = 0.82 * inch
    slot_h = 0.22 * inch
    slot_r = slot_h / 2
    slot_x = (BADGE_WIDTH - slot_w) / 2
    slot_y = BADGE_HEIGHT - 0.36 * inch

    c.setFillColor(white)
    c.setStrokeColor(ink)
    c.setLineWidth(1.1)
    c.roundRect(slot_x, slot_y, slot_w, slot_h, slot_r, fill=1, stroke=1)

    # Organization Branding / Logo
    # Positioned centered vertically in remaining header space below the slot
    brand_center_y = header_bottom + (slot_y - header_bottom) / 2
    logo_size = 22.0
    font_name = "Helvetica-Bold"
    font_size = 13.5
    org_display = data.org_name[:30]
    text_w = c.stringWidth(org_display, font_name, font_size)

    if data.logo_bytes:
        try:
            logo = ImageReader(BytesIO(data.logo_bytes))
            spacing = 8.0
            total_w = logo_size + spacing + text_w
            start_x = (BADGE_WIDTH - total_w) / 2
            logo_y = brand_center_y - (logo_size / 2)
            c.drawImage(
                logo,
                start_x,
                logo_y,
                width=logo_size,
                height=logo_size,
                mask="auto",
                preserveAspectRatio=True,
            )
            c.setFillColor(ink)
            c.setFont(font_name, font_size)
            c.drawString(start_x + logo_size + spacing, brand_center_y - 4.5, org_display)
        except Exception:
            c.setFillColor(ink)
            c.setFont(font_name, font_size)
            c.drawCentredString(BADGE_WIDTH / 2, brand_center_y - 4.5, org_display)
    else:
        # Clean circular brand badge with lightning bolt
        spacing = 8.0
        total_w = logo_size + spacing + text_w
        start_x = (BADGE_WIDTH - total_w) / 2
        logo_y = brand_center_y - (logo_size / 2)

        # Draw stylish circular badge
        c.setFillColor(ink)
        c.circle(start_x + (logo_size / 2), brand_center_y, logo_size / 2, fill=1, stroke=0)

        # Lightning bolt glyph inside badge
        c.saveState()
        c.setFillColor(white)
        p = c.beginPath()
        bx = start_x + (logo_size / 2)
        by = brand_center_y
        p.moveTo(bx + 1.2, by + 5.5)
        p.lineTo(bx - 3.8, by - 0.5)
        p.lineTo(bx - 0.2, by - 0.5)
        p.lineTo(bx - 1.2, by - 5.5)
        p.lineTo(bx + 3.8, by + 0.5)
        p.lineTo(bx + 0.2, by + 0.5)
        p.close()
        c.drawPath(p, fill=1, stroke=0)
        c.restoreState()

        # Organization title
        c.setFillColor(ink)
        c.setFont(font_name, font_size)
        c.drawString(start_x + logo_size + spacing, brand_center_y - 4.5, org_display)

    # ── Bottom Full-Width Banner ─────────────────────────────────────────────
    banner_height = 1.08 * inch
    c.setFillColor(accent)
    c.rect(0, 0, BADGE_WIDTH, banner_height, fill=1, stroke=0)

    # Role / Category title in bold white capital letters
    tier_text = data.ticket_type_name.upper()
    tier_size = _fit_text(c, tier_text, "Helvetica-Bold", 17, 10, content_width)
    c.setFont("Helvetica-Bold", tier_size)
    c.setFillColor(white)

    if data.show_powered_by:
        tier_y = (banner_height / 2) + 2.5
        c.drawCentredString(BADGE_WIDTH / 2, tier_y, tier_text)
        c.saveState()
        c.setFillAlpha(0.65)
        c.setFont("Helvetica", 6.2)
        c.drawCentredString(BADGE_WIDTH / 2, 10.0, "Powered by Heelo  •  heelo.io")
        c.restoreState()
    else:
        tier_y = (banner_height / 2) - (tier_size / 2.8)
        c.drawCentredString(BADGE_WIDTH / 2, tier_y, tier_text)

    # ── Middle Section (Attendee Details & QR Code) ──────────────────────────
    name_font = "Helvetica-Bold"
    name_size = _fit_text(c, data.attendee_name, name_font, 23, 14, content_width)
    name_y = header_bottom - 0.48 * inch
    c.setFont(name_font, name_size)
    c.setFillColor(ink)
    c.drawCentredString(BADGE_WIDTH / 2, name_y, data.attendee_name[:50])

    # Subtitle: Email address or event title
    sub_text = data.attendee_email or data.event_title or ""
    sub_y = name_y - 17.0
    if sub_text:
        sub_font_size = _fit_text(c, sub_text, "Helvetica", 10.5, 8, content_width)
        c.setFont("Helvetica", sub_font_size)
        c.setFillColor(HexColor("#262626"))
        c.drawCentredString(BADGE_WIDTH / 2, sub_y, sub_text[:50])

    # Centered large crisp QR Code
    if data.qr_bytes:
        qr_size = 2.05 * inch
        qr_img = ImageReader(BytesIO(data.qr_bytes))
        qr_x = (BADGE_WIDTH - qr_size) / 2
        # Center vertically between banner_height and sub_y
        available_top = sub_y - 14.0
        available_bottom = banner_height + 12.0
        qr_y = available_bottom + (available_top - available_bottom - qr_size) / 2
        c.drawImage(qr_img, qr_x, qr_y, width=qr_size, height=qr_size)

    # Restore from clipping path
    c.restoreState()

    # ── Outer Subtle Contour Guide (for card cutting / punch pouch) ───────────
    c.setStrokeColor(HexColor("#DCD7CD"))
    c.setLineWidth(0.8)
    c.roundRect(0, 0, BADGE_WIDTH, BADGE_HEIGHT, corner_r, fill=0, stroke=1)


def generate_badge_pdf(badges: list[BadgeData]) -> bytes:
    """One page per badge. Pass a single-item list for one attendee, or every
    registration on an event for a bulk print run."""
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(BADGE_WIDTH, BADGE_HEIGHT))
    for data in badges:
        _draw_badge(c, data)
        c.showPage()
    c.save()
    return buf.getvalue()
