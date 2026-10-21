"""Add vendor escrow and reconciliation tracking columns.

Revision ID: 0046
Revises: 0045
Create Date: 2026-10-21
"""

from __future__ import annotations

from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS escrow_balance NUMERIC(12, 2) NOT NULL DEFAULT 0.00;")
    op.execute("ALTER TABLE vendors ADD COLUMN IF NOT EXISTS disputed_balance NUMERIC(12, 2) NOT NULL DEFAULT 0.00;")
    op.execute("ALTER TABLE vendor_bookings ADD COLUMN IF NOT EXISTS escrow_status VARCHAR(30) NOT NULL DEFAULT 'pending';")
    op.execute("ALTER TABLE vendor_bookings ADD COLUMN IF NOT EXISTS fulfillment_submitted_at TIMESTAMP WITH TIME ZONE NULL;")
    op.execute("ALTER TABLE vendor_bookings ADD COLUMN IF NOT EXISTS fulfillment_proof_notes TEXT NULL;")
    op.execute("ALTER TABLE vendor_bookings ADD COLUMN IF NOT EXISTS fulfillment_proof_urls JSONB NULL;")
    op.execute("ALTER TABLE vendor_bookings ADD COLUMN IF NOT EXISTS escrow_released_at TIMESTAMP WITH TIME ZONE NULL;")
    op.execute("ALTER TABLE vendor_bookings ADD COLUMN IF NOT EXISTS auto_release_deadline TIMESTAMP WITH TIME ZONE NULL;")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vendor_bookings_escrow_status ON vendor_bookings (escrow_status);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vendor_bookings_auto_release ON vendor_bookings (auto_release_deadline) WHERE escrow_status = 'held_in_escrow';")


def downgrade() -> None:
    op.drop_index("ix_vendor_bookings_auto_release", table_name="vendor_bookings", if_exists=True)
    op.drop_index("ix_vendor_bookings_escrow_status", table_name="vendor_bookings", if_exists=True)
    op.drop_column("vendor_bookings", "auto_release_deadline")
    op.drop_column("vendor_bookings", "escrow_released_at")
    op.drop_column("vendor_bookings", "fulfillment_proof_urls")
    op.drop_column("vendor_bookings", "fulfillment_proof_notes")
    op.drop_column("vendor_bookings", "fulfillment_submitted_at")
    op.drop_column("vendor_bookings", "escrow_status")
    op.drop_column("vendors", "disputed_balance")
    op.drop_column("vendors", "escrow_balance")

