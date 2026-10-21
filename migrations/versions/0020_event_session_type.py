"""Add session_type to event_sessions - lets a session be categorized
(talk/panel/workshop/networking/break/ceremony) for the agenda builder UI,
matching what the old Event.extras.agenda blob already tracked per item.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "event_sessions",
        sa.Column("session_type", sa.String(30), nullable=False, server_default="talk"),
    )


def downgrade() -> None:
    op.drop_column("event_sessions", "session_type")
