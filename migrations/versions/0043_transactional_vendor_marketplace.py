"""Transactional Vendor Marketplace migration:
- Enhances vendors table with business profile, verification, ratings, subscriptions, balances
- Creates vendor_service_listings table
- Creates vendor_quote_requests and vendor_quote_recipients tables
- Creates vendor_quotations table
- Creates vendor_bookings table
- Creates vendor_reviews table
- Creates vendor_transactions ledger table
- Creates vendor_subscriptions table
- Creates vendor_featured_campaigns table
- Creates vendor_lead_credits table
- Creates vendor_payouts table
- Creates vendor_verification_requests table
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Enhance vendors table ──────────────────────────────────────────────
    op.add_column("vendors", sa.Column("logo_url", sa.Text(), nullable=True))
    op.add_column("vendors", sa.Column("service_areas", postgresql.JSONB(), nullable=True))
    op.add_column("vendors", sa.Column("social_links", postgresql.JSONB(), nullable=True))
    op.add_column("vendors", sa.Column("operating_hours", postgresql.JSONB(), nullable=True))
    op.add_column("vendors", sa.Column("starting_price", sa.Numeric(12, 2), nullable=True))
    op.add_column("vendors", sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"))
    op.add_column("vendors", sa.Column("faqs", postgresql.JSONB(), nullable=True))
    op.add_column("vendors", sa.Column("verification_status", sa.String(30), nullable=False, server_default="unverified"))
    op.add_column("vendors", sa.Column("verification_documents", postgresql.JSONB(), nullable=True))
    op.add_column("vendors", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("vendors", sa.Column("verification_notes", sa.Text(), nullable=True))
    op.add_column("vendors", sa.Column("subscription_tier", sa.String(30), nullable=False, server_default="free"))
    op.add_column("vendors", sa.Column("subscription_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("vendors", sa.Column("lead_credits_balance", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("vendors", sa.Column("rating_avg", sa.Numeric(3, 2), nullable=False, server_default="0.0"))
    op.add_column("vendors", sa.Column("reviews_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("vendors", sa.Column("is_featured", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("vendors", sa.Column("featured_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("vendors", sa.Column("custom_commission_rate", sa.Numeric(5, 2), nullable=True))
    op.add_column("vendors", sa.Column("payable_balance", sa.Numeric(12, 2), nullable=False, server_default="0.0"))
    op.add_column("vendors", sa.Column("total_earned", sa.Numeric(12, 2), nullable=False, server_default="0.0"))
    op.add_column("vendors", sa.Column("total_withdrawn", sa.Numeric(12, 2), nullable=False, server_default="0.0"))

    op.create_index("ix_vendors_verification", "vendors", ["verification_status"])
    op.create_index("ix_vendors_featured", "vendors", ["is_featured", "featured_until"])
    op.create_index("ix_vendors_rating", "vendors", ["rating_avg"])
    op.create_index("ix_vendors_sub_tier", "vendors", ["subscription_tier"])

    # ── 2. Vendor Service Listings ────────────────────────────────────────────
    op.create_table(
        "vendor_service_listings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("pricing_type", sa.String(30), nullable=False, server_default="fixed"),
        sa.Column("price", sa.Numeric(12, 2), nullable=False, server_default="0.0"),
        sa.Column("price_max", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("inclusions", postgresql.JSONB(), nullable=True),
        sa.Column("image_urls", postgresql.JSONB(), nullable=True),
        sa.Column("duration_hours", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_service_listings_vendor", "vendor_service_listings", ["vendor_id"])
    op.create_index("ix_service_listings_cat_active", "vendor_service_listings", ["category", "is_active"])

    # ── 3. Vendor Quote Requests ──────────────────────────────────────────────
    op.create_table(
        "vendor_quote_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_name", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=True),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_location", sa.String(255), nullable=True),
        sa.Column("expected_attendance", sa.Integer(), nullable=True),
        sa.Column("service_category", sa.String(50), nullable=False),
        sa.Column("budget_min", sa.Numeric(12, 2), nullable=True),
        sa.Column("budget_max", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("requirements", sa.Text(), nullable=False),
        sa.Column("preferred_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attachments", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_quote_requests_requester", "vendor_quote_requests", ["requester_id"])
    op.create_index("ix_quote_requests_status", "vendor_quote_requests", ["status"])

    # ── 4. Vendor Quote Recipients (Multi-Vendor Requests) ─────────────────────
    op.create_table(
        "vendor_quote_recipients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendor_quote_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("declined_reason", sa.Text(), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_quote_recipients_req_vendor", "vendor_quote_recipients", ["request_id", "vendor_id"], unique=True)
    op.create_index("ix_quote_recipients_vendor", "vendor_quote_recipients", ["vendor_id", "status"])

    # ── 5. Vendor Quotations ──────────────────────────────────────────────────
    op.create_table(
        "vendor_quotations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("quote_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendor_quote_requests.id", ondelete="SET NULL"), nullable=True),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendor_quote_recipients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("scope_of_work", sa.Text(), nullable=False),
        sa.Column("items", postgresql.JSONB(), nullable=True),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False, server_default="0.0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("deposit_required", sa.Numeric(12, 2), nullable=False, server_default="0.0"),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="submitted"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_quotations_vendor", "vendor_quotations", ["vendor_id"])
    op.create_index("ix_quotations_requester", "vendor_quotations", ["requester_id"])

    # ── 6. Vendor Bookings ────────────────────────────────────────────────────
    op.create_table(
        "vendor_bookings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("booking_reference", sa.String(50), nullable=False, unique=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("service_listing_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendor_service_listings.id", ondelete="SET NULL"), nullable=True),
        sa.Column("quotation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendor_quotations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_name", sa.String(255), nullable=True),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_location", sa.String(255), nullable=True),
        sa.Column("service_summary", sa.Text(), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False, server_default="0.0"),
        sa.Column("platform_commission_rate", sa.Numeric(5, 2), nullable=False, server_default="10.0"),
        sa.Column("commission_amount", sa.Numeric(12, 2), nullable=False, server_default="0.0"),
        sa.Column("vendor_earnings", sa.Numeric(12, 2), nullable=False, server_default="0.0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("cancellation_policy", sa.String(50), nullable=False, server_default="moderate"),
        sa.Column("cancellation_terms", sa.Text(), nullable=True),
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending_payment"),
        sa.Column("payment_reference", sa.String(255), nullable=True, unique=True),
        sa.Column("payment_method", sa.String(50), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("refund_amount", sa.Numeric(12, 2), nullable=False, server_default="0.0"),
        sa.Column("dispute_reason", sa.Text(), nullable=True),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_bookings_vendor", "vendor_bookings", ["vendor_id", "status"])
    op.create_index("ix_bookings_requester", "vendor_bookings", ["requester_id"])
    op.create_index("ix_bookings_reference", "vendor_bookings", ["booking_reference"])

    # ── 7. Vendor Reviews ─────────────────────────────────────────────────────
    op.create_table(
        "vendor_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendor_bookings.id", ondelete="CASCADE"), nullable=True, unique=True),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("response_from_vendor", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="published"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_reviews_vendor", "vendor_reviews", ["vendor_id", "status"])

    # ── 8. Vendor Transactions Ledger ─────────────────────────────────────────
    op.create_table(
        "vendor_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reference", sa.String(100), nullable=False, unique=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendor_bookings.id", ondelete="SET NULL"), nullable=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("gross_amount", sa.Numeric(12, 2), nullable=False, server_default="0.0"),
        sa.Column("platform_fee", sa.Numeric(12, 2), nullable=False, server_default="0.0"),
        sa.Column("net_amount", sa.Numeric(12, 2), nullable=False, server_default="0.0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("status", sa.String(30), nullable=False, server_default="completed"),
        sa.Column("payment_provider", sa.String(50), nullable=False, server_default="paystack"),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_vendor_tx_vendor", "vendor_transactions", ["vendor_id", "type"])

    # ── 9. Vendor Subscriptions ───────────────────────────────────────────────
    op.create_table(
        "vendor_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tier", sa.String(30), nullable=False, server_default="free"),
        sa.Column("price", sa.Numeric(12, 2), nullable=False, server_default="0.0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_reference", sa.String(255), nullable=True, unique=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_vendor_subs_vendor", "vendor_subscriptions", ["vendor_id", "status"])

    # ── 10. Vendor Featured Placement Campaigns ───────────────────────────────
    op.create_table(
        "vendor_featured_campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("placement", sa.String(50), nullable=False, server_default="marketplace_top"),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_paid", sa.Numeric(12, 2), nullable=False, server_default="0.0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("payment_reference", sa.String(255), nullable=True, unique=True),
        sa.Column("impressions_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clicks_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_featured_campaigns_status", "vendor_featured_campaigns", ["status", "placement", "end_date"])

    # ── 11. Vendor Lead Credits ───────────────────────────────────────────────
    op.create_table(
        "vendor_lead_credits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("credits_purchased", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("price_paid", sa.Numeric(12, 2), nullable=False, server_default="0.0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("payment_reference", sa.String(255), nullable=True, unique=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="completed"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_vendor_lead_credits_vendor", "vendor_lead_credits", ["vendor_id"])

    # ── 12. Vendor Payouts ────────────────────────────────────────────────────
    op.create_table(
        "vendor_payouts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False, server_default="0.0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("method", sa.String(30), nullable=False, server_default="manual"),
        sa.Column("account_details", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column("transfer_code", sa.String(255), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("initiated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_vendor_payouts_vendor", "vendor_payouts", ["vendor_id", "status"])

    # ── 13. Vendor Verification Requests ──────────────────────────────────────
    op.create_table(
        "vendor_verification_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("business_registration_number", sa.String(100), nullable=True),
        sa.Column("tax_id", sa.String(100), nullable=True),
        sa.Column("document_urls", postgresql.JSONB(), nullable=True),
        sa.Column("government_id_url", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_verification_requests_status", "vendor_verification_requests", ["status"])


def downgrade() -> None:
    op.drop_table("vendor_verification_requests")
    op.drop_table("vendor_payouts")
    op.drop_table("vendor_lead_credits")
    op.drop_table("vendor_featured_campaigns")
    op.drop_table("vendor_subscriptions")
    op.drop_table("vendor_transactions")
    op.drop_table("vendor_reviews")
    op.drop_table("vendor_bookings")
    op.drop_table("vendor_quotations")
    op.drop_table("vendor_quote_recipients")
    op.drop_table("vendor_quote_requests")
    op.drop_table("vendor_service_listings")

    op.drop_index("ix_vendors_sub_tier", table_name="vendors")
    op.drop_index("ix_vendors_rating", table_name="vendors")
    op.drop_index("ix_vendors_featured", table_name="vendors")
    op.drop_index("ix_vendors_verification", table_name="vendors")

    op.drop_column("vendors", "total_withdrawn")
    op.drop_column("vendors", "total_earned")
    op.drop_column("vendors", "payable_balance")
    op.drop_column("vendors", "custom_commission_rate")
    op.drop_column("vendors", "featured_until")
    op.drop_column("vendors", "is_featured")
    op.drop_column("vendors", "reviews_count")
    op.drop_column("vendors", "rating_avg")
    op.drop_column("vendors", "lead_credits_balance")
    op.drop_column("vendors", "subscription_expires_at")
    op.drop_column("vendors", "subscription_tier")
    op.drop_column("vendors", "verification_notes")
    op.drop_column("vendors", "verified_at")
    op.drop_column("vendors", "verification_documents")
    op.drop_column("vendors", "verification_status")
    op.drop_column("vendors", "faqs")
    op.drop_column("vendors", "currency")
    op.drop_column("vendors", "starting_price")
    op.drop_column("vendors", "operating_hours")
    op.drop_column("vendors", "social_links")
    op.drop_column("vendors", "service_areas")
    op.drop_column("vendors", "logo_url")

