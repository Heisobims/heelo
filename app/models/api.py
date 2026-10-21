from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class ApiKey(Base, TimestampMixin):
    """Org-level API key for the public REST API (X-API-Key header)."""

    __tablename__ = "api_keys"
    __table_args__ = (Index("ix_api_keys_org_active", "org_id", "is_active"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # SHA-256 hash of the raw key - the raw key is shown once and never stored
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    # Key prefix shown in the UI e.g. "hlo_live_aBcD..."
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Organization] = relationship("Organization", back_populates="api_keys")

    def __repr__(self) -> str:
        return f"<ApiKey {self.name} org={self.org_id}>"


class WebhookSubscription(Base, TimestampMixin):
    """A URL that Heelo will POST to on specified event types."""

    __tablename__ = "webhook_subscriptions"
    __table_args__ = (Index("ix_webhook_subscriptions_org_active", "org_id", "is_active"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    # e.g. ["registration.created", "order.paid", "checkin.completed"]
    events: Mapped[list[str]] = mapped_column(ARRAY(String(100)), nullable=False)
    # Used to sign the HMAC-SHA256 payload
    secret: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    organization: Mapped[Organization] = relationship(
        "Organization", back_populates="webhook_subscriptions"
    )
    deliveries: Mapped[list[WebhookDelivery]] = relationship(
        "WebhookDelivery", back_populates="subscription", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<WebhookSubscription {self.url}>"


class WebhookDelivery(Base, TimestampMixin):
    """A single delivery attempt for a webhook event - retained for 30 days."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        Index("ix_webhook_deliveries_subscription_created", "subscription_id", "created_at"),
        Index("ix_webhook_deliveries_next_retry", "next_retry_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # HTTP response from the subscriber endpoint
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # pending | success | failed | exhausted
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    subscription: Mapped[WebhookSubscription] = relationship(
        "WebhookSubscription", back_populates="deliveries"
    )

    def __repr__(self) -> str:
        return f"<WebhookDelivery {self.event_type} status={self.status}>"
