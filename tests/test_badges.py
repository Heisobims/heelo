"""Attendee badge PDF generation — single badge (attendee-facing capability
URL, same pattern as the existing QR/calendar endpoints) and bulk print run
(organizer-facing, for printing badges for everyone checked in at the door).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from app.utils.badge_pdf import BadgeData, generate_badge_pdf


def _pdf_page_count(pdf_bytes: bytes) -> int:
    """Count `/Type /Page` object entries, excluding the `/Type /Pages` tree
    root (whose name is a prefix-match superstring of `/Page`)."""
    return pdf_bytes.count(b"/Type /Page") - pdf_bytes.count(b"/Type /Pages")


class TestBadgePdfGeneration:
    def test_generates_valid_single_page_pdf(self):
        data = BadgeData(
            attendee_name="Ada Lovelace",
            ticket_type_name="VIP",
            event_title="Founders Summit",
            org_name="Heelo Events",
        )
        pdf_bytes = generate_badge_pdf([data])
        assert pdf_bytes.startswith(b"%PDF")
        assert _pdf_page_count(pdf_bytes) == 1

    def test_generates_one_page_per_badge(self):
        badges = [
            BadgeData(
                attendee_name=f"Person {i}",
                ticket_type_name="General",
                event_title="Founders Summit",
                org_name="Heelo Events",
            )
            for i in range(3)
        ]
        pdf_bytes = generate_badge_pdf(badges)
        assert pdf_bytes.startswith(b"%PDF")
        assert _pdf_page_count(pdf_bytes) == 3

    def test_handles_missing_brand_color_and_qr(self):
        # No brand_color, no qr_bytes, no logo — must not raise
        data = BadgeData(
            attendee_name="No Frills",
            ticket_type_name="Free",
            event_title="Event",
            org_name="Org",
        )
        pdf_bytes = generate_badge_pdf([data])
        assert pdf_bytes.startswith(b"%PDF")

    def test_invalid_brand_color_falls_back_to_default(self):
        data = BadgeData(
            attendee_name="Test",
            ticket_type_name="General",
            event_title="Event",
            org_name="Org",
            brand_color="not-a-hex-color",
        )
        pdf_bytes = generate_badge_pdf([data])
        assert pdf_bytes.startswith(b"%PDF")


class TestSingleBadgeEndpoint:
    async def test_download_badge_for_confirmed_registration(
        self, client: AsyncClient, published_event, registration
    ):
        resp = await client.get(f"/api/v1/registrations/{registration.id}/badge.pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content.startswith(b"%PDF")

    async def test_badge_404_for_unknown_registration(self, client: AsyncClient):
        resp = await client.get(
            "/api/v1/registrations/00000000-0000-0000-0000-000000000000/badge.pdf"
        )
        assert resp.status_code == 404

    async def test_badge_403_for_pending_registration(
        self, client: AsyncClient, db, published_event, ticket_type
    ):
        import uuid as _uuid

        from app.models.ticketing import Registration

        reg = Registration(
            event_id=published_event.id,
            ticket_type_id=ticket_type.id,
            attendee_name="Pending Person",
            attendee_email="pending@example.com",
            qr_code=f"pending-qr-{_uuid.uuid4()}",
            status="pending",
        )
        db.add(reg)
        await db.flush()

        resp = await client.get(f"/api/v1/registrations/{reg.id}/badge.pdf")
        assert resp.status_code == 403


class TestBulkBadgesEndpoint:
    async def test_print_all_badges_for_event(
        self, client: AsyncClient, org, published_event, registration, user_headers
    ):
        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/badges.pdf",
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content.startswith(b"%PDF")

    async def test_checkin_staff_can_print_badges(
        self, client: AsyncClient, org, published_event, registration, checkin_staff_headers
    ):
        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/badges.pdf",
            headers=checkin_staff_headers,
        )
        assert resp.status_code == 200

    async def test_no_matching_registrations_404s(
        self, client: AsyncClient, org, event, user_headers
    ):
        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{event.id}/badges.pdf",
            headers=user_headers,
        )
        assert resp.status_code == 404

    async def test_status_filter_excludes_cancelled(
        self, client: AsyncClient, db, org, published_event, ticket_type, user_headers
    ):
        import uuid as _uuid

        from app.models.ticketing import Registration

        cancelled = Registration(
            event_id=published_event.id,
            ticket_type_id=ticket_type.id,
            attendee_name="Cancelled Person",
            attendee_email="cancelled@example.com",
            qr_code=f"cancelled-qr-{_uuid.uuid4()}",
            status="cancelled",
        )
        db.add(cancelled)
        await db.flush()

        resp = await client.get(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/badges.pdf?status=cancelled",
            headers=user_headers,
        )
        assert resp.status_code == 200
        # only the cancelled registration should print — 1 page
        assert _pdf_page_count(resp.content) == 1

    async def test_logo_fetch_failure_does_not_break_badge(
        self, client: AsyncClient, db, org, published_event, registration, user_headers
    ):
        org.logo_url = "https://example.com/does-not-exist.png"
        await db.flush()
        # Patched where it's called from (app.services.badge_service), not on
        # httpx.AsyncClient globally — that class is shared with the test
        # client itself and patching it there would break every request.
        with patch(
            "app.services.badge_service._fetch_logo_bytes", new=AsyncMock(return_value=None)
        ):
            resp = await client.get(
                f"/api/v1/organizations/{org.slug}/events/{published_event.id}/badges.pdf",
                headers=user_headers,
            )
        assert resp.status_code == 200
        assert resp.content.startswith(b"%PDF")

    async def test_fetch_logo_bytes_swallows_network_errors(self):
        from app.services.badge_service import _fetch_logo_bytes

        with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=Exception("network down"))):
            result = await _fetch_logo_bytes("https://example.com/logo.png")
        assert result is None
