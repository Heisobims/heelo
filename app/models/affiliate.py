from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.user import User


class EventAffiliate(Base, TimestampMixin):
    """An ambassador / promoter / affiliate for an event who earns commission on referred ticket sales."""

    __tablename__ = "event_affiliates"
    __table_args__ = (
        UniqueConstraint("event_id", "affiliate_code", name="uq_affiliate_event_code"),
        Index("ix_event_affiliates_event", "event_id"),
        Index("ix_event_affiliates_code", "affiliate_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    promoter_name: Mapped[str] = mapped_column(String(255), nullable=False)
    promoter_email: Mapped[str] = mapped_column(String(255), nullable=False)
    promoter_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    affiliate_code: Mapped[str] = mapped_column(String(50), nullable=False)
    # "percentage" | "fixed"
    commission_type: Mapped[str] = mapped_column(String(20), nullable=False, default="percentage")
    commission_rate: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=10.0)
    clicks_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tickets_sold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gross_sales: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    commission_earned: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    commission_paid: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    # "pending" | "paid" | "partial"
    payout_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    payout_bank_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payout_account_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payout_account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipient_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    event: Mapped[Event] = relationship("Event", back_populates="affiliates")
    user: Mapped[User | None] = relationship("User")
    payouts: Mapped[list[AffiliatePayout]] = relationship(
        "AffiliatePayout", back_populates="affiliate", cascade="all, delete-orphan"
    )

    @property
    def commission_owed(self) -> float:
        return max(0.0, float(self.commission_earned) - float(self.commission_paid))

    def __repr__(self) -> str:
        return f"<EventAffiliate {self.promoter_name} code={self.affiliate_code}>"


class AffiliatePayout(Base):
    """A recorded commission disbursement to an affiliate."""

    __tablename__ = "affiliate_payouts"
    __table_args__ = (Index("ix_affiliate_payouts_affiliate", "affiliate_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    affiliate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("event_affiliates.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    transfer_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transfer_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # "completed" | "pending" | "failed"
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="completed")
    # "manual" | "paystack_transfer"
    method: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    affiliate: Mapped[EventAffiliate] = relationship("EventAffiliate", back_populates="payouts")

    def __repr__(self) -> str:
        return f"<AffiliatePayout affiliate={self.affiliate_id} amount={self.amount}>"

