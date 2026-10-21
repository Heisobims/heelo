"""Add additional foreign key indexes for marketplace, orders, affiliates and booths.

Revision ID: 0045
Revises: 0044
Create Date: 2026-10-21
"""

from __future__ import annotations

from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_vendors_user_id ON vendors (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vendor_bookings_org_id ON vendor_bookings (org_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vendor_bookings_event_id ON vendor_bookings (event_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vendor_quote_requests_org_id ON vendor_quote_requests (org_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_order_items_ticket_type_id ON order_items (ticket_type_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_event_affiliates_user_id ON event_affiliates (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_booth_applications_package_id ON booth_applications (package_id);")


def downgrade() -> None:
    op.drop_index("ix_booth_applications_package_id", table_name="booth_applications", if_exists=True)
    op.drop_index("ix_event_affiliates_user_id", table_name="event_affiliates", if_exists=True)
    op.drop_index("ix_order_items_ticket_type_id", table_name="order_items", if_exists=True)
    op.drop_index("ix_vendor_quote_requests_org_id", table_name="vendor_quote_requests", if_exists=True)
    op.drop_index("ix_vendor_bookings_event_id", table_name="vendor_bookings", if_exists=True)
    op.drop_index("ix_vendor_bookings_org_id", table_name="vendor_bookings", if_exists=True)
    op.drop_index("ix_vendors_user_id", table_name="vendors", if_exists=True)

