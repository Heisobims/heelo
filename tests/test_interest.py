"""Save-and-remind ('interested') - lightweight non-binary RSVP short of buying a ticket."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import interest_service as int_svc


async def test_mark_interested_is_idempotent(db: AsyncSession, user, published_event):
    await int_svc.mark_interested(db, user.id, published_event.id)
    await int_svc.mark_interested(db, user.id, published_event.id)  # should not raise or duplicate

    assert await int_svc.is_interested(db, user.id, published_event.id) is True
    assert await int_svc.get_interest_count(db, published_event.id) == 1


async def test_unmark_interested(db: AsyncSession, user, published_event):
    await int_svc.mark_interested(db, user.id, published_event.id)
    await int_svc.unmark_interested(db, user.id, published_event.id)

    assert await int_svc.is_interested(db, user.id, published_event.id) is False


async def test_unmark_interested_when_never_marked_is_a_noop(
    db: AsyncSession, user, published_event
):
    await int_svc.unmark_interested(db, user.id, published_event.id)  # should not raise
    assert await int_svc.is_interested(db, user.id, published_event.id) is False


async def test_interested_event_ids_for_user_batches_correctly(db: AsyncSession, user, org):
    from datetime import UTC, datetime, timedelta

    from app.models.event import Event

    now = datetime.now(UTC)
    e1 = Event(
        org_id=org.id,
        title="E1",
        slug="interest-e1",
        status="published",
        format="in_person",
        start_datetime=now + timedelta(days=1),
        end_datetime=now + timedelta(days=1, hours=2),
    )
    e2 = Event(
        org_id=org.id,
        title="E2",
        slug="interest-e2",
        status="published",
        format="in_person",
        start_datetime=now + timedelta(days=2),
        end_datetime=now + timedelta(days=2, hours=2),
    )
    db.add_all([e1, e2])
    await db.flush()

    await int_svc.mark_interested(db, user.id, e1.id)

    ids = await int_svc.interested_event_ids_for_user(db, user.id, [e1.id, e2.id])
    assert ids == {e1.id}


async def test_mark_interested_endpoint(client: AsyncClient, published_event, user_headers):
    resp = await client.post(
        f"/api/v1/events/{published_event.slug}/interested", headers=user_headers
    )
    assert resp.status_code == 204


async def test_mark_interested_requires_auth(client: AsyncClient, published_event):
    resp = await client.post(f"/api/v1/events/{published_event.slug}/interested")
    assert resp.status_code == 401


async def test_unmark_interested_endpoint(client: AsyncClient, published_event, user_headers):
    await client.post(f"/api/v1/events/{published_event.slug}/interested", headers=user_headers)
    resp = await client.delete(
        f"/api/v1/events/{published_event.slug}/interested", headers=user_headers
    )
    assert resp.status_code == 204


async def test_interested_on_nonexistent_event_returns_404(client: AsyncClient, user_headers):
    resp = await client.post("/api/v1/events/does-not-exist/interested", headers=user_headers)
    assert resp.status_code == 404
