"""Add missing foreign key indexes identified in system audit:
- ix_ticket_types_event_id
- ix_waitlists_event_id
- ix_waitlists_ticket_type_id
- ix_webhook_deliveries_subscription_id
- ix_whatsapp_messages_org_id
"""

from __future__ import annotations

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use if_not_exists pattern safe for Postgres
    op.execute("CREATE INDEX IF NOT EXISTS ix_ticket_types_event_id ON ticket_types (event_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_waitlists_event_id ON waitlists (event_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_waitlists_ticket_type_id ON waitlists (ticket_type_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_subscription_id ON webhook_deliveries (subscription_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_whatsapp_messages_org_id ON whatsapp_messages (org_id);")


def downgrade() -> None:
    op.drop_index("ix_whatsapp_messages_org_id", table_name="whatsapp_messages", if_exists=True)
    op.drop_index("ix_webhook_deliveries_subscription_id", table_name="webhook_deliveries", if_exists=True)
    op.drop_index("ix_waitlists_ticket_type_id", table_name="waitlists", if_exists=True)
    op.drop_index("ix_waitlists_event_id", table_name="waitlists", if_exists=True)
    op.drop_index("ix_ticket_types_event_id", table_name="ticket_types", if_exists=True)

