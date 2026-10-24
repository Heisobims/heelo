"""
Viral attendee story card generator using Pillow.
Produces 1080x1920 high-res PNG graphics for Instagram Stories,
WhatsApp Status, LinkedIn, and Twitter/X.
"""

from __future__ import annotations

import io
import textwrap

from PIL import Image, ImageDraw, ImageFont

from app.utils.og_image import _load_font


def generate_attendee_share_card(
    attendee_name: str,
    event_title: str,
    *,
    date_str: str | None = None,
    location_str: str | None = None,
    ticket_type: str | None = None,
    org_name: str | None = None,
    brand_color_hex: str | None = None,
) -> bytes:
    """Generate a 1080x1920 story graphic for attendee social sharing."""
    width, height = 1080, 1920
    im = Image.new("RGBA", (width, height), (15, 15, 18, 255))
    draw = ImageDraw.Draw(im)

    # Accent color (default: Heelo coral orange #E85938)
    accent_rgb = (232, 89, 56)
    if brand_color_hex and brand_color_hex.startswith("#") and len(brand_color_hex) == 7:
        try:
            accent_rgb = tuple(int(brand_color_hex[i : i + 2], 16) for i in (1, 3, 5))
        except Exception:
            pass

    # Background gradient glow
    for y in range(height):
        ratio = y / height
        r = int(14 + (accent_rgb[0] - 14) * 0.08 * ratio)
        g = int(14 + (accent_rgb[1] - 14) * 0.08 * ratio)
        b = int(18 + (accent_rgb[2] - 18) * 0.08 * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    # Top Pill Header: "I'M ATTENDING"
    font_badge = _load_font(36, bold=True)
    pill_text = "I'M ATTENDING"
    draw.rounded_rectangle(
        [(100, 140), (460, 220)],
        radius=40,
        fill=accent_rgb,
    )
    draw.text((150, 158), pill_text, fill=(255, 255, 255, 255), font=font_badge)

    # Org / Platform header
    font_sub = _load_font(32, bold=False)
    header_text = f"Presented by {org_name}" if org_name else "heelo.io"
    draw.text((100, 260), header_text, fill=(180, 180, 190, 255), font=font_sub)

    # Attendee Name Box
    font_name = _load_font(72, bold=True)
    draw.text((100, 420), attendee_name, fill=(255, 255, 255, 255), font=font_name)

    font_pass = _load_font(36, bold=False)
    pass_label = f"Confirmed Attendee · {ticket_type or 'General Admission'}"
    draw.text((100, 520), pass_label, fill=(220, 220, 230, 255), font=font_pass)

    # Decorative separator line
    draw.line([(100, 600), (980, 600)], fill=(50, 50, 60, 255), width=3)

    # Event Title
    font_title = _load_font(68, bold=True)
    wrapped_title = "\n".join(textwrap.wrap(event_title, width=24, max_lines=4, placeholder="…"))
    draw.multiline_text(
        (100, 670),
        wrapped_title,
        fill=(255, 255, 255, 255),
        font=font_title,
        spacing=20,
    )

    # Event Details Card (Date & Venue)
    draw.rounded_rectangle(
        [(100, 1200), (980, 1500)],
        radius=28,
        fill=(28, 28, 35, 255),
        outline=(50, 50, 65, 255),
        width=2,
    )

    font_card_head = _load_font(32, bold=True)
    font_card_val = _load_font(42, bold=True)

    if date_str:
        draw.text((150, 1240), "DATE & TIME", fill=(160, 160, 175, 255), font=font_card_head)
        draw.text((150, 1285), date_str[:40], fill=(255, 255, 255, 255), font=font_card_val)

    if location_str:
        draw.text((150, 1370), "LOCATION", fill=(160, 160, 175, 255), font=font_card_head)
        draw.text((150, 1415), location_str[:40], fill=(255, 255, 255, 255), font=font_card_val)

    # Footer CTA
    font_footer = _load_font(36, bold=True)
    draw.text(
        (100, 1720),
        "Get tickets & join me on Heelo",
        fill=(255, 255, 255, 255),
        font=font_footer,
    )
    draw.text(
        (100, 1775),
        "heelo.io",
        fill=accent_rgb,
        font=font_sub,
    )

    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

