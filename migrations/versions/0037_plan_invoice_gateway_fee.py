"""Add gateway_fee_amount to plan_invoices - org-plan checkout now grosses
up the charge by an estimated payment-gateway processing fee (mirroring
orders.gateway_fee_amount) so Heelo nets the full plan list price.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plan_invoices",
        sa.Column("gateway_fee_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("plan_invoices", "gateway_fee_amount")
