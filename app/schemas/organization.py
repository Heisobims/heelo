from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class OrgCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    country: str | None = Field(None, pattern=r"^[A-Z]{2}$")
    currency: str = Field("NGN", pattern=r"^[A-Z]{3}$")

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip()


class OrgUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    description: str | None = None
    website: str | None = None
    country: str | None = Field(None, pattern=r"^[A-Z]{2}$")
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    logo_url: str | None = None
    cover_url: str | None = None
    contact_email: str | None = None
    instagram_url: str | None = None
    twitter_url: str | None = None
    facebook_url: str | None = None
    linkedin_url: str | None = None
    brand_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")


class OrgOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    logo_url: str | None = None
    cover_url: str | None = None
    description: str | None = None
    website: str | None = None
    country: str | None = None
    currency: str
    plan: str
    owner_id: uuid.UUID
    is_active: bool
    contact_email: str | None = None
    instagram_url: str | None = None
    twitter_url: str | None = None
    facebook_url: str | None = None
    linkedin_url: str | None = None
    brand_color: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OrgListItem(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    logo_url: str | None = None
    country: str | None = None
    currency: str
    plan: str
    role: str
    is_owner: bool

    model_config = {"from_attributes": True}


class InviteMemberRequest(BaseModel):
    email: str
    role: Literal["admin", "organizer", "finance", "checkin_staff"] = "organizer"


class OrgMemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    org_id: uuid.UUID
    role: str
    status: str
    invited_at: datetime
    accepted_at: datetime | None = None
    invited_email: str | None = None
    user_name: str | None = None
    user_email: str | None = None
    user_avatar: str | None = None

    model_config = {"from_attributes": True}


class UpdateMemberRoleRequest(BaseModel):
    role: Literal["admin", "organizer", "finance", "checkin_staff"]


class OnboardingState(BaseModel):
    has_event: bool = False
    has_payment_account: bool = False
    has_team_member: bool = False
    has_whatsapp: bool = False

    @property
    def is_complete(self) -> bool:
        return self.has_event and self.has_payment_account

    @property
    def completed_count(self) -> int:
        return sum(
            [self.has_event, self.has_payment_account, self.has_team_member, self.has_whatsapp]
        )

    @property
    def total(self) -> int:
        return 4
