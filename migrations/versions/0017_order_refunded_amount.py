"""Add orders.refunded_amount to track cumulative refunds per order.

Revenue queries previously only summed orders with payment_status == "paid",
so a refunded/partially-refunded order dropped out of revenue totals
entirely instead of netting out just the refunded portion. This column lets
those queries subtract what was actually refunded while still counting
what the organizer retained.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("refunded_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("orders", "refunded_amount")
