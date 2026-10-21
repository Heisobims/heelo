"""Add referral_token to registrations - a public "refer a friend" code that
is deliberately NOT the registration's own id, since that id also acts as
the bare capability-token behind qr.png/badge.pdf/certificate.pdf. Sharing a
referral link previously leaked access to those.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("registrations", sa.Column("referral_token", sa.String(length=32), nullable=True))
    op.create_unique_constraint(
        "uq_registrations_referral_token", "registrations", ["referral_token"]
    )
    # Backfill existing rows so referral links/stats keep working immediately
    # after deploy, not just for registrations created from now on.
    op.execute(
        "UPDATE registrations SET referral_token = substr(md5(random()::text || id::text), 1, 16) "
        "WHERE referral_token IS NULL"
    )


def downgrade() -> None:
    op.drop_constraint("uq_registrations_referral_token", "registrations", type_="unique")
    op.drop_column("registrations", "referral_token")
