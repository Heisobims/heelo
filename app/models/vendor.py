from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.organization import Organization
    from app.models.user import User


VENDOR_CATEGORIES = [
    "catering",
    "photography",
    "videography",
    "decorations",
    "event_planning",
    "sound_lighting",
    "entertainment",
    "dj",
    "mc",
    "equipment_rentals",
    "branding_printing",
    "branding",
    "security",
    "transportation",
    "logistics",
    "beauty_makeup",
    "staffing_ushers",
    "cakes_desserts",
    "venue",
    "other",
]

VENDOR_PRICE_RANGES = ["budget", "mid", "premium"]


class Vendor(Base, TimestampMixin):
    """A service vendor that event organizers and attendees can hire through Tixdoo."""

    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_vendor_slug"),
        Index("ix_vendors_category", "category"),
        Index("ix_vendors_status", "status"),
        Index("ix_vendors_location", "location_city", "location_country"),
        Index("ix_vendors_verification", "verification_status"),
        Index("ix_vendors_featured", "is_featured", "featured_until"),
        Index("ix_vendors_rating", "rating_avg"),
        Index("ix_vendors_sub_tier", "subscription_tier"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    business_name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tagline: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    website_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    portfolio_urls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    portfolio_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    service_areas: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    social_links: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    operating_hours: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    starting_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    faqs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    price_range: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # pending | active | suspended
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lead_count: Mapped[int] = mapped_column(nullable=False, default=0)

    # Verification: unverified | pending | verified | rejected | suspended
    verification_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unverified")
    verification_documents: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Monetization: Subscriptions (free, starter, pro, premium)
    subscription_tier: Mapped[str] = mapped_column(String(30), nullable=False, default="free")
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lead_credits_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Reputation & Reviews
    rating_avg: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False, default=0.0)
    reviews_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Featured Listings Placement
    is_featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    featured_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Financial Ledger & Commissions
    custom_commission_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    escrow_balance: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    payable_balance: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    disputed_balance: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    total_earned: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    total_withdrawn: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)

    user: Mapped[User] = relationship("User")
    leads: Mapped[list[VendorLead]] = relationship(
        "VendorLead", back_populates="vendor", cascade="all, delete-orphan"
    )
    booth_applications: Mapped[list[BoothApplication]] = relationship(
        "BoothApplication", back_populates="vendor"
    )
    service_listings: Mapped[list[VendorServiceListing]] = relationship(
        "VendorServiceListing", back_populates="vendor", cascade="all, delete-orphan"
    )
    received_quotes: Mapped[list[VendorQuoteRecipient]] = relationship(
        "VendorQuoteRecipient", back_populates="vendor"
    )
    quotations: Mapped[list[VendorQuotation]] = relationship(
        "VendorQuotation", back_populates="vendor"
    )
    bookings: Mapped[list[VendorBooking]] = relationship(
        "VendorBooking", back_populates="vendor"
    )
    reviews: Mapped[list[VendorReview]] = relationship(
        "VendorReview", back_populates="vendor", cascade="all, delete-orphan"
    )
    transactions: Mapped[list[VendorTransaction]] = relationship(
        "VendorTransaction", back_populates="vendor"
    )
    payouts: Mapped[list[VendorPayout]] = relationship(
        "VendorPayout", back_populates="vendor"
    )
    verification_requests: Mapped[list[VendorVerificationRequest]] = relationship(
        "VendorVerificationRequest", back_populates="vendor"
    )
    subscriptions: Mapped[list[VendorSubscription]] = relationship(
        "VendorSubscription", back_populates="vendor"
    )
    featured_campaigns: Mapped[list[VendorFeaturedCampaign]] = relationship(
        "VendorFeaturedCampaign", back_populates="vendor"
    )
    lead_credit_purchases: Mapped[list[VendorLeadCreditPurchase]] = relationship(
        "VendorLeadCreditPurchase", back_populates="vendor"
    )

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def __repr__(self) -> str:
        return f"<Vendor {self.business_name} category={self.category}>"


class VendorLead(Base, TimestampMixin):
    """Tracks when an organizer contacts a vendor through Tixdoo."""

    __tablename__ = "vendor_leads"
    __table_args__ = (
        Index("ix_vendor_leads_vendor", "vendor_id"),
        Index("ix_vendor_leads_org", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    requester_name: Mapped[str] = mapped_column(String(255), nullable=False)
    requester_email: Mapped[str] = mapped_column(String(255), nullable=False)
    event_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # new | contacted | converted | closed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")

    vendor: Mapped[Vendor] = relationship("Vendor", back_populates="leads")
    organization: Mapped[Organization | None] = relationship("Organization")

    def __repr__(self) -> str:
        return f"<VendorLead vendor={self.vendor_id} from={self.requester_email}>"


class EventBoothPackage(Base, TimestampMixin):
    """A booth package configured by the organizer for exhibitors / vendors."""

    __tablename__ = "event_booth_packages"
    __table_args__ = (Index("ix_booth_packages_event", "event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    dimensions: Mapped[str | None] = mapped_column(String(100), nullable=True)
    total_booths: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    booths_remaining: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    amenities: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    event: Mapped[Event] = relationship("Event", back_populates="booth_packages")
    applications: Mapped[list[BoothApplication]] = relationship(
        "BoothApplication", back_populates="package"
    )

    def __repr__(self) -> str:
        return f"<EventBoothPackage {self.name} price={self.price}>"


class BoothApplication(Base, TimestampMixin):
    """An application from an exhibitor / vendor for an event booth."""

    __tablename__ = "booth_applications"
    __table_args__ = (
        Index("ix_booth_applications_event", "event_id"),
        Index("ix_booth_applications_vendor", "vendor_id"),
        Index("ix_booth_applications_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="SET NULL"),
        nullable=True,
    )
    package_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("event_booth_packages.id", ondelete="SET NULL"),
        nullable=True,
    )
    business_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    booth_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    assigned_booth_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    invoice_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    event: Mapped[Event] = relationship("Event", back_populates="booth_applications")
    package: Mapped[EventBoothPackage | None] = relationship(
        "EventBoothPackage", back_populates="applications"
    )
    vendor: Mapped[Vendor | None] = relationship("Vendor", back_populates="booth_applications")

    def __repr__(self) -> str:
        return f"<BoothApplication {self.business_name} status={self.status}>"


# ── Granular Service Listings ─────────────────────────────────────────────────
class VendorServiceListing(Base, TimestampMixin):
    """An individual service or package listed by a vendor."""

    __tablename__ = "vendor_service_listings"
    __table_args__ = (
        Index("ix_service_listings_vendor", "vendor_id"),
        Index("ix_service_listings_cat_active", "category", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    pricing_type: Mapped[str] = mapped_column(String(30), nullable=False, default="fixed")  # fixed, starting_at, range, quote_only
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    price_max: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    inclusions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    image_urls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    duration_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    vendor: Mapped[Vendor] = relationship("Vendor", back_populates="service_listings")

    def __repr__(self) -> str:
        return f"<VendorServiceListing {self.title} price={self.price}>"


# ── Request-a-Quote (RFQ) Models ──────────────────────────────────────────────
class VendorQuoteRequest(Base, TimestampMixin):
    """A formal Request for Quotation (RFQ) submitted by an organizer or client."""

    __tablename__ = "vendor_quote_requests"
    __table_args__ = (
        Index("ix_quote_requests_requester", "requester_id"),
        Index("ix_quote_requests_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expected_attendance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_category: Mapped[str] = mapped_column(String(50), nullable=False)
    budget_min: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    budget_max: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    requirements: Mapped[str] = mapped_column(Text, nullable=False)
    preferred_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attachments: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")  # open, closed, cancelled

    requester: Mapped[User] = relationship("User")
    organization: Mapped[Organization | None] = relationship("Organization")
    event: Mapped[Event | None] = relationship("Event")
    recipients: Mapped[list[VendorQuoteRecipient]] = relationship(
        "VendorQuoteRecipient", back_populates="request", cascade="all, delete-orphan"
    )
    quotations: Mapped[list[VendorQuotation]] = relationship(
        "VendorQuotation", back_populates="quote_request"
    )

    def __repr__(self) -> str:
        return f"<VendorQuoteRequest {self.event_name} status={self.status}>"


class VendorQuoteRecipient(Base, TimestampMixin):
    """M-to-N assignment of a quote request to target vendors."""

    __tablename__ = "vendor_quote_recipients"
    __table_args__ = (
        Index("ix_quote_recipients_req_vendor", "request_id", "vendor_id", unique=True),
        Index("ix_quote_recipients_vendor", "vendor_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendor_quote_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")  # pending, viewed, quoted, declined
    declined_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    request: Mapped[VendorQuoteRequest] = relationship("VendorQuoteRequest", back_populates="recipients")
    vendor: Mapped[Vendor] = relationship("Vendor", back_populates="received_quotes")
    quotations: Mapped[list[VendorQuotation]] = relationship(
        "VendorQuotation", back_populates="recipient"
    )

    def __repr__(self) -> str:
        return f"<VendorQuoteRecipient request={self.request_id} vendor={self.vendor_id}>"


class VendorQuotation(Base, TimestampMixin):
    """A formal quotation submitted by a vendor in response to an RFQ or direct request."""

    __tablename__ = "vendor_quotations"
    __table_args__ = (
        Index("ix_quotations_vendor", "vendor_id"),
        Index("ix_quotations_requester", "requester_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quote_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendor_quote_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendor_quote_recipients.id", ondelete="SET NULL"),
        nullable=True,
    )
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="CASCADE"),
        nullable=False,
    )
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    scope_of_work: Mapped[str] = mapped_column(Text, nullable=False)
    items: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    deposit_required: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    attachment_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="submitted")  # submitted, accepted, rejected, expired

    quote_request: Mapped[VendorQuoteRequest | None] = relationship("VendorQuoteRequest", back_populates="quotations")
    recipient: Mapped[VendorQuoteRecipient | None] = relationship("VendorQuoteRecipient", back_populates="quotations")
    vendor: Mapped[Vendor] = relationship("Vendor", back_populates="quotations")
    requester: Mapped[User] = relationship("User")
    booking: Mapped[VendorBooking | None] = relationship("VendorBooking", back_populates="quotation", uselist=False)

    def __repr__(self) -> str:
        return f"<VendorQuotation {self.title} total={self.total_amount}>"


# ── Bookings & Contracts ──────────────────────────────────────────────────────
class VendorBooking(Base, TimestampMixin):
    """A binding transactional booking for vendor services."""

    __tablename__ = "vendor_bookings"
    __table_args__ = (
        Index("ix_bookings_vendor", "vendor_id", "status"),
        Index("ix_bookings_requester", "requester_id"),
        Index("ix_bookings_reference", "booking_reference"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_reference: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="RESTRICT"),
        nullable=False,
    )
    service_listing_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendor_service_listings.id", ondelete="SET NULL"),
        nullable=True,
    )
    quotation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendor_quotations.id", ondelete="SET NULL"),
        nullable=True,
    )
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_summary: Mapped[str] = mapped_column(Text, nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    platform_commission_rate: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=10.0)
    commission_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    vendor_earnings: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    cancellation_policy: Mapped[str] = mapped_column(String(50), nullable=False, default="moderate")  # flexible, moderate, strict
    cancellation_terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending_payment")  # pending_payment, confirmed, in_progress, delivered, completed, cancelled, disputed
    escrow_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")  # pending, held_in_escrow, partially_released, released, refunded, disputed
    payment_reference: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fulfillment_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fulfillment_proof_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    fulfillment_proof_urls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    escrow_released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_release_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    refund_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    dispute_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    vendor: Mapped[Vendor] = relationship("Vendor", back_populates="bookings")
    service_listing: Mapped[VendorServiceListing | None] = relationship("VendorServiceListing")
    quotation: Mapped[VendorQuotation | None] = relationship("VendorQuotation", back_populates="booking")
    requester: Mapped[User] = relationship("User")
    organization: Mapped[Organization | None] = relationship("Organization")
    event: Mapped[Event | None] = relationship("Event")
    review: Mapped[VendorReview | None] = relationship("VendorReview", back_populates="booking", uselist=False)

    def __repr__(self) -> str:
        return f"<VendorBooking {self.booking_reference} status={self.status}>"


# ── Reviews & Reputation ──────────────────────────────────────────────────────
class VendorReview(Base, TimestampMixin):
    """A client review verified against an actual completed booking."""

    __tablename__ = "vendor_reviews"
    __table_args__ = (
        Index("ix_reviews_vendor", "vendor_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="CASCADE"),
        nullable=False,
    )
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendor_bookings.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 to 5
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    response_from_vendor: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="published")  # published, reported, hidden

    vendor: Mapped[Vendor] = relationship("Vendor", back_populates="reviews")
    booking: Mapped[VendorBooking | None] = relationship("VendorBooking", back_populates="review")
    reviewer: Mapped[User] = relationship("User")

    def __repr__(self) -> str:
        return f"<VendorReview rating={self.rating} vendor={self.vendor_id}>"


# ── Financial Ledger & Monetization Models ────────────────────────────────────
class VendorTransaction(Base, TimestampMixin):
    """An immutable financial ledger row tracking all vendor platform money flows."""

    __tablename__ = "vendor_transactions"
    __table_args__ = (
        Index("ix_vendor_tx_vendor", "vendor_id", "type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="CASCADE"),
        nullable=False,
    )
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendor_bookings.id", ondelete="SET NULL"),
        nullable=True,
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # booking_payment, escrow_deposit, escrow_release, escrow_dispute_freeze, commission_deduction, subscription_fee, featured_listing_fee, lead_credit_purchase, payout, refund
    gross_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    platform_fee: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    net_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="completed")  # pending, completed, failed, reversed
    payment_provider: Mapped[str] = mapped_column(String(50), nullable=False, default="paystack")
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    vendor: Mapped[Vendor] = relationship("Vendor", back_populates="transactions")
    booking: Mapped[VendorBooking | None] = relationship("VendorBooking")

    def __repr__(self) -> str:
        return f"<VendorTransaction {self.type} gross={self.gross_amount} net={self.net_amount}>"


class VendorSubscription(Base, TimestampMixin):
    """Vendor subscription tier (Model B: Free, Starter, Pro, Premium)."""

    __tablename__ = "vendor_subscriptions"
    __table_args__ = (
        Index("ix_vendor_subs_vendor", "vendor_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="CASCADE"),
        nullable=False,
    )
    tier: Mapped[str] = mapped_column(String(30), nullable=False, default="free")  # free, starter, pro, premium
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")  # active, expired, cancelled

    vendor: Mapped[Vendor] = relationship("Vendor", back_populates="subscriptions")

    def __repr__(self) -> str:
        return f"<VendorSubscription {self.tier} vendor={self.vendor_id} status={self.status}>"


class VendorFeaturedCampaign(Base, TimestampMixin):
    """Sponsored placement campaign (Model C)."""

    __tablename__ = "vendor_featured_campaigns"
    __table_args__ = (
        Index("ix_featured_campaigns_status", "status", "placement", "end_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="CASCADE"),
        nullable=False,
    )
    placement: Mapped[str] = mapped_column(String(50), nullable=False, default="marketplace_top")
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_paid: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    payment_reference: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    impressions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clicks_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")  # active, expired, cancelled

    vendor: Mapped[Vendor] = relationship("Vendor", back_populates="featured_campaigns")

    def __repr__(self) -> str:
        return f"<VendorFeaturedCampaign {self.placement} vendor={self.vendor_id}>"


class VendorLeadCreditPurchase(Base, TimestampMixin):
    """Purchased lead credits for viewing qualified RFQ contacts (Model D)."""

    __tablename__ = "vendor_lead_credits"
    __table_args__ = (
        Index("ix_vendor_lead_credits_vendor", "vendor_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="CASCADE"),
        nullable=False,
    )
    credits_purchased: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price_paid: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    payment_reference: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="completed")

    vendor: Mapped[Vendor] = relationship("Vendor", back_populates="lead_credit_purchases")

    def __repr__(self) -> str:
        return f"<VendorLeadCreditPurchase {self.credits_purchased} credits>"


class VendorPayout(Base, TimestampMixin):
    """A withdrawal disbursement from vendor payable earnings to their bank account."""

    __tablename__ = "vendor_payouts"
    __table_args__ = (
        Index("ix_vendor_payouts_vendor", "vendor_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NGN")
    method: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")  # manual, paystack_transfer, flutterwave_transfer
    account_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")  # pending, processing, completed, failed
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transfer_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    initiated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    vendor: Mapped[Vendor] = relationship("Vendor", back_populates="payouts")
    initiator: Mapped[User | None] = relationship("User")

    def __repr__(self) -> str:
        return f"<VendorPayout {self.amount} {self.currency} status={self.status}>"


class VendorVerificationRequest(Base, TimestampMixin):
    """Business document submission for official verified vendor badge (Phase 11)."""

    __tablename__ = "vendor_verification_requests"
    __table_args__ = (
        Index("ix_verification_requests_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vendors.id", ondelete="CASCADE"),
        nullable=False,
    )
    business_registration_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    document_urls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    government_id_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")  # pending, approved, rejected
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    vendor: Mapped[Vendor] = relationship("Vendor", back_populates="verification_requests")
    reviewer: Mapped[User | None] = relationship("User")

    def __repr__(self) -> str:
        return f"<VendorVerificationRequest vendor={self.vendor_id} status={self.status}>"
