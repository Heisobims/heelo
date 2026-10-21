"""Add attachment_url and attachment_name to vendor_quotations

Revision ID: 0044
Revises: 0043
Create Date: 2026-10-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vendor_quotations",
        sa.Column("attachment_url", sa.String(length=1000), nullable=True),
    )
    op.add_column(
        "vendor_quotations",
        sa.Column("attachment_name", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("vendor_quotations", "attachment_name")
    op.drop_column("vendor_quotations", "attachment_url")

