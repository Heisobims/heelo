"""org_members: nullable user_id and invited_email column

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the existing non-partial unique constraint on (org_id, user_id)
    op.drop_constraint("uq_org_member", "organization_members", type_="unique")

    # Allow user_id to be NULL for pending invites of unregistered users
    op.alter_column("organization_members", "user_id", nullable=True)

    # Add invited_email column - stores the email the invite was sent to
    op.add_column(
        "organization_members",
        sa.Column("invited_email", sa.String(255), nullable=True),
    )

    # Partial unique index: only enforce uniqueness when user_id is known
    op.execute(
        """
        CREATE UNIQUE INDEX uq_org_member_user
        ON organization_members (org_id, user_id)
        WHERE user_id IS NOT NULL
        """
    )

    # Separate partial index: one pending invite per email per org
    op.execute(
        """
        CREATE UNIQUE INDEX uq_org_member_email
        ON organization_members (org_id, invited_email)
        WHERE status = 'invite_pending' AND invited_email IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_org_member_email")
    op.execute("DROP INDEX IF EXISTS uq_org_member_user")
    op.drop_column("organization_members", "invited_email")
    op.alter_column("organization_members", "user_id", nullable=False)
    op.create_unique_constraint("uq_org_member", "organization_members", ["org_id", "user_id"])
