from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.organization import Organization
    from app.models.user import User


class AttendeeProfile(Base, TimestampMixin):
    """Public-facing profile for an attendee at heelo.io/p/<username>."""

    __tablename__ = "attendee_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    headline: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    twitter_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Text array of interest tags e.g. ["AI", "Startups", "FinTech"]
    interests: Mapped[list[str]] = mapped_column(ARRAY(String(100)), nullable=False, default=list)
    is_visible_in_directory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    events_attended_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user: Mapped[User] = relationship("User", back_populates="attendee_profile")

    def __repr__(self) -> str:
        return f"<AttendeeProfile user={self.user_id}>"


class Connection(Base, TimestampMixin):
    """Peer-to-peer connection between two attendees — typically formed at an event."""

    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint("user_id", "connected_user_id", name="uq_connection_pair"),
        Index("ix_connections_user", "user_id"),
        Index("ix_connections_connected_user", "connected_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    connected_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Event where they met
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )
    # pending | accepted | declined | blocked
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    requester: Mapped[User] = relationship("User", foreign_keys=[user_id])
    target: Mapped[User] = relationship("User", foreign_keys=[connected_user_id])
    event: Mapped[Event | None] = relationship("Event")

    def __repr__(self) -> str:
        return f"<Connection {self.user_id} → {self.connected_user_id} {self.status}>"


class OrganizerFollower(Base, TimestampMixin):
    """A user following an organization to receive new event notifications."""

    __tablename__ = "organizer_followers"
    __table_args__ = (
        UniqueConstraint("user_id", "org_id", name="uq_organizer_follower"),
        Index("ix_organizer_followers_org", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    notify_new_events: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped[User] = relationship("User")
    organization: Mapped[Organization] = relationship("Organization")


class EventInterest(Base, TimestampMixin):
    """
    Lightweight non-binary RSVP — 'I'm interested' short of buying a ticket.
    Nudges toward purchase via a single reminder before the event.
    """

    __tablename__ = "event_interests"
    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="uq_event_interest_user_event"),
        Index("ix_event_interests_event", "event_id"),
        Index("ix_event_interests_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )

    user: Mapped[User] = relationship("User")
    event: Mapped[Event] = relationship("Event")

    def __repr__(self) -> str:
        return f"<EventInterest user={self.user_id} event={self.event_id}>"


class WhatsAppMessage(Base, TimestampMixin):
    """
    Two-way WhatsApp inbox record.
    Inbound messages from attendees and outbound replies from organizers.
    """

    __tablename__ = "whatsapp_messages"
    __table_args__ = (
        Index("ix_whatsapp_messages_org_thread", "org_id", "from_number"),
        Index("ix_whatsapp_messages_wa_id", "wa_message_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # WhatsApp phone number (with country code, no +)
    from_number: Mapped[str] = mapped_column(String(30), nullable=False)
    to_number: Mapped[str] = mapped_column(String(30), nullable=False)
    # inbound | outbound
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # text | image | document | audio | reaction
    message_type: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    media_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Meta Cloud API message ID
    wa_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    # sent | delivered | read | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="sent")
    is_read_by_org: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # AI-generated suggested reply (for outbound drafts)
    ai_suggested_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    # User who sent (outbound) — null for inbound
    sent_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )

    organization: Mapped[Organization] = relationship("Organization")
