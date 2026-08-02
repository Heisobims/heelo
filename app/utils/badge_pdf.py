"""
Attendee badge PDF generation via reportlab.

reportlab (not weasyprint) is used deliberately: weasyprint needs native
system libraries (Pango/cairo/gobject) that aren't guaranteed to be present
on the host, while reportlab is pure-Python and draws with its own built-in
base14 fonts — no font files or system packages required at all.

Pure drawing logic only — no I/O. Callers (badge_service.py) fetch the org
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

_DEFAULT_ACCENT = "#00B3A9"  # platform default cyan (dark variant, prints better than #00FFF3)


@dataclass
class BadgeData:
    attendee_name: str
    ticket_type_name: str
    event_title: str
    org_name: str
    brand_color: str | None = None
    logo_bytes: bytes | None = None
    qr_bytes: bytes | None = None


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


def _draw_badge(c: canvas.Canvas, data: BadgeData) -> None:
    accent = _accent(data)
    margin = 0.3 * inch
    content_width = BADGE_WIDTH - 2 * margin

    # Top accent band
    band_height = 0.9 * inch
    c.setFillColor(accent)
    c.rect(0, BADGE_HEIGHT - band_height, BADGE_WIDTH, band_height, fill=1, stroke=0)

    if data.logo_bytes:
        try:
            logo = ImageReader(BytesIO(data.logo_bytes))
            logo_size = 0.5 * inch
            c.drawImage(
                logo,
                margin,
                BADGE_HEIGHT - band_height / 2 - logo_size / 2,
                width=logo_size,
                height=logo_size,
                mask="auto",
                preserveAspectRatio=True,
            )
            org_x = margin + logo_size + 0.15 * inch
        except Exception:
            org_x = margin
    else:
        org_x = margin

    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(org_x, BADGE_HEIGHT - band_height / 2 - 5, data.org_name[:40])

    # Attendee name — the focal point
    c.setFillColor(HexColor("#0A0A0A"))
    name_font = "Helvetica-Bold"
    name_size = _fit_text(c, data.attendee_name, name_font, 30, 16, content_width)
    c.setFont(name_font, name_size)
    name_y = BADGE_HEIGHT - band_height - 0.7 * inch
    c.drawCentredString(BADGE_WIDTH / 2, name_y, data.attendee_name[:60])

    # Ticket tier pill
    tier_text = data.ticket_type_name.upper()
    c.setFont("Helvetica-Bold", 11)
    pill_width = c.stringWidth(tier_text, "Helvetica-Bold", 11) + 0.4 * inch
    pill_height = 0.32 * inch
    pill_x = (BADGE_WIDTH - pill_width) / 2
    pill_y = name_y - 0.5 * inch
    c.setFillColor(accent)
    c.roundRect(pill_x, pill_y, pill_width, pill_height, pill_height / 2, fill=1, stroke=0)
    c.setFillColor(white)
    c.drawCentredString(BADGE_WIDTH / 2, pill_y + pill_height / 2 - 4, tier_text)

    # QR code
    if data.qr_bytes:
        qr_size = 1.9 * inch
        qr_img = ImageReader(BytesIO(data.qr_bytes))
        qr_x = (BADGE_WIDTH - qr_size) / 2
        qr_y = 0.55 * inch
        c.setFillColor(white)
        c.setStrokeColor(HexColor("#E5E5E0"))
        c.roundRect(
            qr_x - 0.12 * inch,
            qr_y - 0.12 * inch,
            qr_size + 0.24 * inch,
            qr_size + 0.24 * inch,
            8,
            fill=1,
            stroke=1,
        )
        c.drawImage(qr_img, qr_x, qr_y, width=qr_size, height=qr_size)

    # Event title footer
    c.setFillColor(HexColor("#6B6B6B"))
    c.setFont("Helvetica", 9)
    c.drawCentredString(BADGE_WIDTH / 2, 0.3 * inch, data.event_title[:60])


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
