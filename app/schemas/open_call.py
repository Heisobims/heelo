from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class OpenCallCreateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    slug: str | None = Field(default=None, max_length=255)
    call_type: str = Field(default="speaker", pattern="^(speaker|papers|sponsor|volunteer|custom)$")
    description: str | None = None
    guidelines: str | None = None
    perks: str | None = None
    status: str = Field(default="open", pattern="^(draft|open|closed|archived)$")
    start_date: datetime | None = None
    end_date: datetime | None = None
    custom_fields: list[dict[str, Any]] = Field(default_factory=list)
    auto_response_message: str | None = None
    max_submissions: int | None = Field(default=None, ge=1)
    allow_anonymous: bool = True


class OpenCallUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=255)
    slug: str | None = Field(default=None, max_length=255)
    call_type: str | None = Field(
        default=None, pattern="^(speaker|papers|sponsor|volunteer|custom)$"
    )
    description: str | None = None
    guidelines: str | None = None
    perks: str | None = None
    status: str | None = Field(default=None, pattern="^(draft|open|closed|archived)$")
    start_date: datetime | None = None
    end_date: datetime | None = None
    custom_fields: list[dict[str, Any]] | None = None
    auto_response_message: str | None = None
    max_submissions: int | None = Field(default=None, ge=1)
    allow_anonymous: bool | None = None


class OpenCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    event_id: uuid.UUID
    created_by: uuid.UUID | None
    title: str
    slug: str
    call_type: str
    description: str | None
    guidelines: str | None
    perks: str | None
    status: str
    start_date: datetime | None
    end_date: datetime | None
    custom_fields: list[dict[str, Any]]
    auto_response_message: str | None
    max_submissions: int | None
    allow_anonymous: bool
    submission_count: int
    created_at: datetime
    updated_at: datetime


class OpenCallPublicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    title: str
    slug: str
    call_type: str
    description: str | None
    guidelines: str | None
    perks: str | None
    status: str
    start_date: datetime | None
    end_date: datetime | None
    custom_fields: list[dict[str, Any]]
    allow_anonymous: bool
    is_open: bool = True


class OpenCallSubmissionCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=50)
    organization_name: str | None = Field(default=None, max_length=255)
    job_title: str | None = Field(default=None, max_length=255)
    bio: str | None = None
    photo_url: str | None = None
    social_links: dict[str, str] = Field(default_factory=dict)
    title: str = Field(..., min_length=2, max_length=500)
    proposal_summary: str = Field(..., min_length=10)
    details: str | None = None
    category_or_track: str | None = Field(default=None, max_length=100)
    attachment_url: str | None = None
    custom_answers: dict[str, Any] = Field(default_factory=dict)


class OpenCallSubmissionReviewRequest(BaseModel):
    status: str = Field(
        ..., pattern="^(submitted|under_review|shortlisted|accepted|rejected|withdrawn)$"
    )
    rating: int | None = Field(default=None, ge=1, le=5)
    organizer_notes: str | None = None
    feedback_to_applicant: str | None = None


class OpenCallSubmissionPromoteRequest(BaseModel):
    role_type: str = Field(
        default="speaker", pattern="^(speaker|keynote|panelist|moderator|workshop_lead)$"
    )
    tier: str = Field(default="partner", pattern="^(platinum|gold|silver|bronze|partner|media)$")


class OpenCallSubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    call_id: uuid.UUID
    event_id: uuid.UUID
    org_id: uuid.UUID
    user_id: uuid.UUID | None
    name: str
    email: str
    phone: str | None
    organization_name: str | None
    job_title: str | None
    bio: str | None
    photo_url: str | None
    social_links: dict[str, Any]
    title: str
    proposal_summary: str
    details: str | None
    category_or_track: str | None
    attachment_url: str | None
    custom_answers: dict[str, Any]
    status: str
    rating: int | None
    organizer_notes: str | None
    feedback_to_applicant: str | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    promoted_to_speaker_id: uuid.UUID | None
    promoted_to_sponsor_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class OpenCallSubmissionPublicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    call_id: uuid.UUID
    title: str
    name: str
    status: str
    created_at: datetime
    feedback_to_applicant: str | None = None
