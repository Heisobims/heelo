"""Initial schema — all Heelo tables

Revision ID: 0001
Revises:
Create Date: 2026-06-29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Extensions ────────────────────────────────────────────────────────────
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')

    # ── users ─────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("avatar_url", sa.Text, nullable=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="attendee"),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("oauth_provider", sa.String(50), nullable=True),
        sa.Column("oauth_id", sa.String(255), nullable=True),
        sa.Column("whatsapp_number", sa.String(30), nullable=True),
        sa.Column("whatsapp_opted_in", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("username", sa.String(50), nullable=True),
        sa.Column("onboarding_completed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True, postgresql_where=sa.text("username IS NOT NULL"))
    op.create_index("ix_users_email_deleted", "users", ["email", "deleted_at"])
    op.create_index("ix_users_oauth", "users", ["oauth_provider", "oauth_id"])

    # ── otp_codes ─────────────────────────────────────────────────────────────
    op.create_table(
        "otp_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("code_hash", sa.String(255), nullable=False),
        sa.Column("purpose", sa.String(50), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_otp_codes_email", "otp_codes", ["email"])
    op.create_index("ix_otp_email_purpose", "otp_codes", ["email", "purpose"])

    # ── password_reset_tokens ─────────────────────────────────────────────────
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_password_reset_tokens_user", "password_reset_tokens", ["user_id"])
    op.create_index("ix_password_reset_tokens_hash", "password_reset_tokens", ["token_hash"])

    # ── refresh_tokens ────────────────────────────────────────────────────────
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("device_info", sa.String(255), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_refresh_tokens_hash", "refresh_tokens", ["token_hash"], unique=True)
    op.create_index("ix_refresh_tokens_user_revoked", "refresh_tokens", ["user_id", "revoked_at"])

    # ── organizations ─────────────────────────────────────────────────────────
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("logo_url", sa.Text, nullable=True),
        sa.Column("cover_url", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("country", sa.String(2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("custom_domain", sa.String(255), nullable=True),
        sa.Column("custom_domain_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("plan", sa.String(20), nullable=False, server_default="starter"),
        sa.Column("plan_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)
    op.create_index("ix_organizations_owner", "organizations", ["owner_id"])
    op.create_index("ix_organizations_custom_domain", "organizations", ["custom_domain"], unique=True, postgresql_where=sa.text("custom_domain IS NOT NULL"))

    # ── organization_members ──────────────────────────────────────────────────
    op.create_table(
        "organization_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(30), nullable=False, server_default="organizer"),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="invite_pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("org_id", "user_id", name="uq_org_member"),
    )
    op.create_index("ix_org_members_org", "organization_members", ["org_id"])
    op.create_index("ix_org_members_user", "organization_members", ["user_id"])

    # ── event_categories ──────────────────────────────────────────────────────
    op.create_table(
        "event_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("icon", sa.String(100), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("name", name="uq_event_category_name"),
        sa.UniqueConstraint("slug", name="uq_event_category_slug"),
    )

    # ── events ────────────────────────────────────────────────────────────────
    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("cover_image_url", sa.Text, nullable=True),
        sa.Column("og_image_url", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("format", sa.String(20), nullable=False, server_default="in_person"),
        sa.Column("start_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False, server_default="UTC"),
        sa.Column("venue_name", sa.String(500), nullable=True),
        sa.Column("venue_address", sa.Text, nullable=True),
        sa.Column("venue_city", sa.String(255), nullable=True),
        sa.Column("venue_country", sa.String(2), nullable=True),
        sa.Column("venue_lat", sa.Float, nullable=True),
        sa.Column("venue_lng", sa.Float, nullable=True),
        sa.Column("virtual_url", sa.Text, nullable=True),
        sa.Column("virtual_platform", sa.String(50), nullable=True),
        sa.Column("max_capacity", sa.Integer, nullable=True),
        sa.Column("is_featured", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_private", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("password", sa.String(255), nullable=True),
        sa.Column("is_recurring", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("recurrence_rule", sa.String(100), nullable=True),
        sa.Column("recurrence_end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parent_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("cloned_from_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_template", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_events_slug", "events", ["slug"], unique=True)
    op.create_index("ix_events_org_status", "events", ["org_id", "status"])
    op.create_index("ix_events_start_datetime", "events", ["start_datetime"])
    op.create_index("ix_events_is_featured", "events", ["is_featured"])
    op.create_index("ix_events_status", "events", ["status"])
    # Full-text search index on title + description
    op.execute("""
        CREATE INDEX ix_events_fts ON events
        USING gin(to_tsvector('english', coalesce(title, '') || ' ' || coalesce(description, '')))
    """)

    # ── event_category_links (M2M) ────────────────────────────────────────────
    op.create_table(
        "event_category_links",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("event_categories.id", ondelete="CASCADE"), primary_key=True),
    )

    # ── event_sessions ────────────────────────────────────────────────────────
    op.create_table(
        "event_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("speaker_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=False)), nullable=False, server_default="{}"),
        sa.Column("start_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("location_or_stream_url", sa.Text, nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("track", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_event_sessions_event_start", "event_sessions", ["event_id", "start_datetime"])

    # ── speakers ──────────────────────────────────────────────────────────────
    op.create_table(
        "speakers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("company", sa.String(255), nullable=True),
        sa.Column("bio", sa.Text, nullable=True),
        sa.Column("photo_url", sa.Text, nullable=True),
        sa.Column("social_links", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("invite_email", sa.String(255), nullable=True),
        sa.Column("invite_token", sa.String(255), nullable=True),
        sa.Column("invite_accepted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_speakers_org", "speakers", ["org_id"])

    # ── sponsors ──────────────────────────────────────────────────────────────
    op.create_table(
        "sponsors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("logo_url", sa.Text, nullable=True),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("tier", sa.String(20), nullable=False, server_default="partner"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_sponsors_event", "sponsors", ["event_id"])

    # ── ticket_types ──────────────────────────────────────────────────────────
    op.create_table(
        "ticket_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("quantity", sa.Integer, nullable=True),
        sa.Column("quantity_sold", sa.Integer, nullable=False, server_default="0"),
        sa.Column("quantity_reserved", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tier", sa.String(20), nullable=False, server_default="general"),
        sa.Column("sale_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sale_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_visible", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("max_per_order", sa.Integer, nullable=False, server_default="10"),
        sa.Column("min_per_order", sa.Integer, nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ticket_types_event_visible", "ticket_types", ["event_id", "is_visible"])

    # ── registration_form_fields ──────────────────────────────────────────────
    op.create_table(
        "registration_form_fields",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(500), nullable=False),
        sa.Column("field_type", sa.String(30), nullable=False),
        sa.Column("is_required", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("options", postgresql.JSONB, nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("applies_to_ticket_type_ids", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_reg_form_fields_event", "registration_form_fields", ["event_id", "sort_order"])

    # ── promo_codes ───────────────────────────────────────────────────────────
    op.create_table(
        "promo_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("discount_type", sa.String(10), nullable=False),
        sa.Column("discount_value", sa.Numeric(12, 2), nullable=False),
        sa.Column("max_uses", sa.Integer, nullable=True),
        sa.Column("used_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("applicable_ticket_type_ids", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("event_id", "code", name="uq_promo_event_code"),
    )
    op.create_index("ix_promo_codes_event", "promo_codes", ["event_id"])

    # ── orders ────────────────────────────────────────────────────────────────
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("promo_code_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("promo_codes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("buyer_name", sa.String(255), nullable=True),
        sa.Column("buyer_email", sa.String(255), nullable=False),
        sa.Column("buyer_phone", sa.String(30), nullable=True),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("net_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("platform_fee", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("payment_provider", sa.String(30), nullable=True),
        sa.Column("payment_reference", sa.String(255), nullable=True),
        sa.Column("payment_status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("invoice_url", sa.Text, nullable=True),
        sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("utm_source", sa.String(255), nullable=True),
        sa.Column("utm_medium", sa.String(255), nullable=True),
        sa.Column("utm_campaign", sa.String(255), nullable=True),
        sa.Column("referral_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_orders_event_status", "orders", ["event_id", "payment_status"])
    op.create_index("ix_orders_user", "orders", ["user_id"])
    op.create_index("ix_orders_reference", "orders", ["payment_reference"], unique=True, postgresql_where=sa.text("payment_reference IS NOT NULL"))

    # ── order_items ───────────────────────────────────────────────────────────
    op.create_table(
        "order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticket_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ticket_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_order_items_order", "order_items", ["order_id"])

    # ── registrations ─────────────────────────────────────────────────────────
    op.create_table(
        "registrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ticket_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ticket_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("checked_in_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("transferred_from_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("registrations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("attendee_name", sa.String(255), nullable=False),
        sa.Column("attendee_email", sa.String(255), nullable=False),
        sa.Column("attendee_phone", sa.String(30), nullable=True),
        sa.Column("qr_code", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ticket_url", sa.Text, nullable=True),
        sa.Column("whatsapp_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transfer_token", sa.String(255), nullable=True),
        sa.Column("transfer_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_registrations_event_status", "registrations", ["event_id", "status"])
    op.create_index("ix_registrations_email", "registrations", ["attendee_email"])
    op.create_index("ix_registrations_qr", "registrations", ["qr_code"], unique=True)
    op.create_index("ix_registrations_user", "registrations", ["user_id"])

    # ── registration_answers ──────────────────────────────────────────────────
    op.create_table(
        "registration_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("registration_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("registrations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("registration_form_fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("value", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_registration_answers_reg", "registration_answers", ["registration_id"])

    # ── waitlists ─────────────────────────────────────────────────────────────
    op.create_table(
        "waitlists",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticket_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ticket_types.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("offer_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_waitlists_event_position", "waitlists", ["event_id", "position"])

    # ── checkins ──────────────────────────────────────────────────────────────
    op.create_table(
        "checkins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("registration_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("registrations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("event_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("scanned_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("method", sa.String(20), nullable=False, server_default="qr"),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_checkins_event_scanned", "checkins", ["event_id", "scanned_at"])
    op.create_index("ix_checkins_registration", "checkins", ["registration_id"])

    # ── campaigns ─────────────────────────────────────────────────────────────
    op.create_table(
        "campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recipient_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("delivered_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("open_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("click_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reply_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_campaigns_org_status", "campaigns", ["org_id", "status"])

    # ── campaign_recipients ───────────────────────────────────────────────────
    op.create_table(
        "campaign_recipients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("registration_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("registrations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("whatsapp_number", sa.String(30), nullable=True),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_campaign_recipients_campaign", "campaign_recipients", ["campaign_id"])
    op.create_index("ix_campaign_recipients_email", "campaign_recipients", ["email"])

    # ── attendee_profiles ─────────────────────────────────────────────────────
    op.create_table(
        "attendee_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("bio", sa.Text, nullable=True),
        sa.Column("headline", sa.String(255), nullable=True),
        sa.Column("linkedin_url", sa.String(500), nullable=True),
        sa.Column("twitter_url", sa.String(500), nullable=True),
        sa.Column("website_url", sa.String(500), nullable=True),
        sa.Column("interests", postgresql.ARRAY(sa.String(100)), nullable=False, server_default="{}"),
        sa.Column("is_visible_in_directory", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("events_attended_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_attendee_profiles_user", "attendee_profiles", ["user_id"])

    # ── connections ───────────────────────────────────────────────────────────
    op.create_table(
        "connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connected_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "connected_user_id", name="uq_connection_pair"),
    )
    op.create_index("ix_connections_user", "connections", ["user_id"])
    op.create_index("ix_connections_connected_user", "connections", ["connected_user_id"])

    # ── organizer_followers ───────────────────────────────────────────────────
    op.create_table(
        "organizer_followers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notify_new_events", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "org_id", name="uq_organizer_follower"),
    )
    op.create_index("ix_organizer_followers_org", "organizer_followers", ["org_id"])
    op.create_index("ix_organizer_followers_user", "organizer_followers", ["user_id"])

    # ── whatsapp_messages ─────────────────────────────────────────────────────
    op.create_table(
        "whatsapp_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_number", sa.String(30), nullable=False),
        sa.Column("to_number", sa.String(30), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("message_type", sa.String(20), nullable=False, server_default="text"),
        sa.Column("media_url", sa.Text, nullable=True),
        sa.Column("wa_message_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="sent"),
        sa.Column("is_read_by_org", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("ai_suggested_reply", sa.Text, nullable=True),
        sa.Column("sent_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_whatsapp_messages_org_thread", "whatsapp_messages", ["org_id", "from_number"])
    op.create_index("ix_whatsapp_messages_wa_id", "whatsapp_messages", ["wa_message_id"], unique=True, postgresql_where=sa.text("wa_message_id IS NOT NULL"))

    # ── notifications ─────────────────────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(60), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("action_url", sa.String(500), nullable=True),
        sa.Column("icon", sa.String(100), nullable=True),
        sa.Column("is_read", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_notifications_user_read", "notifications", ["user_id", "is_read"])
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"])

    # ── audit_logs ────────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(100), nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_logs_org_created", "audit_logs", ["org_id", "created_at"])
    op.create_index("ix_audit_logs_user_created", "audit_logs", ["user_id", "created_at"])
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])

    # ── payment_accounts ──────────────────────────────────────────────────────
    op.create_table(
        "payment_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("provider_account_id", sa.String(255), nullable=False),
        sa.Column("account_name", sa.String(255), nullable=True),
        sa.Column("bank_name", sa.String(255), nullable=True),
        sa.Column("account_number", sa.String(50), nullable=True),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("country", sa.String(2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("instant_settlement", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_payment_accounts_org", "payment_accounts", ["org_id"])

    # ── payouts ───────────────────────────────────────────────────────────────
    op.create_table(
        "payouts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payment_account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payment_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column("failure_reason", sa.Text, nullable=True),
        sa.Column("initiated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_payouts_org_status", "payouts", ["org_id", "status"])
    op.create_index("ix_payouts_event", "payouts", ["event_id"])

    # ── api_keys ──────────────────────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("key_prefix", sa.String(20), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_api_keys_org_active", "api_keys", ["org_id", "is_active"])
    op.create_index("ix_api_keys_hash", "api_keys", ["key_hash"], unique=True)

    # ── webhook_subscriptions ─────────────────────────────────────────────────
    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("events", postgresql.ARRAY(sa.String(100)), nullable=False),
        sa.Column("secret", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_webhook_subscriptions_org_active", "webhook_subscriptions", ["org_id", "is_active"])

    # ── webhook_deliveries ────────────────────────────────────────────────────
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("response_status", sa.Integer, nullable=True),
        sa.Column("response_body", sa.Text, nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_webhook_deliveries_subscription_created", "webhook_deliveries", ["subscription_id", "created_at"])
    op.create_index("ix_webhook_deliveries_next_retry", "webhook_deliveries", ["next_retry_at"])

    # ── Seed default event categories ─────────────────────────────────────────
    op.execute("""
        INSERT INTO event_categories (id, name, slug, icon, sort_order) VALUES
        (uuid_generate_v4(), 'Technology', 'technology', 'computer', 1),
        (uuid_generate_v4(), 'Business', 'business', 'briefcase', 2),
        (uuid_generate_v4(), 'Music', 'music', 'music', 3),
        (uuid_generate_v4(), 'Arts & Culture', 'arts-culture', 'palette', 4),
        (uuid_generate_v4(), 'Sports & Fitness', 'sports-fitness', 'trophy', 5),
        (uuid_generate_v4(), 'Food & Drink', 'food-drink', 'utensils', 6),
        (uuid_generate_v4(), 'Education', 'education', 'graduation-cap', 7),
        (uuid_generate_v4(), 'Health & Wellness', 'health-wellness', 'heart', 8),
        (uuid_generate_v4(), 'Networking', 'networking', 'users', 9),
        (uuid_generate_v4(), 'Startup & Innovation', 'startup-innovation', 'rocket', 10),
        (uuid_generate_v4(), 'Finance', 'finance', 'chart-bar', 11),
        (uuid_generate_v4(), 'Faith & Spirituality', 'faith-spirituality', 'star', 12),
        (uuid_generate_v4(), 'Community', 'community', 'home', 13),
        (uuid_generate_v4(), 'Government & Politics', 'government-politics', 'landmark', 14),
        (uuid_generate_v4(), 'Other', 'other', 'grid', 99)
        ON CONFLICT DO NOTHING
    """)

    # ── updated_at trigger function ───────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ language 'plpgsql'
    """)

    # Apply updated_at trigger to every table that has the column
    tables_with_updated_at = [
        "users", "otp_codes", "password_reset_tokens", "refresh_tokens",
        "organizations", "organization_members", "event_categories", "events",
        "event_sessions", "speakers", "sponsors", "ticket_types",
        "registration_form_fields", "promo_codes", "orders", "order_items",
        "registrations", "registration_answers", "waitlists", "checkins",
        "campaigns", "campaign_recipients", "attendee_profiles", "connections",
        "organizer_followers", "whatsapp_messages", "notifications", "audit_logs",
        "payment_accounts", "payouts", "api_keys", "webhook_subscriptions",
        "webhook_deliveries",
    ]
    for table in tables_with_updated_at:
        op.execute(f"""
            CREATE TRIGGER {table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
        """)


def downgrade() -> None:
    tables = [
        "webhook_deliveries", "webhook_subscriptions", "api_keys",
        "payouts", "payment_accounts",
        "audit_logs", "notifications", "whatsapp_messages",
        "organizer_followers", "connections", "attendee_profiles",
        "campaign_recipients", "campaigns",
        "checkins", "waitlists", "registration_answers", "registrations",
        "order_items", "orders", "promo_codes", "registration_form_fields",
        "ticket_types", "sponsors", "speakers",
        "event_category_links", "event_sessions", "events", "event_categories",
        "organization_members", "organizations",
        "refresh_tokens", "password_reset_tokens", "otp_codes", "users",
    ]
    for table in tables:
        op.drop_table(table)

    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column CASCADE")
    op.execute('DROP EXTENSION IF EXISTS "pg_trgm"')
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
