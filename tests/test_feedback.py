"""Post-event feedback — submission, idempotent resubmission, organizer summary."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def _make_started_event_registration(db: AsyncSession, org, *, status="confirmed"):
    """A published event that already started, with one registration — feedback can
    only be left once an event has actually begun, so the shared `event`/`published_event`
    fixtures (both scheduled 7 days in the future) don't work here."""
    from app.models.event import Event
    from app.models.ticketing import Registration, TicketType

    event = Event(
        org_id=org.id,
        title="Past Meetup",
        slug=f"past-meetup-{uuid.uuid4()}",
        status="live",
        format="in_person",
        venue_city="Lagos",
        start_datetime=datetime.now(UTC) - timedelta(hours=2),
        end_datetime=datetime.now(UTC) - timedelta(hours=1),
    )
    db.add(event)
    await db.flush()

    tt = TicketType(event_id=event.id, name="General", price=0.0, currency="NGN", quantity=None)
    db.add(tt)
    await db.flush()

    reg = Registration(
        event_id=event.id,
        ticket_type_id=tt.id,
        attendee_name="Ada Lovelace",
        attendee_email="ada@example.com",
        qr_code=f"test-qr-{uuid.uuid4()}",
        status=status,
    )
    db.add(reg)
    await db.flush()
    return event, reg


async def test_submit_feedback(client: AsyncClient, db, org):
    event, reg = await _make_started_event_registration(db, org)

    resp = await client.post(
        f"/api/v1/registrations/{reg.id}/feedback",
        json={"rating": 5, "comment": "Loved it!"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["rating"] == 5


async def test_resubmitting_feedback_updates_instead_of_duplicating(client: AsyncClient, db, org):
    event, reg = await _make_started_event_registration(db, org)

    await client.post(
        f"/api/v1/registrations/{reg.id}/feedback", json={"rating": 3, "comment": "It was OK"}
    )
    resp = await client.post(
        f"/api/v1/registrations/{reg.id}/feedback", json={"rating": 5, "comment": "Actually great"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["rating"] == 5

    from sqlalchemy import func, select

    from app.models.feedback import EventFeedback

    count = await db.scalar(
        select(func.count(EventFeedback.id)).where(EventFeedback.registration_id == reg.id)
    )
    assert count == 1


async def test_feedback_rejected_before_event_starts(
    client: AsyncClient, published_event, registration
):
    # `registration`/`published_event` start 7 days from now.
    resp = await client.post(
        f"/api/v1/registrations/{registration.id}/feedback",
        json={"rating": 4},
    )
    assert resp.status_code == 400


async def test_feedback_rejected_for_cancelled_registration(client: AsyncClient, db, org):
    event, reg = await _make_started_event_registration(db, org, status="cancelled")

    resp = await client.post(
        f"/api/v1/registrations/{reg.id}/feedback",
        json={"rating": 4},
    )
    assert resp.status_code == 400


async def test_feedback_rating_must_be_in_range(client: AsyncClient, db, org):
    event, reg = await _make_started_event_registration(db, org)

    resp = await client.post(f"/api/v1/registrations/{reg.id}/feedback", json={"rating": 6})
    assert resp.status_code == 422


async def test_organizer_feedback_summary(client: AsyncClient, db, org, user_headers):
    event, reg = await _make_started_event_registration(db, org)

    await client.post(
        f"/api/v1/registrations/{reg.id}/feedback",
        json={"rating": 4, "comment": "Great vibes"},
    )

    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/feedback", headers=user_headers
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["average_rating"] == 4.0
    assert data["count"] == 1
    assert data["recent"][0]["comment"] == "Great vibes"
    assert data["recent"][0]["attendee_name"] == "Ada Lovelace"


async def test_organizer_feedback_summary_requires_membership(
    client: AsyncClient, db, org, other_headers
):
    event, _reg = await _make_started_event_registration(db, org)

    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/feedback", headers=other_headers
    )
    assert resp.status_code == 403
