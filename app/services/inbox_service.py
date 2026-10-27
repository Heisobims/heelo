"""
WhatsApp inbox service - thread listing, message history, reply sending.
All functions are async (FastAPI). Sync helpers live in tasks/whatsapp.py.
"""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.community import WhatsAppMessage


async def list_threads(db: AsyncSession, org_id: uuid.UUID) -> list[dict]:
    """
    Return one entry per unique phone number - last message body/time + unread count.
    Ordered by most recent message first.
    """
    # Subquery: last message time per phone
    sub = (
        select(
            WhatsAppMessage.from_number,
            func.max(WhatsAppMessage.created_at).label("last_at"),
        )
        .where(WhatsAppMessage.org_id == org_id)
        .group_by(WhatsAppMessage.from_number)
        .subquery()
    )

    # Unread count per phone (inbound only, not yet read)
    unread_sub = (
        select(
            WhatsAppMessage.from_number,
            func.count().label("unread"),
        )
        .where(
            WhatsAppMessage.org_id == org_id,
            WhatsAppMessage.direction == "inbound",
            WhatsAppMessage.is_read_by_org.is_(False),
        )
        .group_by(WhatsAppMessage.from_number)
        .subquery()
    )

    # Latest message per thread (for preview)
    rows = await db.execute(
        select(
            WhatsAppMessage,
            unread_sub.c.unread,
        )
        .join(
            sub,
            (WhatsAppMessage.from_number == sub.c.from_number)
            & (WhatsAppMessage.created_at == sub.c.last_at)
            & (WhatsAppMessage.org_id == org_id),
        )
        .outerjoin(unread_sub, WhatsAppMessage.from_number == unread_sub.c.from_number)
        .order_by(desc(sub.c.last_at))
    )

    threads = []
    seen: set[str] = set()
    for row in rows.all():
        msg: WhatsAppMessage = row[0]
        if msg.from_number in seen:
            continue
        seen.add(msg.from_number)
        threads.append(
            {
                "phone": msg.from_number,
                "last_body": (msg.body or "")[:80],
                "last_at": msg.created_at,
                "direction": msg.direction,
                "unread": row[1] or 0,
            }
        )
    return threads


async def get_thread_messages(
    db: AsyncSession, org_id: uuid.UUID, phone: str, limit: int = 100
) -> list[WhatsAppMessage]:
    rows = await db.scalars(
        select(WhatsAppMessage)
        .where(WhatsAppMessage.org_id == org_id, WhatsAppMessage.from_number == phone)
        .order_by(WhatsAppMessage.created_at.asc())
        .limit(limit)
    )
    return list(rows.all())


async def mark_thread_read(db: AsyncSession, org_id: uuid.UUID, phone: str) -> None:
    await db.execute(
        update(WhatsAppMessage)
        .where(
            WhatsAppMessage.org_id == org_id,
            WhatsAppMessage.from_number == phone,
            WhatsAppMessage.direction == "inbound",
            WhatsAppMessage.is_read_by_org.is_(False),
        )
        .values(is_read_by_org=True)
    )
    await db.commit()


async def send_reply(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    sent_by: uuid.UUID,
    phone: str,
    body: str,
) -> WhatsAppMessage:
    # Send via Meta Cloud API
    if settings.WHATSAPP_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID:
        url = f"https://graph.facebook.com/v18.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        headers = {
            "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(url, json=payload, headers=headers)
            wa_status = "sent"
        except Exception:
            wa_status = "failed"
    else:
        wa_status = "sent"  # dev mode

    msg = WhatsAppMessage(
        org_id=org_id,
        from_number=settings.WHATSAPP_PHONE_NUMBER_ID or "tixdoo",
        to_number=phone,
        direction="outbound",
        body=body,
        message_type="text",
        status=wa_status,
        is_read_by_org=True,
        sent_by=sent_by,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def store_inbound(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    from_phone: str,
    body: str,
    wa_message_id: str | None = None,
    ai_suggested_reply: str | None = None,
) -> WhatsAppMessage:
    msg = WhatsAppMessage(
        org_id=org_id,
        from_number=from_phone,
        to_number=settings.WHATSAPP_PHONE_NUMBER_ID or "tixdoo",
        direction="inbound",
        body=body,
        message_type="text",
        status="delivered",
        is_read_by_org=False,
        wa_message_id=wa_message_id,
        ai_suggested_reply=ai_suggested_reply,
    )
    db.add(msg)
    await db.commit()
    return msg


async def get_follower_count(db: AsyncSession, org_id: uuid.UUID) -> int:
    from app.models.community import OrganizerFollower

    count = await db.scalar(select(func.count()).where(OrganizerFollower.org_id == org_id))
    return count or 0


async def toggle_follow(db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Returns True if now following, False if unfollowed."""
    from sqlalchemy import delete

    from app.models.community import OrganizerFollower

    existing = await db.scalar(
        select(OrganizerFollower).where(
            OrganizerFollower.org_id == org_id,
            OrganizerFollower.user_id == user_id,
        )
    )
    if existing:
        await db.execute(
            delete(OrganizerFollower).where(
                OrganizerFollower.org_id == org_id,
                OrganizerFollower.user_id == user_id,
            )
        )
        await db.commit()
        return False
    else:
        db.add(OrganizerFollower(org_id=org_id, user_id=user_id))
        await db.commit()
        return True


async def is_following(db: AsyncSession, *, org_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    from app.models.community import OrganizerFollower

    row = await db.scalar(
        select(OrganizerFollower).where(
            OrganizerFollower.org_id == org_id,
            OrganizerFollower.user_id == user_id,
        )
    )
    return row is not None
