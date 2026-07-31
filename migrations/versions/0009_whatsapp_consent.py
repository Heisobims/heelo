"""Add whatsapp_consent to orders and registrations."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("whatsapp_consent", sa.Boolean, nullable=False, server_default="false"),
    )
    op.add_column(
        "registrations",
        sa.Column("whatsapp_consent", sa.Boolean, nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("registrations", "whatsapp_consent")
    op.drop_column("orders", "whatsapp_consent")
