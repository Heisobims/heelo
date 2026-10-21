"""Add fee-passthrough support: events.pass_fees_to_buyer (organizer toggle,
default off - preserves current behavior) and the two order-level fields
that record what happened at checkout time: orders.fees_passed_to_buyer and
orders.gateway_fee_amount.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "pass_fees_to_buyer", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "fees_passed_to_buyer", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "orders",
        sa.Column("gateway_fee_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("orders", "gateway_fee_amount")
    op.drop_column("orders", "fees_passed_to_buyer")
    op.drop_column("events", "pass_fees_to_buyer")
