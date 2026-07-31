"""Add org branding fields — contact email + social links, for campaign email footers.

Powers the branded broadcast-email footer (logo/name already existed;
this adds the missing contact/social info organizers want to show).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("contact_email", sa.String(255), nullable=True))
    op.add_column("organizations", sa.Column("instagram_url", sa.String(500), nullable=True))
    op.add_column("organizations", sa.Column("twitter_url", sa.String(500), nullable=True))
    op.add_column("organizations", sa.Column("facebook_url", sa.String(500), nullable=True))
    op.add_column("organizations", sa.Column("linkedin_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "linkedin_url")
    op.drop_column("organizations", "facebook_url")
    op.drop_column("organizations", "twitter_url")
    op.drop_column("organizations", "instagram_url")
    op.drop_column("organizations", "contact_email")
