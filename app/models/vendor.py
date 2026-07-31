from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


VENDOR_CATEGORIES = [
    "photography",
    "videography",
    "catering",
    "decorations",
    "security",
    "entertainment",
    "mc",
    "venue",
    "sound_lighting",
    "branding",
    "logistics",
    "other",
]

VENDOR_PRICE_RANGES = ["budget", "mid", "premium"]


class Vendor(Base, TimestampMixin):
    """A service vendor that event organizers can hire through Heelo."""

    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_vendor_slug"),
        Index("ix_vendors_category", "category"),
        Index("ix_vendors_status", "status"),
        Index("ix_vendors_location", "location_city", "location_country"),
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
    # Guest capacity — only meaningful for category="venue", null otherwise
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    website_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    portfolio_urls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    price_range: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # pending | active | suspended
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lead_count: Mapped[int] = mapped_column(nullable=False, default=0)

    user: Mapped[User] = relationship("User")
    leads: Mapped[list[VendorLead]] = relationship(
        "VendorLead", back_populates="vendor", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Vendor {self.business_name} category={self.category}>"


class VendorLead(Base, TimestampMixin):
    """Tracks when an organizer contacts a vendor through Heelo (commission trigger)."""

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
