"""
Certificate of Attendance PDF generation via reportlab — same engine and
same "pure drawing logic, no I/O" separation as badge_pdf.py, for the same
reason (no native system libraries required, unlike weasyprint).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

PAGE_WIDTH, PAGE_HEIGHT = landscape(letter)

_DEFAULT_ACCENT = "#00B3A9"
_INK = HexColor("#0A0A0A")
_MUTED = HexColor("#6B6B6B")


@dataclass
class CertificateData:
    attendee_name: str
    event_title: str
    org_name: str
    event_date: datetime
    brand_color: str | None = None


def _accent(data: CertificateData):
    if data.brand_color:
        try:
            return HexColor(data.brand_color)
        except ValueError:
            pass
    return HexColor(_DEFAULT_ACCENT)


def _draw_certificate(c: canvas.Canvas, data: CertificateData) -> None:
    accent = _accent(data)
    margin = 0.5 * inch

    # Outer border
    c.setStrokeColor(accent)
    c.setLineWidth(3)
    c.rect(margin, margin, PAGE_WIDTH - 2 * margin, PAGE_HEIGHT - 2 * margin, fill=0, stroke=1)
    # Inner hairline
    inset = margin + 0.12 * inch
    c.setLineWidth(0.75)
    c.setStrokeColor(HexColor("#D5D5D0"))
    c.rect(inset, inset, PAGE_WIDTH - 2 * inset, PAGE_HEIGHT - 2 * inset, fill=0, stroke=1)

    center_x = PAGE_WIDTH / 2

    # Org name
    c.setFillColor(accent)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(center_x, PAGE_HEIGHT - 1.35 * inch, data.org_name.upper())

    # Title
    c.setFillColor(_INK)
    c.setFont("Times-Bold", 34)
    c.drawCentredString(center_x, PAGE_HEIGHT - 2.15 * inch, "Certificate of Attendance")

    # "This certifies that"
    c.setFillColor(_MUTED)
    c.setFont("Times-Italic", 14)
    c.drawCentredString(center_x, PAGE_HEIGHT - 2.85 * inch, "This certifies that")

    # Attendee name — the focal point
    c.setFillColor(_INK)
    name_font = "Times-Bold"
    name_size = 36
    max_width = PAGE_WIDTH - 3 * inch
    while name_size > 20 and c.stringWidth(data.attendee_name, name_font, name_size) > max_width:
        name_size -= 1
    c.setFont(name_font, name_size)
    c.drawCentredString(center_x, PAGE_HEIGHT - 3.7 * inch, data.attendee_name)

    # Underline beneath the name
    name_width = c.stringWidth(data.attendee_name, name_font, name_size)
    underline_y = PAGE_HEIGHT - 3.95 * inch
    c.setStrokeColor(accent)
    c.setLineWidth(1.5)
    c.line(center_x - name_width / 2 - 20, underline_y, center_x + name_width / 2 + 20, underline_y)

    # "attended <event>"
    c.setFillColor(_MUTED)
    c.setFont("Times-Roman", 15)
    c.drawCentredString(center_x, PAGE_HEIGHT - 4.5 * inch, "for attending")

    c.setFillColor(_INK)
    c.setFont("Times-Bold", 20)
    c.drawCentredString(center_x, PAGE_HEIGHT - 4.95 * inch, data.event_title[:80])

    # Date
    c.setFillColor(_MUTED)
    c.setFont("Times-Roman", 13)
    c.drawCentredString(center_x, PAGE_HEIGHT - 5.5 * inch, data.event_date.strftime("%B %-d, %Y"))


def generate_certificate_pdf(certificates: list[CertificateData]) -> bytes:
    """One page per certificate."""
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    for data in certificates:
        _draw_certificate(c, data)
        c.showPage()
    c.save()
    return buf.getvalue()
