"""Add section_order to events — lets an organizer reorder and show/hide the
public event page's content sections (About, Agenda, People, Partners,
Gallery, Discussion) via drag-and-drop. Deliberately scoped to reordering
existing sections rather than a full block-based page composer — see the
build-order discussion; a block composer stays a possible future upgrade.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("section_order", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("events", "section_order")
