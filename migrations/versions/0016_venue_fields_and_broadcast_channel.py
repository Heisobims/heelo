"""Add venue-specific fields to vendors, and a delivery channel to admin broadcasts.

- vendors.address / vendors.capacity: "venue" is already a vendor category -
  these let hall/venue owners list guest capacity and a precise address,
  which the generic vendor fields didn't cover.
- admin_broadcasts.channel: lets a platform admin send an announcement as an
  email, an in-app notification, or both.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vendors", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("vendors", sa.Column("capacity", sa.Integer(), nullable=True))
    op.add_column(
        "admin_broadcasts",
        sa.Column("channel", sa.String(20), nullable=False, server_default="email"),
    )


def downgrade() -> None:
    op.drop_column("admin_broadcasts", "channel")
    op.drop_column("vendors", "capacity")
    op.drop_column("vendors", "address")
