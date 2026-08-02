"""Certificate of Attendance generation — organizer-triggered (not automatic)
per the confirmed scope: an explicit "Generate certificates" action gates
attendee downloads, and only checked-in attendees (proof of attendance) can
download. Certificates are rendered on-the-fly, nothing is stored.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.ticketing import Registration


async def _make_ended_event(db: AsyncSession, org) -> Event:
    ev = Event(
        org_id=org.id,
        title="Ended Test Event",
        slug=f"ended-event-{uuid.uuid4().hex[:8]}",
        status="ended",
        format="in_person",
        venue_city="Lagos",
        start_datetime=datetime.now(UTC) - timedelta(days=2),
        end_datetime=datetime.now(UTC) - timedelta(days=1),
    )
    db.add(ev)
    await db.flush()
    return ev


async def _make_checked_in_registration(db: AsyncSession, event, ticket_type, name="Grace Hopper"):
    reg = Registration(
        event_id=event.id,
        ticket_type_id=ticket_type.id,
        attendee_name=name,
        attendee_email=f"{name.lower().replace(' ', '.')}@example.com",
        qr_code=f"qr-{uuid.uuid4()}",
        status="checked_in",
    )
    db.add(reg)
    await db.flush()
    return reg


class TestGenerateCertificates:
    async def test_generate_requires_ended_status(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/certificates/generate",
            headers=user_headers,
        )
        assert resp.status_code == 400

    async def test_generate_succeeds_for_ended_event(
        self, client: AsyncClient, db: AsyncSession, org, ticket_type, user_headers
    ):
        # ticket_type fixture is on published_event; make our own ended event
        event = await _make_ended_event(db, org)

        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{event.id}/certificates/generate",
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["certificates_generated_at"] is not None

    async def test_checkin_staff_cannot_generate(
        self, client: AsyncClient, db: AsyncSession, org, checkin_staff_headers
    ):
        event = await _make_ended_event(db, org)
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{event.id}/certificates/generate",
            headers=checkin_staff_headers,
        )
        assert resp.status_code == 403


class TestSingleCertificateDownload:
    async def test_403_before_certificates_generated(
        self, client: AsyncClient, db: AsyncSession, org, user_headers
    ):
        from app.models.ticketing import TicketType

        event = await _make_ended_event(db, org)
        tt = TicketType(event_id=event.id, name="General", price=0, currency="NGN")
        db.add(tt)
        await db.flush()
        reg = await _make_checked_in_registration(db, event, tt)

        resp = await client.get(f"/api/v1/registrations/{reg.id}/certificate.pdf")
        assert resp.status_code == 403

    async def test_download_succeeds_after_generation_for_checked_in_attendee(
        self, client: AsyncClient, db: AsyncSession, org, user_headers
    ):
        from app.models.ticketing import TicketType

        event = await _make_ended_event(db, org)
        tt = TicketType(event_id=event.id, name="General", price=0, currency="NGN")
        db.add(tt)
        await db.flush()
        reg = await _make_checked_in_registration(db, event, tt)

        await client.post(
            f"/api/v1/organizations/{org.slug}/events/{event.id}/certificates/generate",
            headers=user_headers,
        )

        resp = await client.get(f"/api/v1/registrations/{reg.id}/certificate.pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content.startswith(b"%PDF")

    async def test_non_checked_in_attendee_cannot_download(
        self, client: AsyncClient, db: AsyncSession, org, user_headers
    ):
        from app.models.ticketing import TicketType

        event = await _make_ended_event(db, org)
        tt = TicketType(event_id=event.id, name="General", price=0, currency="NGN")
        db.add(tt)
        await db.flush()
        reg = Registration(
            event_id=event.id,
            ticket_type_id=tt.id,
            attendee_name="No Show",
            attendee_email="noshow@example.com",
            qr_code=f"qr-{uuid.uuid4()}",
            status="confirmed",
        )
        db.add(reg)
        await db.flush()

        await client.post(
            f"/api/v1/organizations/{org.slug}/events/{event.id}/certificates/generate",
            headers=user_headers,
        )

        resp = await client.get(f"/api/v1/registrations/{reg.id}/certificate.pdf")
        assert resp.status_code == 403


class TestBulkCertificatesDownload:
    async def test_bulk_requires_generation_first(
        self, client: AsyncClient, db: AsyncSession, org, user_headers
    ):
        event = await _make_ended_event(db, org)
        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{event.id}/certificates.pdf",
            headers=user_headers,
        )
        assert resp.status_code == 400

    async def test_bulk_download_after_generation(
        self, client: AsyncClient, db: AsyncSession, org, user_headers
    ):
        from app.models.ticketing import TicketType

        event = await _make_ended_event(db, org)
        tt = TicketType(event_id=event.id, name="General", price=0, currency="NGN")
        db.add(tt)
        await db.flush()
        await _make_checked_in_registration(db, event, tt, "Attendee One")
        await _make_checked_in_registration(db, event, tt, "Attendee Two")

        await client.post(
            f"/api/v1/organizations/{org.slug}/events/{event.id}/certificates/generate",
            headers=user_headers,
        )

        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{event.id}/certificates.pdf",
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.content.startswith(b"%PDF")
