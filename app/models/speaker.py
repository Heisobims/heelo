from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.organization import Organization


class Speaker(Base, TimestampMixin):
    """Speaker profile — reusable across events within an org."""

    __tablename__ = "speakers"
    __table_args__ = (Index("ix_speakers_org", "org_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # If the speaker has a Heelo account this links them for profile access
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Public profile URL slug (GET /speakers/{slug}) — globally unique
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # {"twitter": "url", "linkedin": "url", "website": "url"}
    social_links: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Invite flow — speaker_invite_token allows speaker to fill their own profile
    invite_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invite_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invite_accepted: Mapped[bool] = mapped_column(nullable=False, default=False)

    organization: Mapped[Organization] = relationship("Organization", back_populates="speakers")
    event_speakers: Mapped[list[EventSpeaker]] = relationship(
        "EventSpeaker", back_populates="speaker", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Speaker {self.name}>"


class EventSpeaker(Base, TimestampMixin):
    """Links a reusable org-level Speaker to a specific event, with the role
    they play at that event and their display order in the event's People
    section. A Speaker row can be linked to many events (that's the point of
    keeping Speaker org-scoped instead of event-scoped)."""

    __tablename__ = "event_speakers"
    __table_args__ = (
        Index("ix_event_speakers_event_sort", "event_id", "sort_order"),
        Index("ix_event_speakers_speaker", "speaker_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    speaker_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("speakers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # speaker | panelist | moderator | judge | organizer
    role_type: Mapped[str] = mapped_column(String(20), nullable=False, default="speaker")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    event: Mapped[Event] = relationship("Event", back_populates="event_speakers")
    speaker: Mapped[Speaker] = relationship("Speaker", back_populates="event_speakers")

    def __repr__(self) -> str:
        return (
            f"<EventSpeaker event={self.event_id} speaker={self.speaker_id} "
            f"role={self.role_type}>"
        )


class Sponsor(Base, TimestampMixin):
    """Sponsor entry on a specific event."""

    __tablename__ = "sponsors"
    __table_args__ = (Index("ix_sponsors_event", "event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # platinum | gold | silver | bronze | partner | media
    tier: Mapped[str] = mapped_column(String(20), nullable=False, default="partner")
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)

    # Trade-show-style exhibitor fields — reuses Sponsor rather than a
    # separate table, since an exhibitor is just a sponsor entry with a
    # booth instead of (or in addition to) a sponsorship tier.
    is_exhibitor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    booth_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Self-service sponsor portal — the org creates the Sponsor row, then
    # invites a real Heelo account to claim and manage it (logo/website/
    # description only; tier/booth/category stay organizer-controlled).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invite_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    event: Mapped[Event] = relationship("Event", back_populates="sponsors")

    def __repr__(self) -> str:
        return f"<Sponsor {self.name} tier={self.tier}>"
