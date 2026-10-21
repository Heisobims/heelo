"""Add tables and columns for:
- event booth packages and applications
- event affiliates and affiliate payouts
- session bookmarks and track color
- event reminder countdown timestamps
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Event reminder countdown columns
    op.add_column(
        "events",
        sa.Column("reminder_24h_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("reminder_1h_sent_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 2. Event session track color
    op.add_column(
        "event_sessions",
        sa.Column("track_color", sa.String(30), nullable=True),
    )

    # 3. Session bookmarks
    op.create_table(
        "session_bookmarks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "session_id", name="uq_session_bookmark_user_session"),
    )
    op.create_index("ix_session_bookmarks_user", "session_bookmarks", ["user_id"])
    op.create_index("ix_session_bookmarks_session", "session_bookmarks", ["session_id"])

    # 4. Booth packages
    op.create_table(
        "event_booth_packages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("dimensions", sa.String(100), nullable=True),
        sa.Column("total_booths", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("booths_remaining", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("amenities", postgresql.JSONB(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_booth_packages_event", "event_booth_packages", ["event_id"])

    # 5. Booth applications
    op.create_table(
        "booth_applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "vendor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vendors.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "package_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_booth_packages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("business_name", sa.String(255), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=False),
        sa.Column("contact_email", sa.String(255), nullable=False),
        sa.Column("contact_phone", sa.String(50), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("booth_requirements", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("price", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("assigned_booth_number", sa.String(50), nullable=True),
        sa.Column("payment_reference", sa.String(255), nullable=True, unique=True),
        sa.Column("invoice_url", sa.Text(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_booth_applications_event", "booth_applications", ["event_id"])
    op.create_index("ix_booth_applications_vendor", "booth_applications", ["vendor_id"])
    op.create_index("ix_booth_applications_status", "booth_applications", ["status"])

    # 6. Event affiliates
    op.create_table(
        "event_affiliates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("promoter_name", sa.String(255), nullable=False),
        sa.Column("promoter_email", sa.String(255), nullable=False),
        sa.Column("promoter_phone", sa.String(50), nullable=True),
        sa.Column("affiliate_code", sa.String(50), nullable=False),
        sa.Column("commission_type", sa.String(20), nullable=False, server_default="percentage"),
        sa.Column("commission_rate", sa.Numeric(10, 2), nullable=False, server_default="10.0"),
        sa.Column("clicks_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tickets_sold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gross_sales", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("commission_earned", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("commission_paid", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("payout_status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("payout_bank_code", sa.String(50), nullable=True),
        sa.Column("payout_account_number", sa.String(50), nullable=True),
        sa.Column("payout_account_name", sa.String(255), nullable=True),
        sa.Column("recipient_code", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("event_id", "affiliate_code", name="uq_affiliate_event_code"),
    )
    op.create_index("ix_event_affiliates_event", "event_affiliates", ["event_id"])
    op.create_index("ix_event_affiliates_code", "event_affiliates", ["affiliate_code"])

    # 7. Affiliate payouts
    op.create_table(
        "affiliate_payouts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "affiliate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_affiliates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("transfer_reference", sa.String(255), nullable=True),
        sa.Column("transfer_code", sa.String(255), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="completed"),
        sa.Column("method", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_affiliate_payouts_affiliate", "affiliate_payouts", ["affiliate_id"])


def downgrade() -> None:
    op.drop_table("affiliate_payouts")
    op.drop_table("event_affiliates")
    op.drop_table("booth_applications")
    op.drop_table("event_booth_packages")
    op.drop_table("session_bookmarks")
    op.drop_column("event_sessions", "track_color")
    op.drop_column("events", "reminder_1h_sent_at")
    op.drop_column("events", "reminder_24h_sent_at")

