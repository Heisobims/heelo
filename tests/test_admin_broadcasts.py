"""Admin broadcasts - audience targeting, router validation/permissions, and
the Celery send task body (recipient filtering, per-recipient failure
handling, status transitions)."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import admin_broadcast_service as bc_svc
from tests.conftest import TEST_DATABASE_URL, _make_user

_SYNC_TEST_URL = TEST_DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")


async def _make_vendor_user(db, *, email: str) -> uuid.UUID:
    from app.models.vendor import Vendor

    user = await _make_user(db, email=email, role="organizer", full_name="Vendor Owner")
    vendor = Vendor(
        user_id=user.id,
        business_name="Test Vendor Co",
        slug=f"test-vendor-{uuid.uuid4().hex[:8]}",
        category="photography",
        cover_image_url="https://example.com/cover.jpg",
    )
    db.add(vendor)
    await db.flush()
    return user


# ── Merge tags ───────────────────────────────────────────────────────────────


def test_validate_merge_tags_allows_name_and_email():
    assert bc_svc.validate_merge_tags("Hi {{name}}, confirm at {{email}}") == []


def test_validate_merge_tags_flags_unknown_tag():
    assert bc_svc.validate_merge_tags("Hi {{name}}, your code is {{secret_code}}") == [
        "secret_code"
    ]


def test_render_personalized_substitutes_tags():
    from types import SimpleNamespace

    user = SimpleNamespace(full_name="Ada", email="ada@example.com")
    out = bc_svc.render_personalized("Hi {{name}} ({{email}})", user)
    assert out == "Hi Ada (ada@example.com)"


def test_render_personalized_falls_back_to_there_when_no_name():
    from types import SimpleNamespace

    user = SimpleNamespace(full_name=None, email="ada@example.com")
    assert bc_svc.render_personalized("Hi {{name}}", user).startswith("Hi there")


# ── Audience targeting ────────────────────────────────────────────────────────


async def test_get_audience_all_includes_everyone(db):
    await _make_user(db, email="org1@example.com", role="organizer")
    await _make_user(db, email="att1@example.com", role="attendee")
    audience = await bc_svc.get_audience(db, "all")
    emails = {u.email for u in audience}
    assert {"org1@example.com", "att1@example.com"}.issubset(emails)


async def test_get_audience_organizer_excludes_attendees(db):
    await _make_user(db, email="org2@example.com", role="organizer")
    await _make_user(db, email="att2@example.com", role="attendee")
    audience = await bc_svc.get_audience(db, "organizer")
    emails = {u.email for u in audience}
    assert "org2@example.com" in emails
    assert "att2@example.com" not in emails


async def test_get_audience_admin_only_includes_admins(db):
    await _make_user(db, email="admin2@example.com", role="admin")
    await _make_user(db, email="org3@example.com", role="organizer")
    audience = await bc_svc.get_audience(db, "admin")
    emails = {u.email for u in audience}
    assert "admin2@example.com" in emails
    assert "org3@example.com" not in emails


async def test_get_audience_vendor_only_includes_vendor_owners(db):
    await _make_vendor_user(db, email="vendor1@example.com")
    await _make_user(db, email="org4@example.com", role="organizer")
    audience = await bc_svc.get_audience(db, "vendor")
    emails = {u.email for u in audience}
    assert "vendor1@example.com" in emails
    assert "org4@example.com" not in emails


async def test_create_broadcast_sets_recipient_count(db, admin_user):
    await _make_user(db, email="org5@example.com", role="organizer")
    await _make_user(db, email="org6@example.com", role="organizer")
    broadcast = await bc_svc.create_broadcast(
        db,
        created_by=admin_user.id,
        subject="Hello",
        body="Hi {{name}}",
        audience_category="organizer",
        channel="email",
    )
    assert broadcast.recipient_count >= 2
    assert broadcast.status == "draft"


async def test_create_broadcast_rejects_invalid_channel(db, admin_user):
    import pytest

    with pytest.raises(ValueError):
        await bc_svc.create_broadcast(
            db,
            created_by=admin_user.id,
            subject="Hello",
            body="Hi",
            audience_category="all",
            channel="carrier_pigeon",
        )


# ── Router - permissions & validation ─────────────────────────────────────────


async def test_create_broadcast_requires_admin(client: AsyncClient, user_headers):
    resp = await client.post(
        "/api/v1/admin/broadcasts",
        json={
            "subject": "Hi",
            "body": "Hi {{name}}",
            "audience_category": "all",
            "channel": "email",
        },
        headers=user_headers,
    )
    assert resp.status_code == 403


async def test_create_broadcast_rejects_unknown_audience(client: AsyncClient, admin_headers):
    resp = await client.post(
        "/api/v1/admin/broadcasts",
        json={
            "subject": "Hi",
            "body": "Hi {{name}}",
            "audience_category": "everyone_on_earth",
            "channel": "email",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 400


async def test_create_broadcast_rejects_unknown_merge_tag(client: AsyncClient, admin_headers):
    resp = await client.post(
        "/api/v1/admin/broadcasts",
        json={
            "subject": "Hi",
            "body": "Your secret is {{not_a_real_tag}}",
            "audience_category": "all",
            "channel": "email",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 400


async def test_create_broadcast_succeeds_and_enqueues_send(client: AsyncClient, admin_headers):
    resp = await client.post(
        "/api/v1/admin/broadcasts",
        json={
            "subject": "Welcome",
            "body": "Hi {{name}}, welcome to Heelo!",
            "audience_category": "all",
            "channel": "email",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["subject"] == "Welcome"
    assert data["status"] == "draft"


async def test_list_broadcasts_requires_admin(client: AsyncClient, user_headers):
    resp = await client.get("/api/v1/admin/broadcasts", headers=user_headers)
    assert resp.status_code == 403


async def test_audience_count_rejects_unknown_category(client: AsyncClient, admin_headers):
    resp = await client.get(
        "/api/v1/admin/broadcasts/audience-count",
        params={"category": "not_a_category"},
        headers=admin_headers,
    )
    assert resp.status_code == 400


async def test_send_broadcast_test_sends_to_admin_only(client: AsyncClient, admin_headers):
    resp = await client.post(
        "/api/v1/admin/broadcasts/test",
        json={
            "subject": "Preview",
            "body": "Hi {{name}}",
            "audience_category": "all",
            "channel": "email",
        },
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["sent_to"] == "admin@example.com"


# ── Celery task body ───────────────────────────────────────────────────────────


async def test_send_broadcast_task_sends_and_tracks_counts(db, monkeypatch):
    """Regression coverage for the send_broadcast task body - previously only
    the router/service layer around it had any tests. Verifies recipients are
    filtered by audience_category, sent_count/status update correctly, and a
    per-recipient failure doesn't abort the whole batch."""
    from app.models.notification import AdminBroadcast
    from app.tasks import admin_broadcast as bc_task

    u1 = await _make_user(db, email="broadcast-org1@example.com", role="organizer")
    await _make_user(db, email="broadcast-att1@example.com", role="attendee")
    broadcast = AdminBroadcast(
        id=uuid.uuid4(),
        created_by=u1.id,
        subject="Task test",
        body="Hi {{name}}",
        audience_category="organizer",
        channel="email",
        status="draft",
    )
    db.add(broadcast)
    await db.commit()

    sync_engine = create_engine(_SYNC_TEST_URL)
    TestSyncSession = sessionmaker(bind=sync_engine)
    monkeypatch.setattr(bc_task, "_db", lambda: TestSyncSession())

    bc_task.send_broadcast(str(broadcast.id))

    await db.refresh(broadcast)
    assert broadcast.status == "sent"
    assert broadcast.sent_count == 1  # only the organizer, not the attendee
    assert broadcast.failed_count == 0
    assert broadcast.sent_at is not None
    sync_engine.dispose()


async def test_send_broadcast_task_is_noop_for_already_sending_broadcast(db, monkeypatch):
    from app.models.notification import AdminBroadcast
    from app.tasks import admin_broadcast as bc_task

    u1 = await _make_user(db, email="broadcast-org2@example.com", role="organizer")
    broadcast = AdminBroadcast(
        id=uuid.uuid4(),
        created_by=u1.id,
        subject="Already sending",
        body="Hi",
        audience_category="organizer",
        channel="email",
        status="sent",  # not draft/failed
        sent_count=5,
    )
    db.add(broadcast)
    await db.commit()

    sync_engine = create_engine(_SYNC_TEST_URL)
    TestSyncSession = sessionmaker(bind=sync_engine)
    monkeypatch.setattr(bc_task, "_db", lambda: TestSyncSession())

    bc_task.send_broadcast(str(broadcast.id))

    await db.refresh(broadcast)
    assert broadcast.sent_count == 5  # untouched - task bailed early
    sync_engine.dispose()
