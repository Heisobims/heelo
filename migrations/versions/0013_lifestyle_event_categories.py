"""Add lifestyle/social event categories - weddings, nightlife, hangouts, concerts.

The existing taxonomy skewed toward professional/conference events (Technology,
Business, Networking...). Tixdoo is meant to host any kind of event, so this
rounds out the category list with the social/lifestyle side: weddings, night
clubs, casual hangouts, concerts, and church/religious services (the latter
folds into the existing "Faith & Spirituality" category rather than
duplicating it).
"""

from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO event_categories (id, name, slug, icon, sort_order) VALUES
        (uuid_generate_v4(), 'Weddings & Celebrations', 'weddings-celebrations', 'favorite', 15),
        (uuid_generate_v4(), 'Nightlife & Parties', 'nightlife-parties', 'nightlife', 16),
        (uuid_generate_v4(), 'Hangouts & Meetups', 'hangouts-meetups', 'groups', 17),
        (uuid_generate_v4(), 'Concerts & Live Shows', 'concerts-live-shows', 'mic', 18)
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM event_categories
        WHERE slug IN (
            'weddings-celebrations', 'nightlife-parties', 'hangouts-meetups', 'concerts-live-shows'
        )
    """)
