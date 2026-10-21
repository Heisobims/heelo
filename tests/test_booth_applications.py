"""End-to-end tests for Vendor Booth Packages and Application Flow."""

from __future__ import annotations

import uuid
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.speaker import Sponsor
from app.models.vendor import BoothApplication, EventBoothPackage


class TestBoothFlow:
    async def test_booth_package_crud(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        # 1. Create booth package
        res = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/booth-packages",
            json={
                "name": "Standard Expo Booth",
                "price": 75000.0,
                "currency": "NGN",
                "total_booths": 5,
                "dimensions": "3m x 3m",
                "description": "Includes 1 table and 2 chairs",
                "amenities": ["WiFi", "Power outlet"],
            },
            headers=user_headers,
        )
        assert res.status_code == 201
        data = res.json()["data"]
        pkg_id = data["id"]
        assert data["name"] == "Standard Expo Booth"
        assert data["price"] == 75000.0
        assert data["booths_remaining"] == 5

        # 2. Public list booth packages
        res_list = await client.get(f"/api/v1/events/{published_event.id}/booth-packages")
        assert res_list.status_code == 200
        packages = res_list.json()["data"]
        assert any(p["id"] == pkg_id for p in packages)

    async def test_booth_application_approval_and_payment_flow(
        self, client: AsyncClient, org, published_event, user_headers, db: AsyncSession
    ):
        # Create a package first
        res_pkg = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/booth-packages",
            json={
                "name": "Premium Corner Booth",
                "price": 120000.0,
                "currency": "NGN",
                "total_booths": 3,
                "dimensions": "4m x 4m",
            },
            headers=user_headers,
        )
        assert res_pkg.status_code == 201
        pkg_id = res_pkg.json()["data"]["id"]

        # Vendor submits public application
        res_apply = await client.post(
            f"/api/v1/events/{published_event.id}/booth-applications",
            json={
                "business_name": "Apex Sound Labs",
                "contact_name": "David Adeleke",
                "contact_email": "david@apexsound.com",
                "contact_phone": "+2348012345678",
                "category": "sound_lighting",
                "package_id": pkg_id,
                "booth_requirements": "Need 32A power hookup and acoustic shielding",
            },
        )
        assert res_apply.status_code == 201
        app_data = res_apply.json()["data"]
        app_id = app_data["id"]
        assert app_data["status"] == "pending"
        assert app_data["price"] == 120000.0

        # Organizer lists booth applications
        res_list = await client.get(
            f"/api/v1/organizations/{org.slug}/booth-applications?event_id={published_event.id}",
            headers=user_headers,
        )
        assert res_list.status_code == 200
        apps = res_list.json()["data"]
        assert any(a["id"] == app_id for a in apps)

        # Organizer approves application with booth number
        res_approve = await client.post(
            f"/api/v1/organizations/{org.slug}/booth-applications/{app_id}/approve",
            json={"assigned_booth_number": "B-04"},
            headers=user_headers,
        )
        assert res_approve.status_code == 200
        approved_data = res_approve.json()["data"]
        assert approved_data["status"] == "approved"
        assert approved_data["assigned_booth_number"] == "B-04"
        assert approved_data["invoice_url"] is not None
        assert f"/booths/{app_id}/pay" in approved_data["invoice_url"]

        # Confirm payment for booth (simulate checkout)
        res_pay = await client.post(
            f"/api/v1/booths/{app_id}/confirm-payment",
            json={"payment_reference": f"pay_test_{uuid.uuid4().hex[:8]}"},
        )
        assert res_pay.status_code == 200
        paid_data = res_pay.json()["data"]
        assert paid_data["status"] == "paid"
        assert paid_data["paid_at"] is not None

        # Verify package booths_remaining was decremented
        pkg_row = await db.scalar(
            select(EventBoothPackage).where(EventBoothPackage.id == uuid.UUID(pkg_id))
        )
        assert pkg_row.booths_remaining == 2

        # Verify sponsor/exhibitor entry was automatically generated
        sponsor_row = await db.scalar(
            select(Sponsor).where(
                Sponsor.event_id == published_event.id,
                Sponsor.name == "Apex Sound Labs",
            )
        )
        assert sponsor_row is not None
        assert sponsor_row.is_exhibitor is True
        assert sponsor_row.booth_number == "B-04"

    async def test_booth_application_rejection(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        res_apply = await client.post(
            f"/api/v1/events/{published_event.id}/booth-applications",
            json={
                "business_name": "Rejected Inc",
                "contact_name": "John Doe",
                "contact_email": "john@rejected.com",
                "contact_phone": "+2348000000000",
                "category": "catering",
            },
        )
        assert res_apply.status_code == 201
        app_id = res_apply.json()["data"]["id"]

        res_reject = await client.post(
            f"/api/v1/organizations/{org.slug}/booth-applications/{app_id}/reject",
            json={"reason": "Food stalls are at maximum event capacity"},
            headers=user_headers,
        )
        assert res_reject.status_code == 200
        rejected_data = res_reject.json()["data"]
        assert rejected_data["status"] == "rejected"
        assert rejected_data["rejection_reason"] == "Food stalls are at maximum event capacity"

