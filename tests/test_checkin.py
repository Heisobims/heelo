"""Check-in - QR token, manual, undo, stats."""

from __future__ import annotations

import uuid

from httpx import AsyncClient


async def test_check_in_by_registration_id(
    client: AsyncClient, org, published_event, registration, user_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
        json={"registration_id": str(registration.id)},
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "checked_in"


async def test_check_in_already_checked_in_returns_409(
    client: AsyncClient, org, published_event, registration, user_headers
):
    # First check-in
    await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
        json={"registration_id": str(registration.id)},
        headers=user_headers,
    )
    # Second check-in - should be 409
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
        json={"registration_id": str(registration.id)},
        headers=user_headers,
    )
    assert resp.status_code == 409


async def test_check_in_nonexistent_registration(
    client: AsyncClient, org, published_event, user_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
        json={"registration_id": str(uuid.uuid4())},
        headers=user_headers,
    )
    assert resp.status_code == 404


async def test_check_in_by_id_rejects_registration_from_a_different_event(
    client: AsyncClient, db, org, published_event, user_headers, other_user
):
    """Regression test: check_in_by_id() used to look up a registration by id
    alone, with no event_id filter - a checkin_staff member of one event
    could check in (and see the name/email of) a registration belonging to a
    completely different org's event by simply passing its id."""
    from app.models.event import Event
    from app.models.organization import Organization
    from app.models.ticketing import Registration, TicketType

    other_org = Organization(
        owner_id=other_user.id, name="Other Org", slug="other-org", plan="free", currency="NGN"
    )
    db.add(other_org)
    await db.flush()

    from datetime import UTC, datetime, timedelta

    other_event = Event(
        org_id=other_org.id,
        title="Other Org's Event",
        slug="other-orgs-event",
        status="published",
        format="in_person",
        venue_city="Nairobi",
        start_datetime=datetime.now(UTC) + timedelta(days=7),
        end_datetime=datetime.now(UTC) + timedelta(days=7, hours=3),
    )
    db.add(other_event)
    await db.flush()

    other_tt = TicketType(event_id=other_event.id, name="GA", price=0, currency="NGN")
    db.add(other_tt)
    await db.flush()

    other_reg = Registration(
        event_id=other_event.id,
        ticket_type_id=other_tt.id,
        attendee_name="Victim Attendee",
        attendee_email="victim@example.com",
        qr_code=f"test-qr-{uuid.uuid4()}",
        status="confirmed",
    )
    db.add(other_reg)
    await db.flush()

    # user_headers belongs to `org`/`published_event`, not `other_org` - try
    # to check in the *other* org's registration through this event's endpoint.
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
        json={"registration_id": str(other_reg.id)},
        headers=user_headers,
    )
    assert resp.status_code == 404

    await db.refresh(other_reg)
    assert other_reg.status == "confirmed"  # untouched


async def test_undo_check_in(client: AsyncClient, org, published_event, registration, user_headers):
    # Check in first
    await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
        json={"registration_id": str(registration.id)},
        headers=user_headers,
    )
    # Undo
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in/{registration.id}/undo",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "confirmed"


async def test_checkin_stats(client: AsyncClient, org, published_event, registration, user_headers):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in/stats",
        headers=user_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "checked_in" in data
    assert "total" in data


async def test_checkin_search(
    client: AsyncClient, org, published_event, registration, user_headers
):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in/search",
        params={"q": "Jane"},
        headers=user_headers,
    )
    assert resp.status_code == 200
    results = resp.json()["data"]
    assert any(r["attendee_name"] == "Jane Doe" for r in results)


async def test_check_in_requires_org_membership(
    client: AsyncClient, org, published_event, registration, other_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
        json={"registration_id": str(registration.id)},
        headers=other_headers,
    )
    assert resp.status_code == 403


async def test_checked_in_ids_excludes_unconfirmed_registrations(
    client: AsyncClient, org, published_event, registration, user_headers
):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in/checked-in-ids",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == []


async def test_checked_in_ids_includes_checked_in_registration(
    client: AsyncClient, org, published_event, registration, user_headers
):
    await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
        json={"registration_id": str(registration.id)},
        headers=user_headers,
    )
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in/checked-in-ids",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == [str(registration.id)]


# ── Virtual join link - /registrations/{id}/join ────────────────────────────────


async def _make_virtual_registration(db, org, *, status="confirmed"):
    import uuid as _uuid
    from datetime import UTC, datetime, timedelta

    from app.models.event import Event
    from app.models.ticketing import Registration, TicketType

    event = Event(
        org_id=org.id,
        title="Virtual Summit",
        slug=f"virtual-summit-{_uuid.uuid4()}",
        status="published",
        format="virtual",
        virtual_url="https://zoom.us/j/123456789",
        virtual_platform="zoom",
        start_datetime=datetime.now(UTC) + timedelta(days=7),
        end_datetime=datetime.now(UTC) + timedelta(days=7, hours=3),
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
        qr_code=f"test-qr-{_uuid.uuid4()}",
        status=status,
    )
    db.add(reg)
    await db.flush()
    return event, reg


async def test_join_marks_attendance_and_redirects_to_virtual_url(client: AsyncClient, org, db):
    event, reg = await _make_virtual_registration(db, org)

    resp = await client.get(f"/api/v1/registrations/{reg.id}/join", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "https://zoom.us/j/123456789"

    await db.refresh(reg)
    assert reg.status == "checked_in"
    assert reg.checked_in_at is not None


async def test_join_is_idempotent_on_repeat_click(client: AsyncClient, org, db):
    event, reg = await _make_virtual_registration(db, org)

    await client.get(f"/api/v1/registrations/{reg.id}/join", follow_redirects=False)
    await db.refresh(reg)
    first_checked_in_at = reg.checked_in_at

    resp = await client.get(f"/api/v1/registrations/{reg.id}/join", follow_redirects=False)
    assert resp.status_code in (302, 307)

    await db.refresh(reg)
    assert reg.checked_in_at == first_checked_in_at


async def test_join_rejects_cancelled_registration(client: AsyncClient, org, db):
    event, reg = await _make_virtual_registration(db, org, status="cancelled")

    resp = await client.get(f"/api/v1/registrations/{reg.id}/join", follow_redirects=False)
    assert resp.status_code == 404

    await db.refresh(reg)
    assert reg.status == "cancelled"


async def test_join_unknown_registration_returns_404(client: AsyncClient):
    resp = await client.get(f"/api/v1/registrations/{uuid.uuid4()}/join", follow_redirects=False)
    assert resp.status_code == 404


async def test_join_in_person_event_does_not_mark_attendance(
    client: AsyncClient, org, published_event, registration
):
    resp = await client.get(f"/api/v1/registrations/{registration.id}/join", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == f"/e/{published_event.slug}"
    assert registration.status == "confirmed"
