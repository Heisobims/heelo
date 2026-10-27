"""
OG image generation using Pillow.
Produces 1200×630 PNG images branded for Tixdoo events.
"""

from __future__ import annotations

import os
import textwrap
from io import BytesIO

import structlog
from PIL import Image, ImageDraw, ImageFont

logger = structlog.get_logger()

# ── Font resolution ───────────────────────────────────────────────────────────
_FONT_CANDIDATES = [
    # Windows
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    # Linux (Docker)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
]

_FONT_CANDIDATES_REGULAR = [
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
]


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = _FONT_CANDIDATES if bold else _FONT_CANDIDATES_REGULAR
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception as err:
                logger.warning("og_image.font_load_failed", path=path, error=str(err))
                continue
    logger.warning("og_image.no_font_found", bold=bold, size=size)
    return ImageFont.load_default()


# ── Brand colours ─────────────────────────────────────────────────────────────
_BLACK = (10, 10, 10)
_WHITE = (255, 255, 255)
_CYAN = (232, 89, 56)
_GRAY = (173, 173, 173)
_DIM_GRAY = (80, 80, 80)

W, H = 1200, 630


def _wrap_text(text: str, max_chars: int) -> str:
    return "\n".join(textwrap.wrap(text, width=max_chars, max_lines=3, placeholder="…"))


def generate_event_og_image(
    title: str,
    *,
    date_str: str | None = None,
    location_str: str | None = None,
    org_name: str | None = None,
    cover_image_bytes: bytes | None = None,
    format_label: str | None = None,
) -> bytes:
    """
    Generate a 1200×630 OG/social image for an event.

    Returns raw PNG bytes suitable for uploading to R2 or serving directly.
    """
    img = Image.new("RGB", (W, H), color=_BLACK)
    draw = ImageDraw.Draw(img)

    # ── Background: cover image with dark overlay ─────────────────────────────
    if cover_image_bytes:
        try:
            bg = Image.open(BytesIO(cover_image_bytes)).convert("RGB")
            bg = bg.resize((W, H), Image.LANCZOS)
            # Darken the cover image significantly
            overlay = Image.new("RGB", (W, H), _BLACK)
            img = Image.blend(bg, overlay, alpha=0.60)
            draw = ImageDraw.Draw(img)
        except Exception as err:
            logger.warning("og_image.cover_image_decode_failed", title=title, error=str(err))
            # fall back to plain black background

    # ── Cyan accent bar (top) ─────────────────────────────────────────────────
    draw.rectangle([(0, 0), (W, 5)], fill=_CYAN)

    # ── Left content column ───────────────────────────────────────────────────
    padding_x = 80

    # Format badge (if provided)
    badge_y = 64
    if format_label:
        badge_font = _load_font(13)
        badge_text = format_label.upper().replace("_", " ")
        draw.text((padding_x, badge_y), badge_text, font=badge_font, fill=_CYAN)
        badge_y += 28

    # Title (large, white, bold)
    title_font = _load_font(60, bold=True)
    wrapped_title = _wrap_text(title, max_chars=32)
    title_y = 100 if not format_label else badge_y + 12

    # Multi-line title with leading
    lines = wrapped_title.split("\n")
    line_h = 72
    for line in lines:
        draw.text((padding_x, title_y), line, font=title_font, fill=_WHITE)
        title_y += line_h

    # ── Meta row (date + location) ─────────────────────────────────────────────
    meta_y = H - 160
    meta_font = _load_font(24)
    meta_items = []
    if date_str:
        meta_items.append(date_str)
    if location_str:
        meta_items.append(location_str)

    if meta_items:
        draw.text((padding_x, meta_y), "  ·  ".join(meta_items), font=meta_font, fill=_GRAY)

    # ── Bottom bar: org name + tixdoo brand ────────────────────────────────────
    bottom_y = H - 80
    brand_font = _load_font(22, bold=True)
    small_font = _load_font(18)

    if org_name:
        draw.text((padding_x, bottom_y), org_name, font=small_font, fill=_DIM_GRAY)

    # "tixdoo" watermark bottom right
    tixdoo_text = "tixdoo"
    bbox = draw.textbbox((0, 0), tixdoo_text, font=brand_font)
    text_w = bbox[2] - bbox[0]
    draw.text((W - padding_x - text_w, bottom_y), tixdoo_text, font=brand_font, fill=_CYAN)

    # ── Divider line above bottom bar ─────────────────────────────────────────
    draw.rectangle([(padding_x, bottom_y - 16), (W - padding_x, bottom_y - 15)], fill=_DIM_GRAY)

    # ── Output ────────────────────────────────────────────────────────────────
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
