"""Add brand_color to organizations - an optional hex accent color that
carries the org's branding into checkout and the public event page, on top
of the logo that already existed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("brand_color", sa.String(7), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "brand_color")
