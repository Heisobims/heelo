"""Add orders.auto_split_applied - tracks, per order, whether the
organizer's net_amount was actually paid out automatically at charge time
(a Paystack/Flutterwave subaccount split or a verified Stripe Connect
destination charge), vs. Heelo still holding it and owing the organizer a
manual payout. Needed because an org's payment-account configuration can
change after an order is placed, so it can't be inferred reliably from
current state - see app/services/payout_service.py.

Backfill is a best-effort historical approximation, not a perfect
reconstruction (accounts can have been added/removed since a given order
was placed): existing paid Paystack/Flutterwave orders are marked True only
if the org currently has a matching payment account on record - the
overwhelmingly common case, since accounts are rarely deleted. Every
historical Stripe order is correctly left False (Stripe had no split
capability before this migration, so those genuinely were never
auto-paid-out) and any order for an org with no matching account today is
also left False - the conservative direction, since that flags a possible
liability for a human to verify via the new payout admin flow rather than
silently hiding one.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("auto_split_applied", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        """
        UPDATE orders
        SET auto_split_applied = true
        WHERE payment_status IN ('paid', 'partially_refunded', 'refunded')
          AND payment_provider IN ('paystack', 'flutterwave')
          AND EXISTS (
              SELECT 1
              FROM payment_accounts pa
              JOIN events e ON e.id = orders.event_id
              WHERE pa.org_id = e.org_id
                AND pa.provider = orders.payment_provider
          )
        """
    )


def downgrade() -> None:
    op.drop_column("orders", "auto_split_applied")
