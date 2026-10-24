"""
Corporate Tax Invoice / Receipt PDF generation via ReportLab.
Generates an official VAT/Tax compliant invoice for attendees and corporate expense teams.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

PAGE_WIDTH, PAGE_HEIGHT = letter

_INK = HexColor("#111111")
_MUTED = HexColor("#666666")
_BORDER = HexColor("#E2E8F0")
_BG_LIGHT = HexColor("#F8FAFC")
_GREEN = HexColor("#16A34A")


@dataclass
class InvoiceItem:
    description: str
    quantity: int
    unit_price: float
    total: float


@dataclass
class InvoiceData:
    invoice_number: str
    issue_date: datetime
    event_title: str
    org_name: str
    org_email: str | None
    org_tax_id: str | None
    buyer_name: str
    buyer_email: str
    buyer_company: str | None
    buyer_tax_id: str | None
    buyer_billing_address: str | None
    currency: str
    items: list[InvoiceItem]
    subtotal: float
    tax_rate: float | None
    tax_amount: float
    total_amount: float
    payment_reference: str | None
    payment_provider: str | None
    brand_color: str | None = None


def generate_invoice_pdf(data: InvoiceData) -> bytes:
    """Generate a clean, single-page corporate tax invoice PDF."""
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)

    margin = 54  # 0.75 in
    y = PAGE_HEIGHT - margin

    # Brand color accent
    accent = HexColor(data.brand_color) if data.brand_color and data.brand_color.startswith("#") else HexColor("#0A0A0A")

    # ── Header ──────────────────────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 24)
    c.setFillColor(accent)
    c.drawString(margin, y, "TAX INVOICE")

    # Paid Badge
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(_GREEN)
    c.roundRect(PAGE_WIDTH - margin - 80, y - 6, 80, 26, 4, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.drawCentredString(PAGE_WIDTH - margin - 40, y + 2, "PAID")

    y -= 30
    c.setFont("Helvetica", 10)
    c.setFillColor(_MUTED)
    c.drawString(margin, y, f"Invoice Number: {data.invoice_number}")
    c.drawRightString(PAGE_WIDTH - margin, y, f"Date: {data.issue_date.strftime('%B %d, %Y')}")

    y -= 16
    if data.payment_reference:
        c.drawString(margin, y, f"Payment Reference: {data.payment_reference}")
    if data.payment_provider:
        c.drawRightString(PAGE_WIDTH - margin, y, f"Payment Method: {data.payment_provider.title()}")

    y -= 25
    c.setStrokeColor(_BORDER)
    c.setLineWidth(1)
    c.line(margin, y, PAGE_WIDTH - margin, y)

    # ── Seller & Buyer Addresses ─────────────────────────────────────────────
    y -= 25
    col_width = (PAGE_WIDTH - (margin * 2) - 40) / 2

    # Left: Seller (Organizer)
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(_INK)
    c.drawString(margin, y, "ISSUED BY (ORGANIZER):")
    y_seller = y - 16
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, y_seller, data.org_name[:40])
    y_seller -= 14
    c.setFont("Helvetica", 9)
    c.setFillColor(_MUTED)
    if data.org_email:
        c.drawString(margin, y_seller, f"Email: {data.org_email}")
        y_seller -= 13
    if data.org_tax_id:
        c.drawString(margin, y_seller, f"Tax / VAT ID: {data.org_tax_id}")
        y_seller -= 13
    c.drawString(margin, y_seller, f"Event: {data.event_title[:45]}")

    # Right: Buyer (Customer / Company)
    buyer_x = margin + col_width + 40
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(_INK)
    c.drawString(buyer_x, y, "BILLED TO (CUSTOMER):")
    y_buyer = y - 16
    c.setFont("Helvetica-Bold", 11)
    c.drawString(buyer_x, y_buyer, (data.buyer_company or data.buyer_name)[:40])
    y_buyer -= 14
    c.setFont("Helvetica", 9)
    c.setFillColor(_MUTED)
    c.drawString(buyer_x, y_buyer, f"Contact: {data.buyer_name} ({data.buyer_email})")
    y_buyer -= 13
    if data.buyer_tax_id:
        c.drawString(buyer_x, y_buyer, f"Tax / VAT ID: {data.buyer_tax_id}")
        y_buyer -= 13
    if data.buyer_billing_address:
        # Wrap address
        addr_lines = data.buyer_billing_address.replace("\r", "").split("\n")
        for line in addr_lines[:3]:
            c.drawString(buyer_x, y_buyer, line[:45])
            y_buyer -= 13

    y = min(y_seller, y_buyer) - 25

    # ── Itemized Table Header ────────────────────────────────────────────────
    c.setFillColor(_BG_LIGHT)
    c.roundRect(margin, y - 20, PAGE_WIDTH - (margin * 2), 24, 4, fill=1, stroke=0)

    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(_INK)
    c.drawString(margin + 12, y - 13, "DESCRIPTION")
    c.drawCentredString(margin + 320, y - 13, "QTY")
    c.drawRightString(PAGE_WIDTH - margin - 120, y - 13, "UNIT PRICE")
    c.drawRightString(PAGE_WIDTH - margin - 12, y - 13, "AMOUNT")

    y -= 36

    # ── Line Items ───────────────────────────────────────────────────────────
    c.setFont("Helvetica", 9)
    c.setFillColor(_INK)
    for item in data.items:
        c.drawString(margin + 12, y, item.description[:45])
        c.drawCentredString(margin + 320, y, str(item.quantity))
        c.drawRightString(PAGE_WIDTH - margin - 120, y, f"{data.currency} {item.unit_price:,.2f}")
        c.drawRightString(PAGE_WIDTH - margin - 12, y, f"{data.currency} {item.total:,.2f}")
        y -= 20
        c.setStrokeColor(_BORDER)
        c.line(margin, y + 6, PAGE_WIDTH - margin, y + 6)
        y -= 6

    # ── Totals ───────────────────────────────────────────────────────────────
    y -= 15
    totals_x = PAGE_WIDTH - margin - 220
    val_x = PAGE_WIDTH - margin - 12

    c.setFont("Helvetica", 9)
    c.setFillColor(_MUTED)
    c.drawString(totals_x, y, "Subtotal:")
    c.drawRightString(val_x, y, f"{data.currency} {data.subtotal:,.2f}")
    y -= 18

    if data.tax_rate and data.tax_amount > 0:
        c.drawString(totals_x, y, f"VAT / Tax ({data.tax_rate:.1f}%):")
        c.drawRightString(val_x, y, f"{data.currency} {data.tax_amount:,.2f}")
        y -= 18

    c.setStrokeColor(_BORDER)
    c.line(totals_x, y + 6, val_x, y + 6)
    y -= 6

    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(_INK)
    c.drawString(totals_x, y, "Total Paid:")
    c.drawRightString(val_x, y, f"{data.currency} {data.total_amount:,.2f}")

    # ── Footer ───────────────────────────────────────────────────────────────
    c.setFont("Helvetica", 8)
    c.setFillColor(_MUTED)
    footer_text = "This receipt was automatically generated and verified by Heelo (heelo.io). Thank you for your business."
    c.drawCentredString(PAGE_WIDTH / 2, margin + 20, footer_text)

    c.showPage()
    c.save()
    return buffer.getvalue()

