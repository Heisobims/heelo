from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.event import Event


class Speaker(Base, TimestampMixin):
    """Speaker profile — reusable across events within an org."""

    __tablename__ = "speakers"
    __table_args__ = (Index("ix_speakers_org", "org_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
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

    def __repr__(self) -> str:
        return f"<Speaker {self.name}>"


class Sponsor(Base, TimestampMixin):
    """Sponsor entry on a specific event."""

    __tablename__ = "sponsors"
    __table_args__ = (Index("ix_sponsors_event", "event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # gold | silver | bronze | partner
    tier: Mapped[str] = mapped_column(String(20), nullable=False, default="partner")
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0)

    event: Mapped[Event] = relationship("Event", back_populates="sponsors")

    def __repr__(self) -> str:
        return f"<Sponsor {self.name} tier={self.tier}>"
