from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.organization import Organization


class PaymentAccount(Base, TimestampMixin):
    """Linked payout account for an organization (Paystack subaccount, Stripe Connect, etc.)."""

    __tablename__ = "payment_accounts"
    __table_args__ = (Index("ix_payment_accounts_org", "org_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # paystack | flutterwave | stripe
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Human-readable label e.g. "GTBank 0123456789"
    account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # Instant settlement enabled (Paystack)
    instant_settlement: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    organization: Mapped[Organization] = relationship(
        "Organization", back_populates="payment_accounts"
    )
    payouts: Mapped[list[Payout]] = relationship("Payout", back_populates="payment_account")

    def __repr__(self) -> str:
        return f"<PaymentAccount {self.provider} org={self.org_id}>"


class Payout(Base, TimestampMixin):
    """A withdrawal request from an organizer after an event."""

    __tablename__ = "payouts"
    __table_args__ = (
        Index("ix_payouts_org_status", "org_id", "status"),
        Index("ix_payouts_event", "event_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )
    payment_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_accounts.id", ondelete="SET NULL"), nullable=True
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # pending | processing | paid | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    initiated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped[Organization] = relationship("Organization", back_populates="payouts")
    event: Mapped[Event | None] = relationship("Event")
    payment_account: Mapped[PaymentAccount | None] = relationship(
        "PaymentAccount", back_populates="payouts"
    )

    def __repr__(self) -> str:
        return f"<Payout {self.amount} {self.currency} {self.status}>"
