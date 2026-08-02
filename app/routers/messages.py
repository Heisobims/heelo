from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.dependencies import CurrentUserID, DBSession
from app.services import message_service as msg_svc

router_messages = APIRouter(prefix="/api/v1/messages", tags=["messages"])


def _message_out(m) -> dict:
    return {
        "id": str(m.id),
        "sender_id": str(m.sender_id),
        "recipient_id": str(m.recipient_id),
        "body": m.body,
        "is_read": m.is_read,
        "created_at": m.created_at.isoformat(),
    }


class SendMessageRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)


@router_messages.get("")
async def list_threads(db: DBSession, current_user_id: CurrentUserID):
    from sqlalchemy import select

    from app.models.user import User

    threads = await msg_svc.list_threads(db, uuid.UUID(current_user_id))
    out = []
    for t in threads:
        other = await db.scalar(select(User).where(User.id == t["other_user_id"]))
        out.append(
            {
                "other_user_id": str(t["other_user_id"]),
                "other_user_name": other.full_name if other else "Unknown",
                "other_user_username": other.username if other else None,
                "other_user_avatar_url": other.avatar_url if other else None,
                "last_message": _message_out(t["last_message"]),
                "unread_count": t["unread_count"],
            }
        )
    return {"success": True, "data": out}


@router_messages.get("/{other_user_id}")
async def get_thread(other_user_id: uuid.UUID, db: DBSession, current_user_id: CurrentUserID):
    user_id = uuid.UUID(current_user_id)
    messages = await msg_svc.get_thread_messages(db, user_id, other_user_id)
    await msg_svc.mark_thread_read(db, user_id, other_user_id)
    return {"success": True, "data": [_message_out(m) for m in messages]}


@router_messages.post("/{other_user_id}", status_code=201)
async def send_message(
    other_user_id: uuid.UUID,
    data: SendMessageRequest,
    db: DBSession,
    current_user_id: CurrentUserID,
):
    msg = await msg_svc.send_message(db, uuid.UUID(current_user_id), other_user_id, data.body)
    return {"success": True, "data": _message_out(msg)}
