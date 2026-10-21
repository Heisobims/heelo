"""Add event fee toggle and payment account transfer fields:
- events.pass_fees_to_buyer (boolean, default True)
- payment_accounts.bank_code (varchar 50, nullable)
- payment_accounts.recipient_code (varchar 100, nullable)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "pass_fees_to_buyer", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.add_column(
        "payment_accounts",
        sa.Column("bank_code", sa.String(50), nullable=True),
    )
    op.add_column(
        "payment_accounts",
        sa.Column("recipient_code", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payment_accounts", "recipient_code")
    op.drop_column("payment_accounts", "bank_code")
    op.drop_column("events", "pass_fees_to_buyer")

