"""Ticket transfer - a genuinely new feature. Registration already had
transferred_from_id/transfer_token columns and a "Transferred" status badge,
but nothing anywhere let an attendee actually initiate one. Covers the
service functions, the attendee-facing endpoints, and the capability-URL
claim flow (same unauthenticated pattern as qr.png/badge.pdf)."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.services import ticketing_service as tk_svc


async def _make_registration(db, event, ticket_type, *, attendee_email, status="confirmed"):
    from app.models.ticketing import Registration

    reg = Registration(
        event_id=event.id,
        ticket_type_id=ticket_type.id,
        attendee_name="Original Holder",
        attendee_email=attendee_email,
        qr_code=f"test-qr-{uuid.uuid4()}",
        status=status,
        referral_token=f"test-ref-{uuid.uuid4().hex[:12]}",
    )
    db.add(reg)
    await db.flush()
    return reg


# ── Service layer ────────────────────────────────────────────────────────────


class TestInitiateTransfer:
    async def test_sets_pending_status_token_and_expiry(
        self, db, published_event, ticket_type, user
    ):
        reg = await _make_registration(db, published_event, ticket_type, attendee_email=user.email)
        result = await tk_svc.initiate_transfer(db, reg)
        assert result.status == "transfer_pending"
        assert result.transfer_token is not None
        assert result.transfer_expires_at is not None

    async def test_rejects_non_confirmed_registration(self, db, published_event, ticket_type, user):
        reg = await _make_registration(
            db, published_event, ticket_type, attendee_email=user.email, status="cancelled"
        )
        with pytest.raises(HTTPException) as exc:
            await tk_svc.initiate_transfer(db, reg)
        assert exc.value.status_code == 400


class TestCancelTransfer:
    async def test_reverts_to_confirmed_and_clears_token(
        self, db, published_event, ticket_type, user
    ):
        reg = await _make_registration(db, published_event, ticket_type, attendee_email=user.email)
        await tk_svc.initiate_transfer(db, reg)
        result = await tk_svc.cancel_transfer(db, reg)
        assert result.status == "confirmed"
        assert result.transfer_token is None
        assert result.transfer_expires_at is None

    async def test_rejects_when_no_pending_transfer(self, db, published_event, ticket_type, user):
        reg = await _make_registration(db, published_event, ticket_type, attendee_email=user.email)
        with pytest.raises(HTTPException) as exc:
            await tk_svc.cancel_transfer(db, reg)
        assert exc.value.status_code == 400


class TestGetByTransferToken:
    async def test_returns_none_for_unknown_token(self, db):
        assert await tk_svc.get_registration_by_transfer_token(db, "not-a-real-token") is None

    async def test_returns_none_for_non_pending_status(
        self, db, published_event, ticket_type, user
    ):
        """Defends against a claimed/expired-and-reused token still resolving
        just because the token string happens to still be set somewhere."""
        reg = await _make_registration(db, published_event, ticket_type, attendee_email=user.email)
        reg.transfer_token = "leftover-token"
        await db.flush()
        assert await tk_svc.get_registration_by_transfer_token(db, "leftover-token") is None

    async def test_returns_none_for_expired_token(self, db, published_event, ticket_type, user):
        from datetime import UTC, datetime, timedelta

        reg = await _make_registration(db, published_event, ticket_type, attendee_email=user.email)
        await tk_svc.initiate_transfer(db, reg)
        reg.transfer_expires_at = datetime.now(UTC) - timedelta(days=1)
        await db.flush()
        assert await tk_svc.get_registration_by_transfer_token(db, reg.transfer_token) is None


class TestClaimTransfer:
    async def test_creates_new_registration_and_voids_original(
        self, db, published_event, ticket_type, user
    ):
        original = await _make_registration(
            db, published_event, ticket_type, attendee_email=user.email
        )
        await tk_svc.initiate_transfer(db, original)
        token = original.transfer_token

        new_reg = await tk_svc.claim_transfer(
            db, token, new_name="New Holder", new_email="new-holder@example.com", new_phone=None
        )
        assert new_reg.status == "confirmed"
        assert new_reg.attendee_email == "new-holder@example.com"
        assert new_reg.transferred_from_id == original.id
        assert new_reg.ticket_type_id == original.ticket_type_id
        assert new_reg.qr_code != original.qr_code

        await db.refresh(original)
        assert original.status == "transferred"
        assert original.transfer_token is None

    async def test_token_is_single_use(self, db, published_event, ticket_type, user):
        original = await _make_registration(
            db, published_event, ticket_type, attendee_email=user.email
        )
        await tk_svc.initiate_transfer(db, original)
        token = original.transfer_token

        await tk_svc.claim_transfer(
            db, token, new_name="First Claimer", new_email="first@example.com", new_phone=None
        )
        with pytest.raises(HTTPException) as exc:
            await tk_svc.claim_transfer(
                db, token, new_name="Second Claimer", new_email="second@example.com", new_phone=None
            )
        assert exc.value.status_code == 400

    async def test_rejects_invalid_token(self, db):
        with pytest.raises(HTTPException) as exc:
            await tk_svc.claim_transfer(
                db, "garbage-token", new_name="X", new_email="x@example.com", new_phone=None
            )
        assert exc.value.status_code == 400

    async def test_concurrent_claims_only_one_succeeds(
        self, db, engine, published_event, ticket_type, user
    ):
        """Two requests racing to claim the same link - e.g. a double-click,
        or the link forwarded to two people - must not both mint a new
        registration from one original ticket."""
        import asyncio

        from sqlalchemy.ext.asyncio import async_sessionmaker

        original = await _make_registration(
            db, published_event, ticket_type, attendee_email=user.email
        )
        await tk_svc.initiate_transfer(db, original)
        token = original.transfer_token

        SessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        async with SessionLocal() as db2:
            results = await asyncio.gather(
                tk_svc.claim_transfer(
                    db, token, new_name="Racer A", new_email="racer-a@example.com", new_phone=None
                ),
                tk_svc.claim_transfer(
                    db2,
                    token,
                    new_name="Racer B",
                    new_email="racer-b@example.com",
                    new_phone=None,
                ),
                return_exceptions=True,
            )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], HTTPException)
        assert failures[0].status_code == 400


# ── Router / HTTP layer ──────────────────────────────────────────────────────


async def test_transfer_requires_auth(client: AsyncClient, registration):
    resp = await client.post(f"/api/v1/registrations/{registration.id}/transfer")
    assert resp.status_code == 401


async def test_transfer_rejects_non_owner(client: AsyncClient, other_headers, registration):
    resp = await client.post(
        f"/api/v1/registrations/{registration.id}/transfer", headers=other_headers
    )
    assert resp.status_code == 403


async def test_transfer_404_for_unknown_registration(client: AsyncClient, user_headers):
    resp = await client.post(f"/api/v1/registrations/{uuid.uuid4()}/transfer", headers=user_headers)
    assert resp.status_code == 404


async def test_transfer_success_returns_shareable_url(
    client: AsyncClient, db, user_headers, user, published_event, ticket_type
):
    reg = await _make_registration(db, published_event, ticket_type, attendee_email=user.email)
    resp = await client.post(f"/api/v1/registrations/{reg.id}/transfer", headers=user_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "transfer_pending"
    assert "/transfer/" in data["transfer_url"]


async def test_qr_image_blocked_while_transfer_pending(
    client: AsyncClient, db, user_headers, user, published_event, ticket_type
):
    reg = await _make_registration(db, published_event, ticket_type, attendee_email=user.email)
    await client.post(f"/api/v1/registrations/{reg.id}/transfer", headers=user_headers)

    resp = await client.get(f"/api/v1/registrations/{reg.id}/qr.png")
    assert resp.status_code == 403


async def test_cancel_transfer_restores_ticket(
    client: AsyncClient, db, user_headers, user, published_event, ticket_type
):
    reg = await _make_registration(db, published_event, ticket_type, attendee_email=user.email)
    await client.post(f"/api/v1/registrations/{reg.id}/transfer", headers=user_headers)

    resp = await client.post(
        f"/api/v1/registrations/{reg.id}/transfer/cancel", headers=user_headers
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "confirmed"

    qr_resp = await client.get(f"/api/v1/registrations/{reg.id}/qr.png")
    assert qr_resp.status_code == 200


async def test_get_transfer_details_public_endpoint(
    client: AsyncClient, db, user_headers, user, published_event, ticket_type
):
    reg = await _make_registration(db, published_event, ticket_type, attendee_email=user.email)
    init = await client.post(f"/api/v1/registrations/{reg.id}/transfer", headers=user_headers)
    token = init.json()["data"]["transfer_url"].rsplit("/", 1)[-1]

    resp = await client.get(f"/api/v1/registrations/transfer/{token}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["event_title"] == published_event.title
    assert data["from_attendee_name"] == "Original Holder"


async def test_get_transfer_details_404_for_invalid_token(client: AsyncClient):
    resp = await client.get("/api/v1/registrations/transfer/not-a-real-token")
    assert resp.status_code == 404


async def test_claim_endpoint_end_to_end(
    client: AsyncClient, db, user_headers, user, published_event, ticket_type
):
    reg = await _make_registration(db, published_event, ticket_type, attendee_email=user.email)
    init = await client.post(f"/api/v1/registrations/{reg.id}/transfer", headers=user_headers)
    token = init.json()["data"]["transfer_url"].rsplit("/", 1)[-1]

    claim = await client.post(
        f"/api/v1/registrations/transfer/{token}/claim",
        json={"name": "New Holder", "email": "claimed@example.com", "phone": "+2348011112222"},
    )
    assert claim.status_code == 200
    new_reg_id = claim.json()["data"]["id"]
    assert claim.json()["data"]["status"] == "confirmed"

    # Original is now voided...
    old_qr = await client.get(f"/api/v1/registrations/{reg.id}/qr.png")
    assert old_qr.status_code == 403
    # ...and the new registration's ticket works.
    new_qr = await client.get(f"/api/v1/registrations/{new_reg_id}/qr.png")
    assert new_qr.status_code == 200

    # Replaying the same link must fail - single-use.
    replay = await client.post(
        f"/api/v1/registrations/transfer/{token}/claim",
        json={"name": "Someone Else", "email": "else@example.com"},
    )
    assert replay.status_code == 400


async def test_transfer_claim_page_renders_for_valid_token(
    client: AsyncClient, db, user_headers, user, published_event, ticket_type
):
    reg = await _make_registration(db, published_event, ticket_type, attendee_email=user.email)
    init = await client.post(f"/api/v1/registrations/{reg.id}/transfer", headers=user_headers)
    token = init.json()["data"]["transfer_url"].rsplit("/", 1)[-1]

    resp = await client.get(f"/transfer/{token}")
    assert resp.status_code == 200
    assert b"You've been sent a ticket" in resp.content


async def test_transfer_claim_page_shows_error_for_invalid_token(client: AsyncClient):
    resp = await client.get("/transfer/not-a-real-token")
    assert resp.status_code == 200
    assert b"Link not valid" in resp.content


async def test_check_in_blocked_while_transfer_pending(
    client: AsyncClient, db, user_headers, user, org, published_event, ticket_type
):
    """The whole point of locking the ticket at initiate-time, not
    claim-time: the original holder can't show up and check in a ticket
    that's mid-transfer to someone else."""
    reg = await _make_registration(db, published_event, ticket_type, attendee_email=user.email)
    await client.post(f"/api/v1/registrations/{reg.id}/transfer", headers=user_headers)

    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
        json={"registration_id": str(reg.id)},
        headers=user_headers,
    )
    assert resp.status_code == 400
