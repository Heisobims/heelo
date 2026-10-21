"""Remove events.pass_fees_to_buyer - the buyer-pays-checkout-fees model is
now mandatory for every event, not a per-event opt-in, so the toggle (and
the column backing it) no longer has a meaning. orders.fees_passed_to_buyer
is untouched - it's the per-order historical snapshot of what happened at
checkout time, still meaningful for orders placed before this change.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("events", "pass_fees_to_buyer")


def downgrade() -> None:
    op.add_column(
        "events",
        sa.Column("pass_fees_to_buyer", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
