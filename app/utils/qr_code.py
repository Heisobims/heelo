from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFont
import qrcode
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_M
import structlog

logger = structlog.get_logger()

_STATIC_DIR = Path(__file__).parent.parent / "static"
_FONT_PATH = _STATIC_DIR / "fonts" / "Denton Test Bold 700.otf"


def _parse_hex_color(hex_str: str | None) -> tuple[int, int, int]:
    """Parse hex color string to RGB tuple, defaulting to signature orange #E85938."""
    default_rgb = (232, 89, 56)
    if not hex_str:
        return default_rgb
    clean = hex_str.strip().lstrip("#")
    if len(clean) == 3:
        clean = "".join([c * 2 for c in clean])
    if len(clean) == 6:
        try:
            return (int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16))
        except ValueError:
            pass
    return default_rgb


def _get_monogram_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load bold TrueType font for monogram or fall back to default."""
    font_size = max(10, int(size * 0.46))
    if _FONT_PATH.is_file():
        try:
            return ImageFont.truetype(str(_FONT_PATH), font_size)
        except Exception:
            pass
    return ImageFont.load_default()


async def fetch_logo_bytes(logo_url: str | None) -> bytes | None:
    """
    Fetch logo image bytes from local disk or remote URL.
    Returns bytes on success, None on failure.
    """
    if not logo_url or not str(logo_url).strip():
        return None

    clean = str(logo_url).strip()

    # 1. Local static or upload path
    if clean.startswith("/static/"):
        rel_path = clean.removeprefix("/static/").lstrip("/")
        local_path = _STATIC_DIR / rel_path
        if local_path.is_file():
            try:
                return local_path.read_bytes()
            except OSError as err:
                logger.warning("qr.local_logo_read_failed", path=str(local_path), error=str(err))
                return None

    # 2. Remote HTTP/HTTPS URL
    if clean.startswith(("http://", "https://")):
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(clean)
                if resp.status_code == 200:
                    return resp.content
        except Exception as err:
            logger.warning("qr.remote_logo_fetch_failed", url=clean, error=str(err))

    return None


def _load_local_logo_sync(logo_url_or_path: str | Path | None) -> bytes | None:
    """Synchronously load logo bytes from a local file path if available."""
    if not logo_url_or_path:
        return None
    p_str = str(logo_url_or_path).strip()
    if p_str.startswith("/static/"):
        rel = p_str.removeprefix("/static/").lstrip("/")
        target = _STATIC_DIR / rel
        if target.is_file():
            try:
                return target.read_bytes()
            except OSError:
                return None
    target_path = Path(p_str)
    if target_path.is_file():
        try:
            return target_path.read_bytes()
        except OSError:
            return None
    return None


def generate_qr_png(
    data: str,
    *,
    box_size: int = 8,
    border: int = 4,
    logo_bytes: bytes | None = None,
    logo_path: str | Path | None = None,
    logo_url: str | None = None,
    org_name: str | None = None,
    brand_color: str | None = None,
) -> bytes:
    """
    Generate a PNG QR code image from a string payload with an embedded organizer logo.

    When logo_bytes, logo_path, or logo_url is provided, the logo is scaled proportionally,
    placed inside a clean padded white badge plate with rounded corners, and centered
    in the QR code using ERROR_CORRECT_H (30% error recovery) to ensure flawless scannability.

    If a logo image is not yet uploaded but an organizer name is provided, an elegant
    monogram avatar badge in the organizer brand color is embedded in the center.
    """
    # Attempt local logo resolution if logo_bytes was not supplied
    if not logo_bytes:
        if logo_path:
            logo_bytes = _load_local_logo_sync(logo_path)
        elif logo_url:
            logo_bytes = _load_local_logo_sync(logo_url)

    has_branding = bool(logo_bytes or org_name)
    error_correction = ERROR_CORRECT_H if has_branding else ERROR_CORRECT_M

    qr = qrcode.QRCode(
        version=None,
        error_correction=error_correction,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")

    # If no branding info is available, return the high-resolution QR directly
    if not has_branding:
        buf = BytesIO()
        qr_img.save(buf, format="PNG")
        return buf.getvalue()

    qr_w, qr_h = qr_img.size

    # The badge plate occupies ~22% of QR dimensions (under 5% of total area)
    badge_size = max(42, int(min(qr_w, qr_h) * 0.22))
    inner_logo_size = max(32, badge_size - 8)  # 4px padding on each side

    logo_img: Image.Image | None = None
    if logo_bytes:
        try:
            logo_img = Image.open(BytesIO(logo_bytes)).convert("RGBA")
        except Exception as err:
            logger.warning("qr.decode_logo_bytes_failed", error=str(err))
            logo_img = None

    badge = Image.new("RGBA", (badge_size, badge_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)
    corner_radius = max(4, badge_size // 6)

    # Clean white rounded badge background with crisp 1px border
    border_color = (226, 232, 240, 255)
    draw.rounded_rectangle(
        [(0, 0), (badge_size - 1, badge_size - 1)],
        radius=corner_radius,
        fill=(255, 255, 255, 255),
        outline=border_color,
        width=1,
    )

    if logo_img:
        # Scale logo proportionally inside the inner bounds
        lw, lh = logo_img.size
        scale = min(inner_logo_size / max(1, lw), inner_logo_size / max(1, lh))
        new_w = max(1, int(lw * scale))
        new_h = max(1, int(lh * scale))
        resized_logo = logo_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        paste_x = (badge_size - new_w) // 2
        paste_y = (badge_size - new_h) // 2
        mask = resized_logo if resized_logo.mode == "RGBA" else None
        badge.paste(resized_logo, (paste_x, paste_y), mask)
    elif org_name:
        # Render a monogram badge with organizer initials and brand color
        rgb = _parse_hex_color(brand_color)
        words = [w for w in org_name.strip().split() if w]
        if len(words) >= 2:
            initials = f"{words[0][0]}{words[1][0]}".upper()
        elif words:
            initials = words[0][:2].upper()
        else:
            initials = "H"

        mono_radius = max(3, inner_logo_size // 6)
        x0 = (badge_size - inner_logo_size) // 2
        y0 = (badge_size - inner_logo_size) // 2
        x1 = x0 + inner_logo_size - 1
        y1 = y0 + inner_logo_size - 1

        draw.rounded_rectangle(
            [(x0, y0), (x1, y1)],
            radius=mono_radius,
            fill=(*rgb, 255),
        )

        font = _get_monogram_font(inner_logo_size)
        bbox = draw.textbbox((0, 0), initials, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = x0 + (inner_logo_size - tw) // 2 - bbox[0]
        ty = y0 + (inner_logo_size - th) // 2 - bbox[1]
        draw.text((tx, ty), initials, fill=(255, 255, 255, 255), font=font)

    # Paste the logo badge in the center of the QR code
    center_x = (qr_w - badge_size) // 2
    center_y = (qr_h - badge_size) // 2
    qr_img.paste(badge, (center_x, center_y), badge)

    buf = BytesIO()
    qr_img.save(buf, format="PNG")
    return buf.getvalue()
