from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.community import AttendeeProfile
    from app.models.notification import Notification
    from app.models.organization import Organization, OrganizationMember


class User(Base, SoftDeleteMixin):
    """Platform user - can be an organizer, attendee, or both."""

    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_email_deleted", "email", "deleted_at"),
        Index("ix_users_oauth", "oauth_provider", "oauth_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # organizer | attendee | both | admin
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="attendee")
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    oauth_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    oauth_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    whatsapp_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    whatsapp_opted_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Public profile slug - e.g. tixdoo.com/p/<username>
    username: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True, index=True)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Opt-in demographics - for audience insights/filtering, never collected at signup.
    # ISO 3166-1 alpha-2, e.g. "NG"
    country: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True)
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    organizations: Mapped[list[Organization]] = relationship(
        "Organization", back_populates="owner", foreign_keys="Organization.owner_id"
    )
    org_memberships: Mapped[list[OrganizationMember]] = relationship(
        "OrganizationMember", back_populates="user", foreign_keys="[OrganizationMember.user_id]"
    )
    attendee_profile: Mapped[AttendeeProfile | None] = relationship(
        "AttendeeProfile", back_populates="user", uselist=False
    )
    notifications: Mapped[list[Notification]] = relationship("Notification", back_populates="user")

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class OTPCode(Base, TimestampMixin):
    """One-time password for email verification and 2FA."""

    __tablename__ = "otp_codes"
    __table_args__ = (Index("ix_otp_email_purpose", "email", "purpose"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Hashed - never stored plain
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # email_verification | login | whatsapp_verification
    purpose: Mapped[str] = mapped_column(String(50), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<OTPCode {self.email} {self.purpose}>"


class PasswordResetToken(Base, TimestampMixin):
    """Single-use token for password reset flow."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User")


class RefreshToken(Base, TimestampMixin):
    """Long-lived JWT refresh token - one per device/session."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user_revoked", "user_id", "revoked_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Stored as SHA-256 hash of the raw token
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device_info: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    user: Mapped[User] = relationship("User")
