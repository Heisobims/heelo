from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.ticketing import Registration


class EventFeedback(Base, TimestampMixin):
    """Post-event rating + optional comment from an attendee — one per registration."""

    __tablename__ = "event_feedback"
    __table_args__ = (
        UniqueConstraint("registration_id", name="uq_feedback_registration"),
        Index("ix_event_feedback_event", "event_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    registration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("registrations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    event: Mapped[Event] = relationship("Event")
    registration: Mapped[Registration] = relationship("Registration")

    def __repr__(self) -> str:
        return f"<EventFeedback event={self.event_id} rating={self.rating}>"
