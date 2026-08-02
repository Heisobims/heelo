"""Extend sponsors for the self-service sponsor portal (real user account,
not a token-only invite) and for exhibitor management, which reuses the
Sponsor model rather than a separate table (booth_number/category/
is_exhibitor distinguish a trade-show-style exhibitor from a financial
sponsor on the same event).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sponsors",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("sponsors", sa.Column("contact_email", sa.String(255), nullable=True))
    op.add_column(
        "sponsors",
        sa.Column("invite_accepted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("sponsors", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("sponsors", sa.Column("booth_number", sa.String(50), nullable=True))
    op.add_column("sponsors", sa.Column("category", sa.String(100), nullable=True))
    op.add_column(
        "sponsors",
        sa.Column("is_exhibitor", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_sponsors_user", "sponsors", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_sponsors_user", table_name="sponsors")
    op.drop_column("sponsors", "is_exhibitor")
    op.drop_column("sponsors", "category")
    op.drop_column("sponsors", "booth_number")
    op.drop_column("sponsors", "description")
    op.drop_column("sponsors", "invite_accepted")
    op.drop_column("sponsors", "contact_email")
    op.drop_column("sponsors", "user_id")
