"""Add optional phone to waitlists.

The WhatsApp waitlist-notification task was passing the entrant's *email*
into a phone-number parameter (format_phone() on an email always fails and
the send silently no-ops), because Waitlist never actually captured a phone
number. This adds the column so the join form can collect one and the
WhatsApp notification can actually be sent.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("waitlists", sa.Column("phone", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("waitlists", "phone")
