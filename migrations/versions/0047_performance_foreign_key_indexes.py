"""Add missing foreign key indexes on high-traffic tables.

Revision ID: 0047
Revises: 0046
Create Date: 2026-10-24
"""

from __future__ import annotations

from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_registrations_order_id ON registrations (order_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_registrations_ticket_type_id ON registrations (ticket_type_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_campaign_recipients_registration_id ON campaign_recipients (registration_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_campaigns_event_id ON campaigns (event_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vendor_quotations_quote_request_id ON vendor_quotations (quote_request_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vendor_transactions_booking_id ON vendor_transactions (booking_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_orders_promo_code_id ON orders (promo_code_id);")


def downgrade() -> None:
    op.drop_index("ix_orders_promo_code_id", table_name="orders", if_exists=True)
    op.drop_index("ix_vendor_transactions_booking_id", table_name="vendor_transactions", if_exists=True)
    op.drop_index("ix_vendor_quotations_quote_request_id", table_name="vendor_quotations", if_exists=True)
    op.drop_index("ix_campaigns_event_id", table_name="campaigns", if_exists=True)
    op.drop_index("ix_campaign_recipients_registration_id", table_name="campaign_recipients", if_exists=True)
    op.drop_index("ix_registrations_ticket_type_id", table_name="registrations", if_exists=True)
    op.drop_index("ix_registrations_order_id", table_name="registrations", if_exists=True)

