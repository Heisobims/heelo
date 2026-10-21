"""Add referral_discount_amount to orders - the portion of discount_amount
that came from the referral program specifically (not an organizer promo
code), so confirm_order() can have the platform fee absorb that cost first
instead of the organizer.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "referral_discount_amount",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("orders", "referral_discount_amount")
