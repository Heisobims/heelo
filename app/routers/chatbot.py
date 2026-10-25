"""
Support AI Chatbot Router.
Provides public, conversational support and intelligent answers
grounded in the Heelo platform and database.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
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

    history_dicts = [{"role": h.role, "content": h.content} for h in body.history]
    result = await get_chatbot_reply(
        db=db,
        user_message=body.message,
        chat_history=history_dicts,
        client_context=body.client_context,
    )

    return ChatResponse(
        success=True,
        data=ChatResponseData(
            reply=result.get("reply", ""),
            suggestions=result.get("suggestions", []),
        ),
    )

