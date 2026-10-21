"""Add SSO domain-restriction columns to organizations - Enterprise orgs can
verify ownership of their email domain (same TXT-record ownership proof as
custom domains, at _heelo-sso-verify.{domain}) and then enforce that members
on that domain must sign in via Google Workspace SSO rather than a password.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("sso_domain", sa.String(length=255), nullable=True))
    op.create_unique_constraint("uq_organizations_sso_domain", "organizations", ["sso_domain"])
    op.add_column(
        "organizations",
        sa.Column("sso_domain_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "organizations",
        sa.Column("sso_verification_token", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "organizations",
        sa.Column("sso_enforced", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("organizations", "sso_enforced")
    op.drop_column("organizations", "sso_verification_token")
    op.drop_column("organizations", "sso_domain_verified")
    op.drop_constraint("uq_organizations_sso_domain", "organizations", type_="unique")
    op.drop_column("organizations", "sso_domain")
