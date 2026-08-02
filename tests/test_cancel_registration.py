"""Tests for the registration cancel/refund flow: the ticketing_service.cancel_registration()
service function, plus the organizer and attendee-self-service router endpoints that call it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.services import payment_service as pay_svc
from app.services import ticketing_service as tk_svc


async def _fetch(db, reg_id):
    return await tk_svc.get_registration_by_id(db, reg_id)


class TestCancelRegistrationService:
    async def test_cancel_without_refund(self, db, paid_registration, ticket_type):
        reg = await _fetch(db, paid_registration.id)
        result = await tk_svc.cancel_registration(db, reg, refund=False, cancelled_by="organizer")
        assert result.status == "cancelled"

        await db.refresh(ticket_type)
        assert ticket_type.quantity_sold == 0

    async def test_cancel_with_successful_refund_marks_order_refunded(
        self, db, paid_registration, order, ticket_type
    ):
        reg = await _fetch(db, paid_registration.id)
        with patch("app.services.payment_service.refund_order_item", AsyncMock(return_value=True)):
            result = await tk_svc.cancel_registration(db, reg, refund=True, cancelled_by="attendee")

        assert result.status == "refunded"
        await db.refresh(order)
        assert float(order.refunded_amount) == pytest.approx(float(ticket_type.price))
        # Single registration on the order -> fully refunded once it's the only item.
        assert order.payment_status == "refunded"

    async def test_refund_reverses_platform_fee_on_the_refunded_amount(
        self, db, paid_registration, order, ticket_type
    ):
        """A refund shouldn't let the platform keep a fee on money given back —
        the fee on the refunded ticket's price is reversed and added back to
        what the organizer nets."""
        original_platform_fee = float(order.platform_fee)
        original_net_amount = float(order.net_amount)

        reg = await _fetch(db, paid_registration.id)
        with patch("app.services.payment_service.refund_order_item", AsyncMock(return_value=True)):
            await tk_svc.cancel_registration(db, reg, refund=True, cancelled_by="attendee")

        await db.refresh(order)
        expected_fee_reversed = float(ticket_type.price) * float(pay_svc.PLATFORM_FEE_PERCENT)

        assert float(order.platform_fee) == pytest.approx(
            original_platform_fee - expected_fee_reversed
        )
        assert float(order.net_amount) == pytest.approx(original_net_amount + expected_fee_reversed)
        # Fee-reversal-adjusted net revenue should equal exactly what's left unrefunded,
        # net of fee — the whole point of tracking it this way.
        assert float(order.net_amount) - float(order.refunded_amount) == pytest.approx(0.0)

    async def test_partial_refund_when_sibling_registration_remains(
        self, db, paid_registration, order, ticket_type, published_event
    ):
        import uuid as _uuid

        from app.models.ticketing import Registration

        sibling = Registration(
            event_id=published_event.id,
            ticket_type_id=ticket_type.id,
            order_id=order.id,
            attendee_name="Sibling Attendee",
            attendee_email="sibling@example.com",
            qr_code=f"test-qr-{_uuid.uuid4()}",
            status="confirmed",
        )
        db.add(sibling)
        await db.flush()

        reg = await _fetch(db, paid_registration.id)
        with patch("app.services.payment_service.refund_order_item", AsyncMock(return_value=True)):
            result = await tk_svc.cancel_registration(
                db, reg, refund=True, cancelled_by="organizer"
            )

        assert result.status == "refunded"
        await db.refresh(order)
        assert order.payment_status == "partially_refunded"

    async def test_refund_failure_raises_502_and_leaves_registration_confirmed(
        self, db, paid_registration, order, ticket_type
    ):
        reg = await _fetch(db, paid_registration.id)
        with patch("app.services.payment_service.refund_order_item", AsyncMock(return_value=False)):
            with pytest.raises(HTTPException) as exc_info:
                await tk_svc.cancel_registration(db, reg, refund=True, cancelled_by="attendee")

        assert exc_info.value.status_code == 502

        await db.refresh(reg)
        await db.refresh(order)
        assert reg.status == "confirmed"
        assert float(order.refunded_amount) == 0
        assert order.payment_status == "paid"

    async def test_already_cancelled_registration_rejected(self, db, paid_registration):
        reg = await _fetch(db, paid_registration.id)
        await tk_svc.cancel_registration(db, reg, refund=False, cancelled_by="organizer")

        reg_again = await _fetch(db, paid_registration.id)
        with pytest.raises(HTTPException) as exc_info:
            await tk_svc.cancel_registration(db, reg_again, refund=False, cancelled_by="organizer")
        assert exc_info.value.status_code == 400

    async def test_free_ticket_cancel_does_not_call_refund(self, db, published_event):
        import uuid as _uuid

        from app.models.ticketing import Registration, TicketType

        free_tt = TicketType(
            event_id=published_event.id,
            name="Free",
            price=0.0,
            currency="NGN",
            quantity=100,
            quantity_sold=1,
        )
        db.add(free_tt)
        await db.flush()

        reg = Registration(
            event_id=published_event.id,
            ticket_type_id=free_tt.id,
            attendee_name="Free Attendee",
            attendee_email="free@example.com",
            qr_code=f"test-qr-{_uuid.uuid4()}",
            status="confirmed",
        )
        db.add(reg)
        await db.flush()

        reg = await _fetch(db, reg.id)
        with patch(
            "app.services.payment_service.refund_order_item", AsyncMock(return_value=True)
        ) as mock_refund:
            result = await tk_svc.cancel_registration(db, reg, refund=True, cancelled_by="attendee")

        mock_refund.assert_not_called()
        # No refund actually happened -> "cancelled", not "refunded".
        assert result.status == "cancelled"


class TestOrganizerCancelEndpoint:
    async def test_success(self, client, user_headers, org, published_event, paid_registration):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}"
            f"/registrations/{paid_registration.id}/cancel",
            json={"refund": False},
            headers=user_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["status"] == "cancelled"

    async def test_404_for_registration_on_a_different_event(
        self, client, user_headers, org, db, paid_registration
    ):
        from datetime import UTC, datetime, timedelta

        from app.models.event import Event

        other_event = Event(
            org_id=org.id,
            title="Other Event",
            slug="other-event",
            status="published",
            format="in_person",
            start_datetime=datetime.now(UTC) + timedelta(days=7),
            end_datetime=datetime.now(UTC) + timedelta(days=7, hours=3),
        )
        db.add(other_event)
        await db.flush()

        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{other_event.id}"
            f"/registrations/{paid_registration.id}/cancel",
            json={"refund": False},
            headers=user_headers,
        )
        assert resp.status_code == 404

    async def test_403_for_non_member(
        self, client, other_headers, org, published_event, paid_registration
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}"
            f"/registrations/{paid_registration.id}/cancel",
            json={"refund": False},
            headers=other_headers,
        )
        assert resp.status_code == 403


class TestAttendeeSelfServiceCancelEndpoint:
    async def test_success_when_email_matches(
        self, client, user_headers, user, db, published_event, ticket_type
    ):
        import uuid as _uuid

        from app.models.ticketing import Registration

        reg = Registration(
            event_id=published_event.id,
            ticket_type_id=ticket_type.id,
            attendee_name=user.full_name,
            attendee_email=user.email,
            qr_code=f"test-qr-{_uuid.uuid4()}",
            status="confirmed",
        )
        db.add(reg)
        await db.flush()

        resp = await client.post(
            f"/api/v1/registrations/{reg.id}/cancel",
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "cancelled"

    async def test_403_when_not_the_owner(self, client, other_headers, paid_registration):
        resp = await client.post(
            f"/api/v1/registrations/{paid_registration.id}/cancel",
            headers=other_headers,
        )
        assert resp.status_code == 403

    async def test_404_for_unknown_registration(self, client, user_headers):
        import uuid

        resp = await client.post(
            f"/api/v1/registrations/{uuid.uuid4()}/cancel",
            headers=user_headers,
        )
        assert resp.status_code == 404
