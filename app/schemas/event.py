from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RecurrenceGenerateRequest(BaseModel):
    rule: Literal["daily", "weekly", "monthly"]
    end_date: datetime


class CategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    icon: str | None = None

    model_config = {"from_attributes": True}


SectionKey = Literal["about", "agenda", "people", "partners", "gallery", "discussion"]

DEFAULT_SECTION_ORDER: list[SectionKey] = [
    "about",
    "agenda",
    "people",
    "partners",
    "gallery",
    "discussion",
]


class SectionConfig(BaseModel):
    key: SectionKey
    visible: bool = True


class EventCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    format: Literal["in_person", "virtual", "hybrid"] = "in_person"
    start_datetime: datetime
    end_datetime: datetime
    timezone: str = Field("Africa/Lagos", max_length=100)
    # Venue
    venue_name: str | None = Field(None, max_length=500)
    venue_address: str | None = None
    venue_city: str | None = Field(None, max_length=255)
    venue_country: str | None = Field(None, max_length=2)
    venue_lat: float | None = None
    venue_lng: float | None = None
    # Virtual
    virtual_url: str | None = None
    virtual_platform: str | None = Field(None, max_length=50)
    # Settings
    max_capacity: int | None = Field(None, gt=0)
    is_private: bool = False
    password: str | None = None
    category_ids: list[uuid.UUID] = Field(default_factory=list)
    vibe_tags: list[str] = Field(default_factory=list, max_length=8)
    pass_fees_to_buyer: bool = True
    meta_pixel_id: str | None = Field(None, max_length=50)
    google_tag_id: str | None = Field(None, max_length=50)
    tiktok_pixel_id: str | None = Field(None, max_length=50)
    tax_rate: Decimal | None = None
    tax_id: str | None = Field(None, max_length=100)
    extras: dict | None = None

    @field_validator("vibe_tags")
    @classmethod
    def clean_vibe_tags(cls, v: list[str]) -> list[str]:
        cleaned = [t.strip().lower()[:50] for t in v if t.strip()]
        seen: list[str] = []
        for tag in cleaned:
            if tag not in seen:
                seen.append(tag)
        return seen

    @field_validator("title")
    @classmethod
    def strip_title(cls, v: str) -> str:
        return v.strip()

    @field_validator("end_datetime")
    @classmethod
    def end_after_start(cls, end: datetime, info) -> datetime:
        start = info.data.get("start_datetime")
        if start and end <= start:
            raise ValueError("end_datetime must be after start_datetime.")
        return end


class EventUpdateRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    description: str | None = None
    format: Literal["in_person", "virtual", "hybrid"] | None = None
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    timezone: str | None = Field(None, max_length=100)
    venue_name: str | None = None
    venue_address: str | None = None
    venue_city: str | None = None
    venue_country: str | None = None
    venue_lat: float | None = None
    venue_lng: float | None = None
    virtual_url: str | None = None
    virtual_platform: str | None = None
    max_capacity: int | None = Field(None, gt=0)
    is_private: bool | None = None
    password: str | None = None
    category_ids: list[uuid.UUID] | None = None
    vibe_tags: list[str] | None = Field(None, max_length=8)
    pass_fees_to_buyer: bool | None = None
    meta_pixel_id: str | None = Field(None, max_length=50)
    google_tag_id: str | None = Field(None, max_length=50)
    tiktok_pixel_id: str | None = Field(None, max_length=50)
    tax_rate: Decimal | None = None
    tax_id: str | None = Field(None, max_length=100)
    extras: dict | None = None
    is_template: bool | None = None
    section_order: list[SectionConfig] | None = None
    livestream_url: str | None = None

    @field_validator("vibe_tags")
    @classmethod
    def clean_vibe_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        cleaned = [t.strip().lower()[:50] for t in v if t.strip()]
        seen: list[str] = []
        for tag in cleaned:
            if tag not in seen:
                seen.append(tag)
        return seen


class EventOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    title: str
    slug: str
    description: str | None = None
    cover_image_url: str | None = None
    gallery_1_url: str | None = None
    gallery_2_url: str | None = None
    og_image_url: str | None = None
    status: str
    format: str
    start_datetime: datetime
    end_datetime: datetime
    timezone: str
    venue_name: str | None = None
    venue_address: str | None = None
    venue_city: str | None = None
    venue_country: str | None = None
    venue_lat: float | None = None
    venue_lng: float | None = None
    virtual_url: str | None = None
    virtual_platform: str | None = None
    max_capacity: int | None = None
    is_private: bool
    is_featured: bool
    is_template: bool
    pass_fees_to_buyer: bool = True
    meta_pixel_id: str | None = None
    google_tag_id: str | None = None
    tiktok_pixel_id: str | None = None
    tax_rate: Decimal | None = None
    tax_id: str | None = None
    created_at: datetime
    categories: list[CategoryOut] = Field(default_factory=list)
    vibe_tags: list[str] = Field(default_factory=list)
    extras: dict | None = None
    section_order: list[SectionConfig] | None = None
    livestream_url: str | None = None

    model_config = {"from_attributes": True}


class EventListItem(BaseModel):
    id: uuid.UUID
    title: str
    slug: str
    cover_image_url: str | None = None
    status: str
    format: str
    start_datetime: datetime
    end_datetime: datetime
    venue_city: str | None = None
    max_capacity: int | None = None
    is_private: bool
    created_at: datetime
    registration_count: int = 0
    total_revenue: Decimal = Decimal("0")

    model_config = {"from_attributes": True}


class PublicEventOut(BaseModel):
    """Stripped event schema for unauthenticated public access."""

    id: uuid.UUID
    title: str
    slug: str
    description: str | None = None
    cover_image_url: str | None = None
    og_image_url: str | None = None
    status: str
    format: str
    start_datetime: datetime
    end_datetime: datetime
    timezone: str
    venue_name: str | None = None
    venue_address: str | None = None
    venue_city: str | None = None
    venue_country: str | None = None
    venue_lat: float | None = None
    venue_lng: float | None = None
    virtual_platform: str | None = None
    max_capacity: int | None = None
    is_private: bool
    categories: list[CategoryOut] = Field(default_factory=list)
    vibe_tags: list[str] = Field(default_factory=list)
    registration_count: int = 0

    model_config = {"from_attributes": True}


class EventSearchQuery(BaseModel):
    q: str | None = None
    format: str | None = None
    city: str | None = None
    country: str | None = None
    category: str | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None
    page: int = Field(1, ge=1)
    per_page: int = Field(20, ge=1, le=50)
