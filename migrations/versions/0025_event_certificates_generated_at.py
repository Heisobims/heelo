"""Add certificates_generated_at to events - gates attendee certificate
downloads behind an explicit organizer action, per the same on-the-fly
generation pattern as badges/OG-images (nothing is stored, this is purely
an availability flag).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events", sa.Column("certificates_generated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("events", "certificates_generated_at")
