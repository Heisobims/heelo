"""Add direct_messages — attendee-to-attendee DMs, gated by an accepted
Connection. No separate conversation table; a thread is just every message
between two user ids, the same lightweight shape WhatsAppMessage already
uses for the organizer inbox (thread key = phone there, = other user id here).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "direct_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "sender_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recipient_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index("ix_direct_messages_sender", "direct_messages", ["sender_id"])
    op.create_index(
        "ix_direct_messages_recipient_read", "direct_messages", ["recipient_id", "is_read"]
    )


def downgrade() -> None:
    op.drop_index("ix_direct_messages_recipient_read", table_name="direct_messages")
    op.drop_index("ix_direct_messages_sender", table_name="direct_messages")
    op.drop_table("direct_messages")
