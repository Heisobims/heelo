"""Add portfolio_link to vendors — an alternative to uploading portfolio_urls
images, letting a vendor link to work hosted elsewhere (Instagram, Behance,
a personal site, etc) instead.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vendors", sa.Column("portfolio_link", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("vendors", "portfolio_link")
