"""Add optional country and birth_year to users, for audience insights/filtering.

Both are opt-in, user-set fields (not collected at signup) — added to power
admin audience insights and filtering by region/age bracket, without forcing
new required fields on the registration flow.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("country", sa.String(2), nullable=True))
    op.add_column("users", sa.Column("birth_year", sa.Integer(), nullable=True))
    op.create_index("ix_users_country", "users", ["country"])


def downgrade() -> None:
    op.drop_index("ix_users_country", table_name="users")
    op.drop_column("users", "birth_year")
    op.drop_column("users", "country")
