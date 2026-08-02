from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SessionType = Literal["talk", "panel", "workshop", "networking", "break", "ceremony"]


class SessionCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    session_type: SessionType = "talk"
    speaker_ids: list[uuid.UUID] = Field(default_factory=list)
    start_datetime: datetime
    end_datetime: datetime
    location_or_stream_url: str | None = None
    track: str | None = Field(None, max_length=100)
    sort_order: int = 0


class SessionUpdateRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    session_type: SessionType | None = None
    speaker_ids: list[uuid.UUID] | None = None
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    location_or_stream_url: str | None = None
    track: str | None = Field(None, max_length=100)
    sort_order: int | None = None


class SessionReorderRequest(BaseModel):
    session_ids: list[uuid.UUID] = Field(..., min_length=1)


class SessionOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    session_type: str
    speaker_ids: list[uuid.UUID]
    start_datetime: datetime
    end_datetime: datetime
    location_or_stream_url: str | None
    track: str | None
    sort_order: int

    model_config = {"from_attributes": True}
