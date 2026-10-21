"""Add event vibe tags and event_interests table.

Note: `connections` already exists (migrated in 0001_initial_schema) - the model
just has no API/router wired up yet. Nothing to migrate there.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "vibe_tags", ARRAY(sa.String(50)), nullable=False, server_default="{}"
        ),
    )

    op.create_table(
        "event_interests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("user_id", "event_id", name="uq_event_interest_user_event"),
    )
    op.create_index("ix_event_interests_event", "event_interests", ["event_id"])
    op.create_index("ix_event_interests_user", "event_interests", ["user_id"])

    # notifications.metadata already exists (0001_initial_schema) - reused as-is for
    # connection_request rows, no schema change needed there.


def downgrade() -> None:
    op.drop_table("event_interests")
    op.drop_column("events", "vibe_tags")
