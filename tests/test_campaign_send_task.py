"""Campaign send task body (app/tasks/campaign.py) - per-recipient delivery,
failure handling, and status transitions. The router/CRUD layer already has
coverage in test_campaigns.py; this exercises the actual Celery task body
that does the sending, which was previously untested."""

from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import email_service as em
from app.services import whatsapp_service as wa
from tests.conftest import TEST_DATABASE_URL

_SYNC_TEST_URL = TEST_DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")


def _patch_sync_db(monkeypatch, campaign_tasks):
    sync_engine = create_engine(_SYNC_TEST_URL)
    TestSyncSession = sessionmaker(bind=sync_engine, expire_on_commit=False)
    monkeypatch.setattr(campaign_tasks, "_get_session", lambda: TestSyncSession())
    return sync_engine


async def _make_campaign(db, org, published_event, *, type="email"):
    from app.models.campaign import Campaign

    c = Campaign(
        org_id=org.id,
        event_id=published_event.id,
        type=type,
        name="Test Campaign",
        subject="Hello {{name}}",
        body="See you at {{event_name}}!",
        status="sending",
    )
    db.add(c)
    await db.flush()
    return c


async def _add_recipient(db, campaign, *, email=None, whatsapp_number=None, name="Attendee"):
    from app.models.campaign import CampaignRecipient

    rec = CampaignRecipient(
        campaign_id=campaign.id,
        email=email,
        whatsapp_number=whatsapp_number,
        phone=whatsapp_number,
        name=name,
        status="pending",
    )
    db.add(rec)
    await db.flush()
    return rec


async def test_send_campaign_email_marks_recipients_sent(db, org, published_event, monkeypatch):
    from app.tasks import campaign as campaign_tasks

    engine = _patch_sync_db(monkeypatch, campaign_tasks)
    campaign = await _make_campaign(db, org, published_event, type="email")
    rec = await _add_recipient(db, campaign, email="fan@example.com")
    await db.commit()

    sent_calls = []
    monkeypatch.setattr(em, "send_sync", lambda to, subject, html: sent_calls.append((to, subject)))

    campaign_tasks.send_campaign(str(campaign.id))

    await db.refresh(campaign)
    await db.refresh(rec)
    assert campaign.status == "sent"
    assert campaign.sent_count == 1
    assert campaign.failed_count == 0
    assert rec.status == "sent"
    assert rec.sent_at is not None
    assert sent_calls == [("fan@example.com", "Hello Attendee")]
    engine.dispose()


async def test_send_campaign_email_recipient_without_email_fails(
    db, org, published_event, monkeypatch
):
    from app.tasks import campaign as campaign_tasks

    engine = _patch_sync_db(monkeypatch, campaign_tasks)
    campaign = await _make_campaign(db, org, published_event, type="email")
    rec = await _add_recipient(db, campaign, email=None)
    await db.commit()

    campaign_tasks.send_campaign(str(campaign.id))

    await db.refresh(campaign)
    await db.refresh(rec)
    assert campaign.status == "failed"  # sent == 0
    assert campaign.failed_count == 1
    assert rec.status == "failed"
    assert rec.error_message == "No email address"
    engine.dispose()


async def test_send_campaign_email_provider_error_marks_recipient_failed(
    db, org, published_event, monkeypatch
):
    from app.tasks import campaign as campaign_tasks

    engine = _patch_sync_db(monkeypatch, campaign_tasks)
    campaign = await _make_campaign(db, org, published_event, type="email")
    ok_rec = await _add_recipient(db, campaign, email="ok@example.com", name="Ok")
    bad_rec = await _add_recipient(db, campaign, email="bad@example.com", name="Bad")
    await db.commit()

    def _send_sync(to, subject, html):
        if to == "bad@example.com":
            raise RuntimeError("SMTP rejected")

    monkeypatch.setattr(em, "send_sync", _send_sync)

    campaign_tasks.send_campaign(str(campaign.id))

    await db.refresh(campaign)
    await db.refresh(ok_rec)
    await db.refresh(bad_rec)
    assert campaign.sent_count == 1
    assert campaign.failed_count == 1
    assert campaign.status == "sent"  # at least one succeeded
    assert ok_rec.status == "sent"
    assert bad_rec.status == "failed"
    assert "SMTP rejected" in bad_rec.error_message
    engine.dispose()


async def test_send_campaign_whatsapp_marks_recipients_sent(db, org, published_event, monkeypatch):
    from app.tasks import campaign as campaign_tasks

    engine = _patch_sync_db(monkeypatch, campaign_tasks)
    campaign = await _make_campaign(db, org, published_event, type="whatsapp")
    rec = await _add_recipient(db, campaign, whatsapp_number="+2348012345678")
    await db.commit()

    sent_calls = []
    monkeypatch.setattr(wa, "send_text_sync", lambda to, body: sent_calls.append((to, body)))

    campaign_tasks.send_campaign(str(campaign.id))

    await db.refresh(campaign)
    await db.refresh(rec)
    assert campaign.status == "sent"
    assert rec.status == "sent"
    assert len(sent_calls) == 1
    engine.dispose()


async def test_send_campaign_sms_marks_recipients_sent(
    db, org, published_event, monkeypatch
):
    from app.tasks import campaign as campaign_tasks
    import app.utils.sms as sms_util

    sms_calls = []
    monkeypatch.setattr(
        sms_util,
        "send_sms_sync",
        lambda phone, text: sms_calls.append((phone, text)) or {"provider": "termii", "message_id": "sms_123"},
    )

    engine = _patch_sync_db(monkeypatch, campaign_tasks)
    campaign = await _make_campaign(db, org, published_event, type="sms")
    rec = await _add_recipient(db, campaign, whatsapp_number="+2348012345678")
    await db.commit()

    campaign_tasks.send_campaign(str(campaign.id))

    await db.refresh(campaign)
    await db.refresh(rec)
    assert campaign.status == "sent"
    assert rec.status == "sent"
    assert rec.provider_message_id == "sms_123"
    assert len(sms_calls) == 1
    assert sms_calls[0][0] == "+2348012345678"
    engine.dispose()


async def test_send_campaign_unimplemented_channel_fails_all_recipients(
    db, org, published_event, monkeypatch
):
    from app.tasks import campaign as campaign_tasks

    engine = _patch_sync_db(monkeypatch, campaign_tasks)
    campaign = await _make_campaign(db, org, published_event, type="telepathy")
    rec = await _add_recipient(db, campaign, whatsapp_number="+2348012345678")
    await db.commit()

    campaign_tasks.send_campaign(str(campaign.id))

    await db.refresh(campaign)
    await db.refresh(rec)
    assert campaign.status == "failed"
    assert rec.status == "failed"
    assert "not yet implemented" in rec.error_message
    engine.dispose()


async def test_send_campaign_noop_for_missing_campaign(monkeypatch):
    from app.tasks import campaign as campaign_tasks

    engine = _patch_sync_db(monkeypatch, campaign_tasks)
    campaign_tasks.send_campaign(str(uuid.uuid4()))  # must not raise
    engine.dispose()
