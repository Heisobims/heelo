"""Unit and integration tests for vendor booking escrow lifecycle, dual fulfillment sign-off, and financial reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid
from httpx import AsyncClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vendor import Vendor, VendorBooking, VendorTransaction
from app.services import vendor_service as vsvc
from app.tasks.billing import auto_release_vendor_escrow


async def _get_or_create_vendor(client: AsyncClient, user_headers) -> uuid.UUID:
    me_res = await client.get("/api/v1/vendors/me", headers=user_headers)
    if me_res.status_code == 200:
        return uuid.UUID(me_res.json()["data"]["id"])
    res = await client.post(
        "/api/v1/vendors",
        json={
            "business_name": "Lagos Acoustic Stage",
            "category": "sound_lighting",
            "cover_image_url": "https://example.com/cover.jpg",
            "location_city": "Lagos",
            "location_country": "NG",
            "price_range": "mid",
            "description": "Professional acoustic stage sound engineering and setup.",
            "currency": "NGN",
        },
        headers=user_headers,
    )
    assert res.status_code == 201
    return uuid.UUID(res.json()["data"]["id"])


@pytest.mark.asyncio
async def test_escrow_funding_and_lock_on_payment(client: AsyncClient, db: AsyncSession, user_headers, other_headers):
    vendor_id = await _get_or_create_vendor(client, user_headers)

    # 2. Add a service listing
    service_res = await client.post(
        "/api/v1/vendors/me/services",
        json={
            "title": "Concert Sound System",
            "category": "sound_lighting",
            "description": "Full concert PA system with digital mixer and monitor array.",
            "price": 500000.0,
            "pricing_type": "fixed",
            "currency": "NGN",
        },
        headers=user_headers,
    )
    assert service_res.status_code == 201
    service_id = uuid.UUID(service_res.json()["data"]["id"])

    # 3. Client creates direct booking
    booking_res = await client.post(
        "/api/v1/vendors/bookings",
        json={
            "vendor_id": str(vendor_id),
            "service_listing_id": str(service_id),
            "event_name": "Afro-Beats Festival Night",
            "event_location": "Victoria Island, Lagos",
        },
        headers=other_headers,
    )
    assert booking_res.status_code == 201
    booking_data = booking_res.json()["data"]
    booking_id = uuid.UUID(booking_data["id"])

    # Model A: 10% platform commission: 500k gross = 50k fee, 450k net
    assert booking_data["total_amount"] == 500000.0
    assert booking_data["commission_amount"] == 50000.0
    assert booking_data["vendor_earnings"] == 450000.0
    assert booking_data["status"] == "pending_payment"
    assert booking_data["escrow_status"] == "pending"

    # 4. Confirm payment (funds enter escrow)
    pay_res = await client.post(
        f"/api/v1/vendors/bookings/{booking_id}/confirm-payment",
        headers=other_headers,
    )
    assert pay_res.status_code == 200
    updated_booking = pay_res.json()["data"]
    assert updated_booking["status"] == "confirmed"
    assert updated_booking["escrow_status"] == "held_in_escrow"

    # 5. Financial verification:
    # Vendor escrow_balance has 450,000 NGN.
    # Vendor payable_balance MUST BE 0.0 (locked in trust until fulfillment!)
    vendor_db = await db.get(Vendor, vendor_id)
    assert float(vendor_db.escrow_balance) == 450000.0
    assert float(vendor_db.payable_balance) == 0.0

    # Verify immutable ledger entry
    tx = await db.scalar(
        select(VendorTransaction).where(
            VendorTransaction.booking_id == booking_id,
            VendorTransaction.type == "escrow_deposit",
        )
    )
    assert tx is not None
    assert float(tx.gross_amount) == 500000.0
    assert float(tx.platform_fee) == 50000.0
    assert float(tx.net_amount) == 450000.0
    assert tx.status == "completed"


@pytest.mark.asyncio
async def test_vendor_mark_delivered_and_client_escrow_release(
    client: AsyncClient, db: AsyncSession, user_headers, other_headers
):
    vendor_id = await _get_or_create_vendor(client, user_headers)

    s_res = await client.post(
        "/api/v1/vendors/me/services",
        json={
            "title": "VIP 3-Course Dinner",
            "category": "catering",
            "description": "Gourmet multi-course plated dinner for up to 100 guests.",
            "price": 300000.0,
            "pricing_type": "fixed",
            "currency": "NGN",
        },
        headers=user_headers,
    )
    service_id = uuid.UUID(s_res.json()["data"]["id"])

    b_res = await client.post(
        "/api/v1/vendors/bookings",
        json={
            "vendor_id": str(vendor_id),
            "service_listing_id": str(service_id),
            "event_name": "Annual Founders Gala",
        },
        headers=other_headers,
    )
    booking_id = uuid.UUID(b_res.json()["data"]["id"])

    # Client pays -> enters escrow
    await client.post(
        f"/api/v1/vendors/bookings/{booking_id}/confirm-payment",
        headers=other_headers,
    )

    # 1. Vendor marks service as delivered
    deliv_res = await client.post(
        f"/api/v1/vendors/bookings/{booking_id}/deliver",
        json={
            "proof_notes": "All 100 VIP dinners served according to menu schedule.",
            "proof_urls": ["https://example.com/proof1.jpg"],
        },
        headers=user_headers,
    )
    assert deliv_res.status_code == 200
    deliv_data = deliv_res.json()["data"]
    assert deliv_data["status"] == "delivered"
    assert deliv_data["fulfillment_submitted_at"] is not None
    assert deliv_data["auto_release_deadline"] is not None
    assert deliv_data["fulfillment_proof_notes"] == "All 100 VIP dinners served according to menu schedule."

    # 2. Client confirms fulfillment and releases escrow
    rel_res = await client.post(
        f"/api/v1/vendors/bookings/{booking_id}/release-escrow",
        headers=other_headers,
    )
    assert rel_res.status_code == 200
    rel_data = rel_res.json()["data"]
    assert rel_data["status"] == "completed"
    assert rel_data["escrow_status"] == "released"
    assert rel_data["escrow_released_at"] is not None

    # 3. Check vendor balance reconciliation:
    # 300,000 NGN total, 30,000 NGN commission (10%), 270,000 NGN net earnings
    # Funds moved from escrow_balance (now 0) to payable_balance (now 270k)
    vendor_db = await db.get(Vendor, vendor_id)
    assert float(vendor_db.escrow_balance) == 0.0
    assert float(vendor_db.payable_balance) == 270000.0
    assert float(vendor_db.total_earned) == 270000.0

    # 4. Check ledger release transaction
    rel_tx = await db.scalar(
        select(VendorTransaction).where(
            VendorTransaction.booking_id == booking_id,
            VendorTransaction.type == "escrow_release",
        )
    )
    assert rel_tx is not None
    assert float(rel_tx.net_amount) == 270000.0


@pytest.mark.asyncio
async def test_client_dispute_freezes_escrow(client: AsyncClient, db: AsyncSession, user_headers, other_headers):
    vendor_id = await _get_or_create_vendor(client, user_headers)

    s_res = await client.post(
        "/api/v1/vendors/me/services",
        json={
            "title": "DJ Booth & 2 Speakers",
            "category": "sound_lighting",
            "description": "Basic 4-hour set.",
            "price": 100000.0,
            "pricing_type": "fixed",
            "currency": "NGN",
        },
        headers=user_headers,
    )
    service_id = uuid.UUID(s_res.json()["data"]["id"])

    b_res = await client.post(
        "/api/v1/vendors/bookings",
        json={
            "vendor_id": str(vendor_id),
            "service_listing_id": str(service_id),
            "event_name": "Birthday Celebration",
        },
        headers=other_headers,
    )
    booking_id = uuid.UUID(b_res.json()["data"]["id"])

    # Client pays
    await client.post(
        f"/api/v1/vendors/bookings/{booking_id}/confirm-payment",
        headers=other_headers,
    )

    # Vendor marks delivered
    await client.post(
        f"/api/v1/vendors/bookings/{booking_id}/deliver",
        headers=user_headers,
    )

    # Client lodges a dispute
    disp_res = await client.post(
        f"/api/v1/vendors/bookings/{booking_id}/dispute",
        json={"reason": "Vendor arrived 3 hours late and missing promised microphones."},
        headers=other_headers,
    )
    assert disp_res.status_code == 200
    disp_data = disp_res.json()["data"]
    assert disp_data["status"] == "disputed"
    assert disp_data["escrow_status"] == "disputed"

    # Funds must be moved to disputed_balance and escrow_balance zeroed
    vendor_db = await db.get(Vendor, vendor_id)
    assert float(vendor_db.escrow_balance) == 0.0
    assert float(vendor_db.disputed_balance) == 90000.0
    assert float(vendor_db.payable_balance) == 0.0


@pytest.mark.asyncio
async def test_auto_release_escrow_after_sla_expiry(client: AsyncClient, db: AsyncSession, user_headers, other_headers):
    vendor_id = await _get_or_create_vendor(client, user_headers)

    s_res = await client.post(
        "/api/v1/vendors/me/services",
        json={
            "title": "Stage Floral Arch",
            "category": "decor_rentals",
            "description": "Custom floral arch with backlighting.",
            "price": 200000.0,
            "pricing_type": "fixed",
            "currency": "NGN",
        },
        headers=user_headers,
    )
    service_id = uuid.UUID(s_res.json()["data"]["id"])

    b_res = await client.post(
        "/api/v1/vendors/bookings",
        json={
            "vendor_id": str(vendor_id),
            "service_listing_id": str(service_id),
            "event_name": "Product Launch",
        },
        headers=other_headers,
    )
    booking_id = uuid.UUID(b_res.json()["data"]["id"])

    # Client pays -> enters escrow
    await client.post(
        f"/api/v1/vendors/bookings/{booking_id}/confirm-payment",
        headers=other_headers,
    )

    # Vendor marks delivered
    await client.post(
        f"/api/v1/vendors/bookings/{booking_id}/deliver",
        headers=user_headers,
    )

    # Simulate that 49 hours have passed by setting auto_release_deadline in the past
    booking = await db.get(VendorBooking, booking_id)
    assert booking is not None
    booking.auto_release_deadline = datetime.now(UTC) - timedelta(hours=1)
    await db.commit()

    # Trigger Celery auto-release task
    released_count = auto_release_vendor_escrow()
    assert released_count >= 1

    # Verify booking status is now completed and escrow is released
    await db.refresh(booking)
    assert booking.status == "completed"
    assert booking.escrow_status == "released"

    vendor_db = await db.get(Vendor, vendor_id)
    assert float(vendor_db.escrow_balance) == 0.0
    assert float(vendor_db.payable_balance) == 180000.0
    assert float(vendor_db.total_earned) == 180000.0

