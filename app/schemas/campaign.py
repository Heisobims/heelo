from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CampaignCreateRequest(BaseModel):
    type: Literal["email", "whatsapp", "sms"]
    name: str = Field(..., min_length=1, max_length=255)
    subject: str | None = Field(None, max_length=500)
    body: str = Field(..., min_length=1)
    event_id: uuid.UUID | None = None
    audience_statuses: list[str] = ["confirmed", "checked_in"]


class CampaignUpdateRequest(BaseModel):
    name: str | None = Field(None, max_length=255)
    subject: str | None = Field(None, max_length=500)
    body: str | None = None
    event_id: uuid.UUID | None = None
    audience_statuses: list[str] | None = None


class CampaignSendRequest(BaseModel):
    scheduled_at: datetime | None = None  # None = send immediately


class AudienceCountRequest(BaseModel):
    event_id: uuid.UUID | None = None
    audience_statuses: list[str] = ["confirmed", "checked_in"]


class CampaignOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    event_id: uuid.UUID | None
    type: str
    name: str
    subject: str | None
    body: str | None
    status: str
    audience_filter: dict | None
    scheduled_at: datetime | None
    sent_at: datetime | None
    recipient_count: int
    sent_count: int
    delivered_count: int
    open_count: int
    click_count: int
    failed_count: int
    created_at: datetime

    model_config = {"from_attributes": True}
