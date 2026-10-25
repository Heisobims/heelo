"""
Support AI Chatbot Router.
Provides public, conversational support and intelligent answers
grounded in the Heelo platform and database.
"""

from __future__ import annotations

from typing import Annotated, Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.services import organization_service as org_svc
from app.services import vendor_service as vendor_svc
from app.services.chatbot_service import get_chatbot_reply
from app.utils.rate_limit import check_and_record, get_client_ip

router = APIRouter(prefix="/api/v1/support", tags=["support"])
DBSession = Annotated[AsyncSession, Depends(get_db)]


class ChatHistoryItem(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    history: list[ChatHistoryItem] = Field(default_factory=list)
    client_context: dict[str, Any] = Field(default_factory=dict)


class ChatResponseData(BaseModel):
    reply: str
    suggestions: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    success: bool = True
    data: ChatResponseData


async def resolve_chat_auth_context(request: Request, db: AsyncSession) -> dict[str, Any]:
    """
    Safely resolve optional authenticated user and organization memberships
    from cookie or Authorization bearer header.
    """
    token = request.cookies.get("heelo_access")
    if not token:
        auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if not token:
        return {"user": None, "user_orgs": [], "vendor": None, "org_ids": []}

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id_raw = payload.get("sub")
        if not user_id_raw:
            return {"user": None, "user_orgs": [], "vendor": None, "org_ids": []}
        user_id = uuid.UUID(user_id_raw)
    except (JWTError, ValueError):
        return {"user": None, "user_orgs": [], "vendor": None, "org_ids": []}

    user = await db.scalar(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    if not user:
        return {"user": None, "user_orgs": [], "vendor": None, "org_ids": []}

    user_orgs = await org_svc.get_user_organizations(db, user.id)
    org_ids = [o["org"].id for o in user_orgs if "org" in o]
    vendor = await vendor_svc.get_vendor_by_user(db, user.id)

    return {
        "user": user,
        "user_orgs": user_orgs,
        "vendor": vendor,
        "org_ids": org_ids,
    }


@router.post("/chat", response_model=ChatResponse)
async def support_chat(
    body: ChatRequest,
    request: Request,
    db: DBSession,
):
    """
    Public conversational support chat endpoint.
    Answers questions about events, ticketing, pricing, payouts, vendors, and platform features.
    """
    # Rate limit: 30 messages per minute per IP
    client_ip = get_client_ip(request)
    try:
        check_and_record(
            f"rate:support_chat:{client_ip}",
            max_attempts=30,
            window_seconds=60,
            error_message="You are sending messages too quickly. Please pause for a moment.",
        )
    except HTTPException:
        raise

    auth_context = await resolve_chat_auth_context(request, db)
    history_dicts = [{"role": h.role, "content": h.content} for h in body.history]
    result = await get_chatbot_reply(
        db=db,
        user_message=body.message,
        chat_history=history_dicts,
        client_context=body.client_context,
        auth_context=auth_context,
    )

    return ChatResponse(
        success=True,
        data=ChatResponseData(
            reply=result.get("reply", ""),
            suggestions=result.get("suggestions", []),
        ),
    )

