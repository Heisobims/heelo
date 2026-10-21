from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.event import Event, EventSession
    from app.models.ticketing import Registration
    from app.models.user import User


class Checkin(Base, TimestampMixin):
    """
    A single check-in event - one row per scan.
    One registration may have multiple rows if the event uses session-level check-in.
    """

    __tablename__ = "checkins"
    __table_args__ = (
        Index("ix_checkins_event_scanned", "event_id", "scanned_at"),
        Index("ix_checkins_registration", "registration_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    registration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("registrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("event_sessions.id", ondelete="SET NULL"), nullable=True
    )
    # qr | manual | kiosk | walk_in
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="qr")
    scanned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Device or kiosk identifier
    device_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    registration: Mapped[Registration] = relationship("Registration", back_populates="checkins")
    event: Mapped[Event] = relationship("Event")
    session: Mapped[EventSession | None] = relationship("EventSession")
    scanner: Mapped[User | None] = relationship("User", foreign_keys=[scanned_by])

    def __repr__(self) -> str:
        return f"<Checkin reg={self.registration_id} method={self.method}>"
