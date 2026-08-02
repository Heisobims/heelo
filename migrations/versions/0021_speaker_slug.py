"""Add slug to speakers — needed for public speaker profile pages
(GET /speakers/{slug}), now that Speaker is a real, reusable-across-events
record instead of an inline JSON blob entry.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("speakers", sa.Column("slug", sa.String(255), nullable=False, server_default=""))
    op.alter_column("speakers", "slug", server_default=None)
    op.create_index("ix_speakers_slug", "speakers", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_speakers_slug", table_name="speakers")
    op.drop_column("speakers", "slug")
