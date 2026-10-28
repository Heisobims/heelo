"""Add venue specifications, security deposit escrow, and blackout dates.

Revision ID: 0050
Revises: 0049
Create Date: 2026-10-28
"""

from __future__ import annotations

from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Add venue_specs to vendors ─────────────────────────────────────────────
    op.execute("""
        ALTER TABLE vendors
        ADD COLUMN IF NOT EXISTS venue_specs JSONB NULL DEFAULT NULL;
    """)

    # ── Add security deposit columns to vendor_bookings ───────────────────────
    op.execute("""
        ALTER TABLE vendor_bookings
        ADD COLUMN IF NOT EXISTS security_deposit_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.0,
        ADD COLUMN IF NOT EXISTS security_deposit_status VARCHAR(30) NOT NULL DEFAULT 'none';
    """)

    # ── Table: vendor_blackout_dates ──────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS vendor_blackout_dates (
            id UUID PRIMARY KEY,
            vendor_id UUID NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
            start_date TIMESTAMP WITH TIME ZONE NOT NULL,
            end_date TIMESTAMP WITH TIME ZONE NOT NULL,
            reason VARCHAR(255) NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_blackout_vendor_dates 
        ON vendor_blackout_dates (vendor_id, start_date, end_date);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vendor_blackout_dates;")
    op.execute("ALTER TABLE vendor_bookings DROP COLUMN IF EXISTS security_deposit_status;")
    op.execute("ALTER TABLE vendor_bookings DROP COLUMN IF EXISTS security_deposit_amount;")
    op.execute("ALTER TABLE vendors DROP COLUMN IF EXISTS venue_specs;")
