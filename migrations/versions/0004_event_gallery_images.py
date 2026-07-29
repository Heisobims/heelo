"""events: add gallery_1_url and gallery_2_url columns

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("events", sa.Column("gallery_1_url", sa.Text, nullable=True))
    op.add_column("events", sa.Column("gallery_2_url", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("events", "gallery_2_url")
    op.drop_column("events", "gallery_1_url")
