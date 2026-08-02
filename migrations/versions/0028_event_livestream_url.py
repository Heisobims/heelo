"""Add livestream_url to events — a public stream URL (YouTube/Vimeo/HLS/
generic embed) shown on the event's live page, distinct from virtual_url
(the private join link only sent to confirmed registrants).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("livestream_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "livestream_url")
