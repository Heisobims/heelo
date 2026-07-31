from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.api import ApiKey, WebhookSubscription
    from app.models.campaign import Campaign
    from app.models.event import Event
    from app.models.payment import PaymentAccount, Payout
    from app.models.speaker import Speaker
    from app.models.user import User


class Organization(Base, TimestampMixin):
    """An organization owns events and has a team. One user can own/belong to many orgs."""

    __tablename__ = "organizations"
    __table_args__ = (Index("ix_organizations_slug", "slug", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Public-facing contact — shown in campaign email footers, distinct from the owner's login email
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    instagram_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    twitter_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    facebook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # ISO 3166-1 alpha-2 country code
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    # ISO 4217 currency code — used as default for new events
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    # Custom domain for white-label — e.g. events.mycompany.com
    custom_domain: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    custom_domain_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # starter | growth | pro | enterprise
    plan: Mapped[str] = mapped_column(String(20), nullable=False, default="starter")
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    owner: Mapped[User] = relationship(
        "User", back_populates="organizations", foreign_keys=[owner_id]
    )
    members: Mapped[list[OrganizationMember]] = relationship(
        "OrganizationMember", back_populates="organization", cascade="all, delete-orphan"
    )
    events: Mapped[list[Event]] = relationship("Event", back_populates="organization")
    payment_accounts: Mapped[list[PaymentAccount]] = relationship(
        "PaymentAccount", back_populates="organization"
    )
    payouts: Mapped[list[Payout]] = relationship("Payout", back_populates="organization")
    campaigns: Mapped[list[Campaign]] = relationship("Campaign", back_populates="organization")
    api_keys: Mapped[list[ApiKey]] = relationship("ApiKey", back_populates="organization")
    webhook_subscriptions: Mapped[list[WebhookSubscription]] = relationship(
        "WebhookSubscription", back_populates="organization"
    )
    speakers: Mapped[list[Speaker]] = relationship("Speaker", back_populates="organization")

    def __repr__(self) -> str:
        return f"<Organization {self.slug}>"


class OrganizationMember(Base, TimestampMixin):
    """Join table: which users belong to which orgs, and their role within the org."""

    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_org_member"),
        Index("ix_org_members_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable until invite is accepted (non-registered invitees have no user yet)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    # Email used for the invite (kept for pending invites & audit)
    invited_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # admin | organizer | finance | checkin_staff
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="organizer")
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    invited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # invite_pending | active | suspended
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="invite_pending")

    # ── Relationships ─────────────────────────────────────────────────────────
    organization: Mapped[Organization] = relationship("Organization", back_populates="members")
    user: Mapped[User] = relationship(
        "User", back_populates="org_memberships", foreign_keys=[user_id]
    )

    def __repr__(self) -> str:
        return f"<OrganizationMember org={self.org_id} user={self.user_id} role={self.role}>"
