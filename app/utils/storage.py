"""
Cloudflare R2 / S3-compatible storage helpers.
Falls back to local disk (app/static/uploads/) when R2 is not configured.
"""

from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path

import aioboto3
import structlog
from PIL import Image

from app.config import settings

logger = structlog.get_logger()

_session = aioboto3.Session()

_LOCAL_UPLOAD_DIR = Path(__file__).parent.parent / "static" / "uploads"


def _r2_client():
    return _session.client(
        "s3",
        endpoint_url=f"https://{settings.CLOUDFLARE_R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.CLOUDFLARE_R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.CLOUDFLARE_R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


async def upload_bytes(
    data: bytes,
    key: str,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload raw bytes to R2. Falls back to local disk when R2 is not configured."""
    if not settings.CLOUDFLARE_R2_ACCESS_KEY_ID:
        dest = _LOCAL_UPLOAD_DIR / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        logger.info("storage.local_fallback", key=key, bytes=len(data))
        return f"/static/uploads/{key}"

    async with _r2_client() as s3:
        await s3.put_object(
            Bucket=settings.CLOUDFLARE_R2_BUCKET,
            Key=key,
            Body=data,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )

    url = f"{settings.CLOUDFLARE_R2_PUBLIC_URL}/{key}"
    logger.info("storage.uploaded", key=key, bytes=len(data))
    return url


async def upload_image(
    image_bytes: bytes,
    folder: str,
    filename: str | None = None,
    max_width: int = 1920,
    quality: int = 88,
) -> str:
    """
    Resize image to max_width (preserving aspect ratio), convert to JPEG,
    upload to R2, and return the public URL.
    """
    img = Image.open(BytesIO(image_bytes)).convert("RGB")

    if img.width > max_width:
        ratio = max_width / img.width
        new_h = int(img.height * ratio)
        img = img.resize((max_width, new_h), Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    jpeg_bytes = buf.getvalue()

    safe_name = filename or f"{uuid.uuid4().hex}.jpg"
    key = f"{folder}/{safe_name}"
    return await upload_bytes(jpeg_bytes, key, "image/jpeg")


async def upload_png(data: bytes, folder: str, filename: str | None = None) -> str:
    """Upload a PNG (e.g. OG image) to R2."""
    safe_name = filename or f"{uuid.uuid4().hex}.png"
    key = f"{folder}/{safe_name}"
    return await upload_bytes(data, key, "image/png")


async def delete_object(key: str) -> None:
    """Delete an object from R2 by key. Silently no-ops if R2 is not configured."""
    if not settings.CLOUDFLARE_R2_ACCESS_KEY_ID:
        return
    async with _r2_client() as s3:
        await s3.delete_object(Bucket=settings.CLOUDFLARE_R2_BUCKET, Key=key)
    logger.info("storage.deleted", key=key)
