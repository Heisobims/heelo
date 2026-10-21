"""Add plan_invoices table (self-serve org-plan billing) and the two
supporting Organization columns: pending_plan_change (scheduled downgrade,
preserves already-paid-for access until plan_expires_at) and
plan_reminder_sent_at (dedup marker for the renewal-reminder task).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=True),
        sa.Column("provider_reference", sa.String(length=255), nullable=True, unique=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "initiated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_plan_invoices_org", "plan_invoices", ["org_id"])
    op.create_index("ix_plan_invoices_org_id", "plan_invoices", ["org_id"])

    op.add_column(
        "organizations", sa.Column("pending_plan_change", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "organizations",
        sa.Column("plan_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "plan_reminder_sent_at")
    op.drop_column("organizations", "pending_plan_change")
    op.drop_index("ix_plan_invoices_org_id", table_name="plan_invoices")
    op.drop_index("ix_plan_invoices_org", table_name="plan_invoices")
    op.drop_table("plan_invoices")
