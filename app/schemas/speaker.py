from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator

RoleType = Literal["speaker", "panelist", "moderator", "judge", "organizer"]


class SpeakerCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    title: str | None = Field(None, max_length=255)
    company: str | None = Field(None, max_length=255)
    bio: str | None = None
    photo_url: str | None = None
    social_links: dict = Field(default_factory=dict)


class SpeakerUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    title: str | None = Field(None, max_length=255)
    company: str | None = Field(None, max_length=255)
    bio: str | None = None
    photo_url: str | None = None
    social_links: dict | None = None


class SpeakerOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    title: str | None
    company: str | None
    bio: str | None
    photo_url: str | None
    social_links: dict

    model_config = {"from_attributes": True}


class EventSpeakerLinkRequest(BaseModel):
    """Add a person to an event's People roster - either by linking an
    existing org speaker (`speaker_id`) or by creating a new one inline
    (`name` + optional profile fields), matching how the event form's
    "add person" UI works (no separate reuse-existing-speaker picker yet)."""

    speaker_id: uuid.UUID | None = None
    name: str | None = Field(None, min_length=1, max_length=255)
    title: str | None = Field(None, max_length=255)
    company: str | None = Field(None, max_length=255)
    bio: str | None = None
    photo_url: str | None = None
    social_links: dict = Field(default_factory=dict)
    role_type: RoleType = "speaker"
    sort_order: int = 0

    @model_validator(mode="after")
    def require_speaker_id_or_name(self):
        if not self.speaker_id and not (self.name and self.name.strip()):
            raise ValueError("Provide either speaker_id or name.")
        return self


class EventSpeakerUpdateRequest(BaseModel):
    role_type: RoleType | None = None
    sort_order: int | None = None
    name: str | None = Field(None, min_length=1, max_length=255)
    title: str | None = Field(None, max_length=255)
    company: str | None = Field(None, max_length=255)
    bio: str | None = None
    photo_url: str | None = None
    social_links: dict | None = None


class EventSpeakerOut(BaseModel):
    id: uuid.UUID
    speaker_id: uuid.UUID
    speaker_slug: str
    role_type: str
    sort_order: int
    name: str
    title: str | None
    company: str | None
    bio: str | None
    photo_url: str | None
    social_links: dict
