"""Add ad conversion pixels, abandoned recovery, and corporate tax invoicing fields.

Revision ID: 0048
Revises: 0047
Create Date: 2026-10-24
"""

from __future__ import annotations

from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Event ad pixels & tax info ──────────────────────────────────────────
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS meta_pixel_id VARCHAR(50) NULL;")
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS google_tag_id VARCHAR(50) NULL;")
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS tiktok_pixel_id VARCHAR(50) NULL;")
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS tax_rate NUMERIC(5, 2) NULL;")
    op.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS tax_id VARCHAR(100) NULL;")

    # ── Order abandoned recovery & corporate invoicing ──────────────────────
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS is_corporate BOOLEAN NOT NULL DEFAULT FALSE;")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS company_name VARCHAR(255) NULL;")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS tax_id VARCHAR(100) NULL;")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS billing_address TEXT NULL;")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS recovery_token VARCHAR(64) NULL;")
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS abandoned_recovery_sent_at TIMESTAMP WITH TIME ZONE NULL;")

    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_recovery_token ON orders (recovery_token) WHERE recovery_token IS NOT NULL;")
    op.execute("CREATE INDEX IF NOT EXISTS ix_orders_abandoned_recovery ON orders (payment_status, created_at) WHERE abandoned_recovery_sent_at IS NULL;")


def downgrade() -> None:
    op.drop_index("ix_orders_abandoned_recovery", table_name="orders", if_exists=True)
    op.drop_index("uq_orders_recovery_token", table_name="orders", if_exists=True)
    op.drop_column("orders", "abandoned_recovery_sent_at")
    op.drop_column("orders", "recovery_token")
    op.drop_column("orders", "billing_address")
    op.drop_column("orders", "tax_id")
    op.drop_column("orders", "company_name")
    op.drop_column("orders", "is_corporate")

    op.drop_column("events", "tax_id")
    op.drop_column("events", "tax_rate")
    op.drop_column("events", "tiktok_pixel_id")
    op.drop_column("events", "google_tag_id")
    op.drop_column("events", "meta_pixel_id")

