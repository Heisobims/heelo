from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.checkin import Checkin
    from app.models.event import Event
    from app.models.user import User


class TicketType(Base, TimestampMixin):
    """A purchasable tier within an event (Free, General, VIP, Early Bird, Group)."""

    __tablename__ = "ticket_types"
    __table_args__ = (Index("ix_ticket_types_event_visible", "event_id", "is_visible"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    # ISO 4217 e.g. NGN, USD, KES
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)  # null = unlimited
    quantity_sold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quantity_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # free | general | early_bird | vip | group
    tier: Mapped[str] = mapped_column(String(20), nullable=False, default="general")
    sale_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sale_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Max tickets per order (for group tickets this may be > 1)
    max_per_order: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    min_per_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    event: Mapped[Event] = relationship("Event", back_populates="ticket_types")
    registrations: Mapped[list[Registration]] = relationship(
        "Registration", back_populates="ticket_type"
    )
    waitlists: Mapped[list[Waitlist]] = relationship("Waitlist", back_populates="ticket_type")

    def __repr__(self) -> str:
        return f"<TicketType {self.name} event={self.event_id}>"


class RegistrationFormField(Base, TimestampMixin):
    """Custom field added to an event's registration form."""

    __tablename__ = "registration_form_fields"
    __table_args__ = (Index("ix_reg_form_fields_event", "event_id", "sort_order"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    # short_text | long_text | dropdown | multi_select | checkbox | file_upload
    field_type: Mapped[str] = mapped_column(String(30), nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # JSON array of option strings for dropdown / multi_select
    options: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    applies_to_ticket_type_ids: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # null = applies to all ticket types

    answers: Mapped[list[RegistrationAnswer]] = relationship(
        "RegistrationAnswer", back_populates="field"
    )


class Registration(Base, TimestampMixin):
    """A single attendee's ticket - confirmed or pending payment."""

    __tablename__ = "registrations"
    __table_args__ = (
        Index("ix_registrations_event_status", "event_id", "status"),
        Index("ix_registrations_email", "attendee_email"),
        Index("ix_registrations_qr", "qr_code", unique=True),
        Index("ix_registrations_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    ticket_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ticket_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Null for guest checkout - linked after account creation if user claims
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    attendee_name: Mapped[str] = mapped_column(String(255), nullable=False)
    attendee_email: Mapped[str] = mapped_column(String(255), nullable=False)
    attendee_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Unique signed QR payload (base64 encoded JWT)
    qr_code: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    # pending | confirmed | cancelled | refunded | transferred
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_in_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Ticket PDF URL in R2
    ticket_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # WhatsApp delivery status
    whatsapp_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Attendee opted in to receive ticket/reminders via WhatsApp (copied from Order at registration)
    whatsapp_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Transfer support
    transferred_from_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("registrations.id", ondelete="SET NULL"), nullable=True
    )
    transfer_token: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    transfer_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Public "refer a friend" code - deliberately NOT the registration's own id,
    # since that id is also the bare capability-token behind qr.png/badge.pdf/
    # certificate.pdf. Sharing a referral link must never leak access to those.
    referral_token: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)

    event: Mapped[Event] = relationship("Event", back_populates="registrations")
    ticket_type: Mapped[TicketType] = relationship("TicketType", back_populates="registrations")
    order: Mapped[Order | None] = relationship("Order", back_populates="registrations")
    user: Mapped[User | None] = relationship("User", foreign_keys=[user_id])
    checkins: Mapped[list[Checkin]] = relationship("Checkin", back_populates="registration")
    answers: Mapped[list[RegistrationAnswer]] = relationship(
        "RegistrationAnswer", back_populates="registration"
    )

    def __repr__(self) -> str:
        return f"<Registration {self.attendee_email} event={self.event_id}>"


class RegistrationAnswer(Base, TimestampMixin):
    """Answer to a custom registration form field."""

    __tablename__ = "registration_answers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    registration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("registrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("registration_form_fields.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Stores text, JSON array for multi_select, or file URL for file_upload
    value: Mapped[str | None] = mapped_column(Text, nullable=True)

    registration: Mapped[Registration] = relationship("Registration", back_populates="answers")
    field: Mapped[RegistrationFormField] = relationship(
        "RegistrationFormField", back_populates="answers"
    )


# payment_status values that still count toward revenue (a refund reduces
# how much of the order's amount counts, but doesn't zero it out - see
# Order.refunded_amount).
REVENUE_STATUSES = ("paid", "partially_refunded", "refunded")


class Order(Base, TimestampMixin):
    """Payment order - contains one or more tickets from the same event."""

    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_event_status", "event_id", "payment_status"),
        Index("ix_orders_reference", "payment_reference"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Null for guest checkout
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Denormalised for quick access
    buyer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    buyer_email: Mapped[str] = mapped_column(String(255), nullable=False)
    buyer_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Buyer opted in to WhatsApp contact (ticket delivery, reminders, bot replies)
    whatsapp_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    # Amount after platform fee
    net_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    platform_fee: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # paystack | flutterwave | stripe | free
    payment_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    # pending | paid | failed | refunded | partially_refunded
    payment_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    invoice_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Promo code used
    promo_code_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("promo_codes.id", ondelete="SET NULL"), nullable=True
    )
    discount_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    # Portion of discount_amount specifically from the referral program (not
    # organizer-created promo codes) - split out so confirm_order() can have
    # the platform fee absorb this cost first, rather than the organizer.
    referral_discount_amount: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0
    )
    # True for every non-free order (the buyer-pays-checkout-fees model is
    # mandatory) - False only for free orders and for historical orders
    # placed before that became mandatory. When True, total_amount already
    # includes platform_fee and gateway_fee_amount on top of the ticket
    # price, and confirm_order() must not re-derive platform_fee/net_amount
    # from scratch.
    fees_passed_to_buyer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Estimated payment-gateway processing fee charged to the buyer on top
    # of the ticket price, when fees_passed_to_buyer is True. The gateway's
    # real deducted fee may vary slightly from this estimate (it depends on
    # the payment method the buyer picks on the gateway's own checkout page,
    # which isn't known until after this order is created) - any variance is
    # absorbed by Heelo, never the organizer or the buyer.
    gateway_fee_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    # Cumulative gross amount refunded back to the buyer across all cancelled
    # items in this order. Subtract from net_amount/total_amount to get what
    # the organizer actually retains - the platform fee is not returned on
    # refund, so this is not simply proportional to net_amount.
    refunded_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    # True when the organizer's net_amount was actually paid out automatically
    # at charge time (a Paystack/Flutterwave subaccount split or a verified
    # Stripe Connect destination charge fired for this specific order) - set
    # once, at initialize_payment() time, and never changed afterward, since
    # an org's payment-account configuration can change after the fact and
    # this must reflect what actually happened to *this* order's money, not
    # the org's current setup. False means Heelo is holding net_amount and
    # owes it to the organizer - see app/services/payout_service.py.
    auto_split_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Corporate invoicing & VAT compliance
    is_corporate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Abandoned checkout recovery
    recovery_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    abandoned_recovery_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # UTM / referral tracking
    utm_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(255), nullable=True)
    referral_code: Mapped[str | None] = mapped_column(String(100), nullable=True)

    user: Mapped[User | None] = relationship("User")
    event: Mapped[Event] = relationship("Event")
    items: Mapped[list[OrderItem]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )
    registrations: Mapped[list[Registration]] = relationship("Registration", back_populates="order")
    promo_code: Mapped[PromoCode | None] = relationship("PromoCode")

    def __repr__(self) -> str:
        return f"<Order {self.id} {self.payment_status}>"


class OrderItem(Base, TimestampMixin):
    """One line item in an order - quantity of a specific ticket type."""

    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ticket_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ticket_types.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    subtotal: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    order: Mapped[Order] = relationship("Order", back_populates="items")
    ticket_type: Mapped[TicketType] = relationship("TicketType")


class PromoCode(Base, TimestampMixin):
    """Discount code for an event's ticket sales."""

    __tablename__ = "promo_codes"
    __table_args__ = (
        UniqueConstraint("event_id", "code", name="uq_promo_event_code"),
        Index("ix_promo_codes_event", "event_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    # percent | fixed
    discount_type: Mapped[str] = mapped_column(String(10), nullable=False)
    discount_value: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)  # null = unlimited
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Restrict to specific ticket type IDs (null = all ticket types)
    applicable_ticket_type_ids: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    event: Mapped[Event] = relationship("Event", back_populates="promo_codes")

    def __repr__(self) -> str:
        return f"<PromoCode {self.code}>"


class Waitlist(Base, TimestampMixin):
    """Queue for a sold-out ticket type - auto-notified on cancellation."""

    __tablename__ = "waitlists"
    __table_args__ = (Index("ix_waitlists_event_position", "event_id", "position"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ticket_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ticket_types.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Expiry window after notification - if not claimed, next person is notified
    offer_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    event: Mapped[Event] = relationship("Event", back_populates="waitlists")
    ticket_type: Mapped[TicketType] = relationship("TicketType", back_populates="waitlists")
    user: Mapped[User | None] = relationship("User")
