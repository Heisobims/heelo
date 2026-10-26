"""Add Open Calls and Open Call Submissions schema.

Revision ID: 0049
Revises: 0048
Create Date: 2026-10-26
"""

from __future__ import annotations

from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Table: open_calls ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS open_calls (
            id UUID PRIMARY KEY,
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            title VARCHAR(255) NOT NULL,
            slug VARCHAR(255) NOT NULL,
            call_type VARCHAR(50) NOT NULL DEFAULT 'speaker',
            description TEXT NULL,
            guidelines TEXT NULL,
            perks TEXT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            start_date TIMESTAMP WITH TIME ZONE NULL,
            end_date TIMESTAMP WITH TIME ZONE NULL,
            custom_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
            auto_response_message TEXT NULL,
            max_submissions INTEGER NULL,
            allow_anonymous BOOLEAN NOT NULL DEFAULT TRUE,
            submission_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_open_calls_event_status ON open_calls (event_id, status);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_open_calls_org ON open_calls (org_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_open_calls_slug ON open_calls (slug);")

    # ── Table: open_call_submissions ──────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS open_call_submissions (
            id UUID PRIMARY KEY,
            call_id UUID NOT NULL REFERENCES open_calls(id) ON DELETE CASCADE,
            event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL,
            phone VARCHAR(50) NULL,
            organization_name VARCHAR(255) NULL,
            job_title VARCHAR(255) NULL,
            bio TEXT NULL,
            photo_url TEXT NULL,
            social_links JSONB NOT NULL DEFAULT '{}'::jsonb,
            title VARCHAR(500) NOT NULL,
            proposal_summary TEXT NOT NULL,
            details TEXT NULL,
            category_or_track VARCHAR(100) NULL,
            attachment_url TEXT NULL,
            custom_answers JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(30) NOT NULL DEFAULT 'submitted',
            rating INTEGER NULL,
            organizer_notes TEXT NULL,
            feedback_to_applicant TEXT NULL,
            reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
            reviewed_at TIMESTAMP WITH TIME ZONE NULL,
            promoted_to_speaker_id UUID REFERENCES speakers(id) ON DELETE SET NULL,
            promoted_to_sponsor_id UUID REFERENCES sponsors(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_open_call_submissions_call_status ON open_call_submissions (call_id, status);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_open_call_submissions_event ON open_call_submissions (event_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_open_call_submissions_org ON open_call_submissions (org_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_open_call_submissions_email ON open_call_submissions (email);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS open_call_submissions CASCADE;")
    op.execute("DROP TABLE IF EXISTS open_calls CASCADE;")

