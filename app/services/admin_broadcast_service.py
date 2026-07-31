"""Platform-wide promotional/announcement emails, sent by a platform admin."""

from __future__ import annotations

import re
import uuid

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import AdminBroadcast
from app.models.user import User

# Personal Gmail accounts cap outbound mail at ~500/day (Workspace: ~2000/day).
# Not enforced here — just surfaced to the admin so they don't get surprised
# by a suspended account mid-send.
GMAIL_DAILY_SOFT_LIMIT = 500


def render_personalized(body: str, user: User) -> str:
    """Merge-tag substitution — deliberately minimal: only fields the admin
    already sees in the Users list, nothing that requires extra context."""
    rendered = body.replace("{{name}}", user.full_name or "there")
    rendered = rendered.replace("{{email}}", user.email)
    return rendered


async def get_audience(db: AsyncSession, category: str) -> list[User]:
    """All users matching a category — no pagination, this is for sending, not display."""
    from app.services.admin_service import apply_category_filter

    q = select(User).where(User.deleted_at.is_(None))
    q = apply_category_filter(q, category)
    rows = await db.scalars(q)
    return list(rows.all())


async def create_broadcast(
    db: AsyncSession,
    *,
    created_by: uuid.UUID,
    subject: str,
    body: str,
    audience_category: str,
    channel: str = "email",
) -> AdminBroadcast:
    if channel not in ("email", "notification", "both"):
        raise ValueError(f"Invalid channel: {channel}")
    audience = await get_audience(db, audience_category)
    broadcast = AdminBroadcast(
        id=uuid.uuid4(),
        created_by=created_by,
        subject=subject,
        body=body,
        audience_category=audience_category,
        channel=channel,
        recipient_count=len(audience),
        status="draft",
    )
    db.add(broadcast)
    await db.commit()
    await db.refresh(broadcast)
    return broadcast


async def list_broadcasts(
    db: AsyncSession, *, page: int = 1, per_page: int = 20
) -> tuple[list[AdminBroadcast], int]:
    from sqlalchemy import func

    total = await db.scalar(select(func.count()).select_from(AdminBroadcast))
    rows = await db.scalars(
        select(AdminBroadcast)
        .order_by(desc(AdminBroadcast.created_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return list(rows.all()), total or 0


_TAG_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_ALLOWED_TAGS = {"name", "email"}


def validate_merge_tags(body: str) -> list[str]:
    """Return any {{tag}} references used that aren't supported."""
    used = set(_TAG_RE.findall(body))
    return sorted(used - _ALLOWED_TAGS)
