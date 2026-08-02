from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

Tier = Literal["platinum", "gold", "silver", "bronze", "partner", "media"]


class SponsorCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    logo_url: str | None = None
    website: str | None = Field(None, max_length=500)
    description: str | None = None
    tier: Tier = "partner"
    sort_order: int = 0
    is_exhibitor: bool = False
    booth_number: str | None = Field(None, max_length=50)
    category: str | None = Field(None, max_length=100)
    contact_email: EmailStr | None = None


class SponsorUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    logo_url: str | None = None
    website: str | None = Field(None, max_length=500)
    description: str | None = None
    tier: Tier | None = None
    sort_order: int | None = None
    is_exhibitor: bool | None = None
    booth_number: str | None = Field(None, max_length=50)
    category: str | None = Field(None, max_length=100)
    contact_email: EmailStr | None = None


class SponsorPortalUpdateRequest(BaseModel):
    """Self-service fields a claimed sponsor may edit themselves — tier,
    booth number, category, and exhibitor status stay organizer-controlled."""

    logo_url: str | None = None
    website: str | None = Field(None, max_length=500)
    description: str | None = None


class SponsorOut(BaseModel):
    id: uuid.UUID
    name: str
    logo_url: str | None
    website: str | None
    description: str | None
    tier: str
    sort_order: int
    is_exhibitor: bool
    booth_number: str | None
    category: str | None
    contact_email: str | None
    user_id: uuid.UUID | None
    invite_accepted: bool

    model_config = {"from_attributes": True}
