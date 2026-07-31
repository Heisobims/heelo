from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api import ApiKey

_PREFIX = "hlo_live_"


def _raw_key() -> str:
    return _PREFIX + secrets.token_hex(32)  # hlo_live_ + 64 hex chars


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def create_api_key(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    created_by: uuid.UUID,
    name: str,
) -> tuple[str, ApiKey]:
    """Return (raw_key, ApiKey). raw_key is shown once and never stored."""
    raw = _raw_key()
    key = ApiKey(
        org_id=org_id,
        created_by=created_by,
        name=name,
        key_hash=_hash(raw),
        key_prefix=raw[:16],  # "hlo_live_" + first 7 chars
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return raw, key


async def list_api_keys(db: AsyncSession, org_id: uuid.UUID) -> list[ApiKey]:
    rows = await db.scalars(
        select(ApiKey).where(ApiKey.org_id == org_id).order_by(ApiKey.created_at.desc())
    )
    return list(rows.all())


async def revoke_api_key(db: AsyncSession, key: ApiKey) -> None:
    key.is_active = False
    await db.commit()


async def authenticate_api_key(db: AsyncSession, raw_key: str) -> ApiKey | None:
    if not raw_key or not raw_key.startswith(_PREFIX):
        return None
    h = _hash(raw_key)
    key = await db.scalar(select(ApiKey).where(ApiKey.key_hash == h, ApiKey.is_active.is_(True)))
    if not key:
        return None
    if key.expires_at and key.expires_at < datetime.now(UTC):
        return None
    # Lazy update last_used without blocking
    await db.execute(
        update(ApiKey).where(ApiKey.id == key.id).values(last_used_at=datetime.now(UTC))
    )
    await db.commit()
    return key
