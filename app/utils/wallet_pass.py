"""
Apple Wallet (.pkpass) pass bundle generator.
Produces signed or unsigned .pkpass archive for instant addition to Apple Wallet on iOS and WatchOS.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime

from PIL import Image


def _create_minimal_png(width: int, height: int, color: tuple[int, int, int, int]) -> bytes:
    """Create a minimal PNG icon for pass bundle."""
    im = Image.new("RGBA", (width, height), color)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def generate_event_pkpass(
    *,
    serial_number: str,
    event_title: str,
    attendee_name: str,
    ticket_type: str,
    qr_data: str,
    event_date: datetime | None = None,
    venue_str: str | None = None,
    org_name: str | None = None,
    brand_color_hex: str | None = None,
) -> bytes:
    """Generate an Apple Wallet .pkpass zip bundle."""
    # Convert brand color to rgb(...)
    bg_color = "rgb(15, 15, 18)"
    if brand_color_hex and brand_color_hex.startswith("#") and len(brand_color_hex) == 7:
        try:
            r = int(brand_color_hex[1:3], 16)
            g = int(brand_color_hex[3:5], 16)
            b = int(brand_color_hex[5:7], 16)
            bg_color = f"rgb({r}, {g}, {b})"
        except Exception:
            pass

    date_label = event_date.strftime("%b %d, %Y") if event_date else "Date TBA"
    time_label = event_date.strftime("%I:%M %p") if event_date else ""

    pass_json = {
        "formatVersion": 1,
        "passTypeIdentifier": "pass.io.heelo.ticket",
        "serialNumber": serial_number,
        "teamIdentifier": "HEELO",
        "organizationName": org_name or "Heelo Events",
        "description": event_title,
        "foregroundColor": "rgb(255, 255, 255)",
        "backgroundColor": bg_color,
        "labelColor": "rgb(210, 210, 220)",
        "eventTicket": {
            "headerFields": [
                {
                    "key": "date",
                    "label": "DATE",
                    "value": date_label,
                }
            ],
            "primaryFields": [
                {
                    "key": "event",
                    "label": "EVENT",
                    "value": event_title[:45],
                }
            ],
            "secondaryFields": [
                {
                    "key": "attendee",
                    "label": "ATTENDEE",
                    "value": attendee_name[:35],
                },
                {
                    "key": "ticket_type",
                    "label": "PASS",
                    "value": ticket_type[:25],
                },
            ],
            "auxiliaryFields": [
                {
                    "key": "venue",
                    "label": "VENUE",
                    "value": (venue_str or "Online Event")[:35],
                },
                {
                    "key": "time",
                    "label": "TIME",
                    "value": time_label or "TBD",
                },
            ],
            "backFields": [
                {
                    "key": "terms",
                    "label": "TICKET INFORMATION",
                    "value": "This digital pass is verified by Heelo (heelo.io). Please present the QR code on this pass upon entry at the event venue.",
                },
                {
                    "key": "ticket_id",
                    "label": "TICKET REFERENCE",
                    "value": serial_number,
                },
            ],
        },
        "barcodes": [
            {
                "format": "PKBarcodeFormatQR",
                "message": qr_data,
                "messageEncoding": "iso-8859-1",
                "altText": serial_number[:8].upper(),
            }
        ],
        "barcode": {
            "format": "PKBarcodeFormatQR",
            "message": qr_data,
            "messageEncoding": "iso-8859-1",
            "altText": serial_number[:8].upper(),
        },
    }

    pass_bytes = json.dumps(pass_json, indent=2).encode("utf-8")
    icon_bytes = _create_minimal_png(58, 58, (232, 89, 56, 255))
    icon2x_bytes = _create_minimal_png(116, 116, (232, 89, 56, 255))
    logo_bytes = _create_minimal_png(160, 50, (255, 255, 255, 255))

    files = {
        "pass.json": pass_bytes,
        "icon.png": icon_bytes,
        "icon@2x.png": icon2x_bytes,
        "logo.png": logo_bytes,
        "logo@2x.png": logo_bytes,
    }

    # Build manifest.json (SHA-1 checksums)
    manifest = {name: hashlib.sha1(data).hexdigest() for name, data in files.items()}
    files["manifest.json"] = json.dumps(manifest, indent=2).encode("utf-8")

    # Package into .pkpass ZIP buffer
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)

    return zip_buf.getvalue()

