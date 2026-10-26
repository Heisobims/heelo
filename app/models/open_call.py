from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.organization import Organization
    from app.models.speaker import Speaker, Sponsor
    from app.models.user import User


class OpenCall(Base, TimestampMixin):
    """An open call created by an organizer for an event (e.g. Call for Papers/Speakers,
    Call for Sponsors, Call for Volunteers, or custom community opportunities)."""

    __tablename__ = "open_calls"
    __table_args__ = (
        Index("ix_open_calls_event_status", "event_id", "status"),
        Index("ix_open_calls_org", "org_id"),
        Index("ix_open_calls_slug", "slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    # speaker | papers | sponsor | volunteer | custom
    call_type: Mapped[str] = mapped_column(String(50), nullable=False, default="speaker")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    guidelines: Mapped[str | None] = mapped_column(Text, nullable=True)
    perks: Mapped[str | None] = mapped_column(Text, nullable=True)
    # draft | open | closed | archived
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")

    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Custom questions builder:
    # [{"id": "...", "label": "...", "field_type": "...", "required": true, "options": [...]}]
    custom_fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    auto_response_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_submissions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    allow_anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    submission_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    event: Mapped[Event] = relationship("Event", back_populates="open_calls")
    organization: Mapped[Organization] = relationship("Organization")
    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by])
    submissions: Mapped[list[OpenCallSubmission]] = relationship(
        "OpenCallSubmission",
        back_populates="open_call",
        cascade="all, delete-orphan",
        order_by="desc(OpenCallSubmission.created_at)",
    )

    def __repr__(self) -> str:
        return f"<OpenCall {self.title} ({self.call_type}) status={self.status}>"


class OpenCallSubmission(Base, TimestampMixin):
    """An application or proposal submitted to an Open Call."""

    __tablename__ = "open_call_submissions"
    __table_args__ = (
        Index("ix_open_call_submissions_call_status", "call_id", "status"),
        Index("ix_open_call_submissions_event", "event_id"),
        Index("ix_open_call_submissions_org", "org_id"),
        Index("ix_open_call_submissions_email", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("open_calls.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Applicant details
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    organization_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    social_links: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Proposal content
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    proposal_summary: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_or_track: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attachment_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_answers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Review status & workflow
    # submitted | under_review | shortlisted | accepted | rejected | withdrawn
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="submitted")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    organizer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_to_applicant: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # One-click promotion references to live event entities
    promoted_to_speaker_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("speakers.id", ondelete="SET NULL"),
        nullable=True,
    )
    promoted_to_sponsor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sponsors.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    open_call: Mapped[OpenCall] = relationship("OpenCall", back_populates="submissions")
    event: Mapped[Event] = relationship("Event")
    user: Mapped[User | None] = relationship("User", foreign_keys=[user_id])
    reviewer: Mapped[User | None] = relationship("User", foreign_keys=[reviewed_by])
    promoted_speaker: Mapped[Speaker | None] = relationship(
        "Speaker", foreign_keys=[promoted_to_speaker_id]
    )
    promoted_sponsor: Mapped[Sponsor | None] = relationship(
        "Sponsor", foreign_keys=[promoted_to_sponsor_id]
    )

    def __repr__(self) -> str:
        return f"<OpenCallSubmission {self.title} applicant={self.name} status={self.status}>"
