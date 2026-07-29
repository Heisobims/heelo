"""vendors: add vendors and vendor_leads tables

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vendors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("business_name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False, unique=True),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("tagline", sa.String(255), nullable=True),
        sa.Column("location_city", sa.String(255), nullable=True),
        sa.Column("location_country", sa.String(2), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("contact_phone", sa.String(30), nullable=True),
        sa.Column("website_url", sa.Text, nullable=True),
        sa.Column("cover_image_url", sa.Text, nullable=True),
        sa.Column("portfolio_urls", postgresql.JSONB, nullable=True),
        sa.Column("price_range", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("lead_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_vendors_category", "vendors", ["category"])
    op.create_index("ix_vendors_status", "vendors", ["status"])
    op.create_index("ix_vendors_location", "vendors", ["location_city", "location_country"])

    op.create_table(
        "vendor_leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("requester_name", sa.String(255), nullable=False),
        sa.Column("requester_email", sa.String(255), nullable=False),
        sa.Column("event_name", sa.String(255), nullable=True),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_vendor_leads_vendor", "vendor_leads", ["vendor_id"])
    op.create_index("ix_vendor_leads_org", "vendor_leads", ["org_id"])


def downgrade() -> None:
    op.drop_table("vendor_leads")
    op.drop_table("vendors")
