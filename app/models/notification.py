from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Notification(Base, TimestampMixin):
    """In-app notification - displayed in the slide-in notification panel."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_read", "user_id", "is_read"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # registration_confirmed | order_paid | event_reminder | checkin_complete
    # campaign_sent | team_invite | connection_request | connection_accepted
    # direct_message | new_event | refund_issued
    type: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # URL to navigate to on click - relative path
    action_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Structured payload for rich rendering: {"event_id": "...", "event_title": "..."}
    extra_data: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    user: Mapped[User] = relationship("User", back_populates="notifications")

    def __repr__(self) -> str:
        return f"<Notification user={self.user_id} type={self.type}>"


class AuditLog(Base, TimestampMixin):
    """
    Immutable record of every state-changing action.
    Retained for 90 days visible to org admins; indefinitely for platform admins.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_org_created", "org_id", "created_at"),
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # e.g. event.published, registration.cancelled, payout.requested
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    # event | registration | order | user | organization | campaign | payout
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Before/after snapshot or any relevant context
    extra_data: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} entity={self.entity_type}:{self.entity_id}>"


class AdminBroadcast(Base, TimestampMixin):
    """
    Platform-wide promotional/announcement email sent by a platform admin to a
    category of users (all / organizers / attendees / vendors / admins).
    Distinct from the org-scoped Campaign model - this targets any user on the
    platform regardless of organization.
    """

    __tablename__ = "admin_broadcasts"
    __table_args__ = (Index("ix_admin_broadcasts_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # all | organizer | attendee | vendor | admin
    audience_category: Mapped[str] = mapped_column(String(20), nullable=False)
    # email | notification | both - where this broadcast is delivered
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="email")
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # draft | sending | sent | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<AdminBroadcast {self.subject!r} status={self.status}>"
