"""Add event_speakers join table — links a reusable org-level Speaker to a
specific event with a role (speaker/panelist/moderator/judge/organizer) and a
display sort order. Lets an event's "People" roster live in the real
`speakers` table instead of the Event.extras.people JSON blob.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_speakers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "speaker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("speakers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role_type", sa.String(20), nullable=False, server_default="speaker"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index(
        "ix_event_speakers_event_sort", "event_speakers", ["event_id", "sort_order"]
    )
    op.create_index("ix_event_speakers_speaker", "event_speakers", ["speaker_id"])


def downgrade() -> None:
    op.drop_index("ix_event_speakers_speaker", table_name="event_speakers")
    op.drop_index("ix_event_speakers_event_sort", table_name="event_speakers")
    op.drop_table("event_speakers")
