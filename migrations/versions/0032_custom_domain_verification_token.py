"""Add custom_domain_verification_token to organizations - the expected TXT
record value an organizer must publish at _tixdoo-verify.{domain} to prove
ownership before their custom domain goes live (Pro+ feature).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("custom_domain_verification_token", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "custom_domain_verification_token")
