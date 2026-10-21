"""Rename the "starter" plan value to "free" on organizations.plan.

The tier is being formalized as part of the Free/Growth/Pro/Enterprise
monetization structure - "Starter" implied a paid entry tier, which
undersells that it's free forever by design.
"""

from __future__ import annotations

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE organizations SET plan = 'free' WHERE plan = 'starter'")


def downgrade() -> None:
    op.execute("UPDATE organizations SET plan = 'starter' WHERE plan = 'free'")
