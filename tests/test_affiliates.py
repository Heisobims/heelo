"""End-to-end tests for Affiliate & Promoter Tracking and Commission Payouts."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.affiliate import EventAffiliate


class TestAffiliateFlow:
    async def test_create_and_list_affiliate(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        res = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/affiliates",
            json={
                "promoter_name": "Tunde Ambassador",
                "promoter_email": "tunde@ambassador.com",
                "promoter_phone": "+2348033333333",
                "affiliate_code": "TUNDE15",
                "commission_type": "percentage",
                "commission_rate": 15.0,
                "payout_bank_code": "058",
                "payout_account_number": "0123456789",
                "payout_account_name": "Tunde Promoter Account",
            },
            headers=user_headers,
        )
        assert res.status_code == 201
        data = res.json()["data"]
        aff_id = data["id"]
        assert data["affiliate_code"] == "TUNDE15"
        assert data["commission_rate"] == 15.0

        # List affiliates for org
        res_list = await client.get(
            f"/api/v1/organizations/{org.slug}/affiliates?event_id={published_event.id}",
            headers=user_headers,
        )
        assert res_list.status_code == 200
        affs = res_list.json()["data"]
        assert any(a["id"] == aff_id for a in affs)

    async def test_affiliate_click_and_redirect(
        self, client: AsyncClient, org, published_event, user_headers, db: AsyncSession
    ):
        res = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/affiliates",
            json={
                "promoter_name": "Sarah Promo",
                "promoter_email": "sarah@promo.com",
                "affiliate_code": "SARAH10",
                "commission_type": "percentage",
                "commission_rate": 10.0,
            },
            headers=user_headers,
        )
        assert res.status_code == 201

        # Test referral redirect route /r/{code}
        res_redirect = await client.get("/r/SARAH10", follow_redirects=False)
        assert res_redirect.status_code in (302, 307)
        assert f"/e/{published_event.slug}?ref=SARAH10" in res_redirect.headers["location"]

        # Verify clicks_count incremented
        aff_row = await db.scalar(
            select(EventAffiliate).where(EventAffiliate.affiliate_code == "SARAH10")
        )
        assert aff_row.clicks_count == 1

    async def test_affiliate_commission_payout_disbursement(
        self, client: AsyncClient, org, published_event, user_headers, db: AsyncSession
    ):
        # Create affiliate with initial earnings
        aff = EventAffiliate(
            event_id=published_event.id,
            promoter_name="Bisi Ambassador",
            promoter_email="bisi@promo.com",
            affiliate_code="BISI20",
            commission_type="percentage",
            commission_rate=20.0,
            tickets_sold=10,
            gross_sales=200000.0,
            commission_earned=40000.0,
            commission_paid=0.0,
        )
        db.add(aff)
        await db.commit()
        await db.refresh(aff)

        assert aff.commission_owed == 40000.0

        # Disburse payout
        res_payout = await client.post(
            f"/api/v1/organizations/{org.slug}/affiliates/{aff.id}/payout",
            json={
                "amount": 40000.0,
                "method": "manual",
                "notes": "Bank transfer confirmed via reference #10293",
            },
            headers=user_headers,
        )
        assert res_payout.status_code == 200
        p_data = res_payout.json()["data"]
        assert p_data["amount"] == 40000.0
        assert p_data["status"] in ["completed", "success"]

        # Check affiliate owed amount is now 0
        await db.refresh(aff)
        assert aff.commission_paid == 40000.0
        assert aff.commission_owed == 0.0

        # List affiliate payouts
        res_payouts = await client.get(
            f"/api/v1/organizations/{org.slug}/affiliates/{aff.id}/payouts",
            headers=user_headers,
        )
        assert res_payouts.status_code == 200
        payouts_list = res_payouts.json()["data"]
        assert len(payouts_list) == 1
        assert payouts_list[0]["amount"] == 40000.0
