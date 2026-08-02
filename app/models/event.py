from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.organization import Organization
    from app.models.speaker import EventSpeaker, Sponsor
    from app.models.ticketing import PromoCode, Registration, TicketType, Waitlist
    from app.models.user import User


# ── Many-to-many: events ↔ categories ─────────────────────────────────────────
event_category_link = Table(
    "event_category_links",
    Base.metadata,
    Column(
        "event_id",
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "category_id",
        UUID(as_uuid=True),
        ForeignKey("event_categories.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class EventCategory(Base, TimestampMixin):
    """Global taxonomy for event discovery (e.g. Tech, Music, Business)."""

    __tablename__ = "event_categories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    events: Mapped[list[Event]] = relationship(
        "Event", secondary=event_category_link, back_populates="categories"
    )


class Event(Base, SoftDeleteMixin):
    """Core event entity — owned by an organization."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_org_status", "org_id", "status"),
        Index("ix_events_slug", "slug", unique=True),
        Index("ix_events_start_datetime", "start_datetime"),
        Index("ix_events_is_featured", "is_featured"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    gallery_1_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    gallery_2_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    og_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Flexible JSONB blob: agenda, people (speakers/panelists/etc), partners/sponsors
    extras: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)
    # Ordered [{"key": "about", "visible": true}, ...] controlling the public
    # event page's section order/visibility. Null = use DEFAULT_SECTION_ORDER.
    section_order: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)
    # Free-form organizer-typed vibe tags e.g. ["chill", "networking-heavy", "dress to impress"]
    vibe_tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), nullable=False, default=list)

    # draft | published | live | ended | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    # in_person | virtual | hybrid
    format: Mapped[str] = mapped_column(String(20), nullable=False, default="in_person")
    # Set when the organizer generates certificates — gates attendee downloads
    # until they explicitly decide the event is ready (e.g. after confirming
    # no late no-show corrections). Certificates are generated on-the-fly per
    # download, not stored; this is purely an availability gate.
    certificates_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    start_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # IANA timezone name e.g. "Africa/Lagos"
    timezone: Mapped[str] = mapped_column(String(100), nullable=False, default="UTC")

    # Venue (in_person / hybrid)
    venue_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    venue_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    venue_city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    venue_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    venue_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    venue_lng: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Virtual (virtual / hybrid)
    virtual_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    virtual_platform: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Public livestream URL (YouTube/Vimeo/HLS/generic embed) shown on the
    # event's live page — distinct from virtual_url, which is the private
    # join link only sent to confirmed registrants.
    livestream_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    max_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    password: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Recurring event support
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # daily | weekly | monthly | null
    recurrence_rule: Mapped[str | None] = mapped_column(String(100), nullable=True)
    recurrence_end_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    parent_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )

    # Cloned / templated from
    cloned_from_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )
    is_template: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Relationships ─────────────────────────────────────────────────────────
    organization: Mapped[Organization] = relationship("Organization", back_populates="events")
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by])
    sessions: Mapped[list[EventSession]] = relationship(
        "EventSession",
        back_populates="event",
        cascade="all, delete-orphan",
        order_by="EventSession.start_datetime",
    )
    ticket_types: Mapped[list[TicketType]] = relationship(
        "TicketType", back_populates="event", cascade="all, delete-orphan"
    )
    registrations: Mapped[list[Registration]] = relationship("Registration", back_populates="event")
    promo_codes: Mapped[list[PromoCode]] = relationship(
        "PromoCode", back_populates="event", cascade="all, delete-orphan"
    )
    waitlists: Mapped[list[Waitlist]] = relationship("Waitlist", back_populates="event")
    sponsors: Mapped[list[Sponsor]] = relationship(
        "Sponsor", back_populates="event", cascade="all, delete-orphan"
    )
    event_speakers: Mapped[list[EventSpeaker]] = relationship(
        "EventSpeaker",
        back_populates="event",
        cascade="all, delete-orphan",
        order_by="EventSpeaker.sort_order",
    )
    campaigns: Mapped[list[Campaign]] = relationship("Campaign", back_populates="event")
    categories: Mapped[list[EventCategory]] = relationship(
        "EventCategory", secondary=event_category_link, back_populates="events"
    )
    children: Mapped[list[Event]] = relationship(
        "Event", foreign_keys=[parent_event_id], back_populates="parent"
    )
    parent: Mapped[Event | None] = relationship(
        "Event", foreign_keys=[parent_event_id], back_populates="children", remote_side="Event.id"
    )
    comments: Mapped[list[EventComment]] = relationship(
        "EventComment", back_populates="event", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Event {self.slug} status={self.status}>"


class EventSession(Base, TimestampMixin):
    """A time-boxed block within an event (agenda item / breakout session)."""

    __tablename__ = "event_sessions"
    __table_args__ = (Index("ix_event_sessions_event_start", "event_id", "start_datetime"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # UUID array of speaker IDs for this session
    speaker_ids: Mapped[list[str]] = mapped_column(
        ARRAY(UUID(as_uuid=False)), nullable=False, default=list
    )
    # talk | panel | workshop | networking | break | ceremony
    session_type: Mapped[str] = mapped_column(String(30), nullable=False, default="talk")
    start_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Physical room or stream URL for this session
    location_or_stream_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Track (for multi-track events)
    track: Mapped[str | None] = mapped_column(String(100), nullable=True)

    event: Mapped[Event] = relationship("Event", back_populates="sessions")

    def __repr__(self) -> str:
        return f"<EventSession {self.title}>"


class EventComment(Base, TimestampMixin):
    """Public discussion comment on an event."""

    __tablename__ = "event_comments"
    __table_args__ = (Index("ix_event_comments_event", "event_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Null for anonymous / guest comments
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    author_name: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    event: Mapped[Event] = relationship("Event", back_populates="comments")

    def __repr__(self) -> str:
        return f"<EventComment event={self.event_id} by={self.author_name}>"
