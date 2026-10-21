"""End-to-end tests for the complete transactional and monetizable Vendor Marketplace.

Covers:
- Phase 2: Service listings CRUD & Subscription tier limits
- Phase 3: Advanced search and filtering
- Phase 4: Request-a-Quote (RFQ) multi-vendor submission & quotation lifecycle
- Phase 5: Inquiry & booking dashboards
- Phase 6: Booking creation, commission calculation (Model A), payment webhook confirmation, completion
- Phase 11: Vendor verification submission & admin approval
- Phase 12: Verified reviews (only for completed bookings) & vendor responses
- Phases 7-10: Subscriptions (Model B), Featured Campaigns (Model C), Lead Credits (Model D), and Payouts
"""

from __future__ import annotations

import hmac
import hashlib
import json
import uuid
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.vendor import (
    Vendor,
    VendorBooking,
    VendorFeaturedCampaign,
    VendorPayout,
    VendorQuotation,
    VendorQuoteRequest,
    VendorReview,
    VendorServiceListing,
    VendorSubscription,
    VendorTransaction,
    VendorVerificationRequest,
)


def _paystack_signature(payload_bytes: bytes) -> str:
    key = settings.PAYSTACK_SECRET_KEY
    raw = key.get_secret_value() if hasattr(key, "get_secret_value") else str(key)
    secret = raw.encode("utf-8")
    return hmac.new(secret, payload_bytes, hashlib.sha512).hexdigest()


class TestVendorMarketplaceE2E:
    async def _setup_vendor(self, client: AsyncClient, user_headers) -> dict:
        """Helper to create a test vendor."""
        res = await client.post(
            "/api/v1/vendors",
            json={
                "business_name": "Apex Visuals & Sound",
                "category": "photography",
                "cover_image_url": "https://example.com/cover.jpg",
                "location_city": "Lagos",
                "location_country": "NG",
                "price_range": "mid",
                "description": "Premium event photography and cinematography studio based in Lagos.",
                "tagline": "Capturing timeless moments",
                "service_areas": ["Lagos", "Abuja", "London"],
                "starting_price": 50000.0,
                "currency": "NGN",
            },
            headers=user_headers,
        )
        assert res.status_code == 201
        return res.json()["data"]

    async def test_service_listings_crud_and_tier_limits(
        self, client: AsyncClient, user_headers
    ):
        vendor_data = await self._setup_vendor(client, user_headers)
        vendor_id = vendor_data["id"]

        # 1. Create Service Listing 1
        res1 = await client.post(
            "/api/v1/vendors/me/services",
            json={
                "title": "Full-Day Wedding Photography",
                "category": "photography",
                "description": "Coverage by 2 photographers, photobook included",
                "pricing_type": "fixed",
                "price": 180000.0,
                "currency": "NGN",
                "duration_hours": 8,
                "inclusions": ["2 photographers", "300 edited photos", "Online gallery"],
            },
            headers=user_headers,
        )
        assert res1.status_code == 201
        service1_id = res1.json()["data"]["id"]

        # 2. Create Service Listing 2
        res2 = await client.post(
            "/api/v1/vendors/me/services",
            json={
                "title": "Drone Aerial Coverage",
                "category": "videography",
                "description": "4K aerial video and panoramic venue captures",
                "pricing_type": "fixed",
                "price": 75000.0,
                "currency": "NGN",
                "duration_hours": 3,
            },
            headers=user_headers,
        )
        assert res2.status_code == 201
        service2_id = res2.json()["data"]["id"]

        # 3. Create Service Listing 3 on Free Plan -> should fail tier limit (Free max 2 services)
        res3 = await client.post(
            "/api/v1/vendors/me/services",
            json={
                "title": "Photo Booth Setup",
                "category": "photography",
                "description": "Interactive photo booth with instant prints",
                "pricing_type": "fixed",
                "price": 60000.0,
            },
            headers=user_headers,
        )
        assert res3.status_code in (400, 403)
        err_msg = res3.json().get("detail") or res3.json().get("error", {}).get("message", "")
        assert any(word in err_msg.lower() for word in ["permits", "upgrade", "limit"])

        # 4. Update Service Listing 1 (PATCH)
        res_update = await client.patch(
            f"/api/v1/vendors/me/services/{service1_id}",
            json={"price": 195000.0, "title": "Deluxe Wedding Photography"},
            headers=user_headers,
        )
        assert res_update.status_code == 200
        assert res_update.json()["data"]["price"] == 195000.0

        # 5. List vendor services
        res_list = await client.get(f"/api/v1/vendors/{vendor_id}/services")
        assert res_list.status_code == 200
        services = res_list.json()["data"]
        assert len(services) == 2

        # 6. Delete Service Listing 2
        res_del = await client.delete(
            f"/api/v1/vendors/me/services/{service2_id}",
            headers=user_headers,
        )
        assert res_del.status_code in (200, 204)

        # Verify only 1 remaining
        res_list2 = await client.get(f"/api/v1/vendors/{vendor_id}/services")
        assert len(res_list2.json()["data"]) == 1

    async def test_advanced_marketplace_search_and_filter(
        self, client: AsyncClient, user_headers
    ):
        await self._setup_vendor(client, user_headers)

        # Search by query
        res_q = await client.get("/api/v1/vendors?q=Apex&category=photography")
        assert res_q.status_code == 200
        data = res_q.json()["data"]
        assert any(v["business_name"] == "Apex Visuals & Sound" for v in data)

        # Search with non-matching category
        res_none = await client.get("/api/v1/vendors?category=catering")
        assert res_none.status_code == 200
        data_none = res_none.json()["data"]
        assert not any(v["business_name"] == "Apex Visuals & Sound" for v in data_none)

    async def test_rfq_quotation_booking_and_payment_flow(
        self, client: AsyncClient, user_headers, other_headers, db: AsyncSession
    ):
        # 1. Setup vendor (user_headers is the vendor)
        vendor_data = await self._setup_vendor(client, user_headers)
        vendor_id = vendor_data["id"]

        # 2. Requester (other_user_headers) submits an RFQ
        rfq_res = await client.post(
            "/api/v1/vendors/quotes/requests",
            json={
                "event_name": "International Tech Gala 2026",
                "service_category": "photography",
                "event_type": "Conference",
                "event_date": "2026-11-20T10:00:00Z",
                "event_location": "Eko Hotel Convention Centre, Lagos",
                "expected_attendance": 500,
                "budget_min": 150000.0,
                "budget_max": 300000.0,
                "requirements": "Full keynote and award coverage with instant highlight reel.",
                "preferred_deadline": "2026-11-01T00:00:00Z",
                "vendor_ids": [vendor_id],
            },
            headers=other_headers,
        )
        assert rfq_res.status_code == 201
        rfq_data = rfq_res.json()["data"]
        rfq_id = rfq_data["id"]

        # 3. Vendor checks inquiries
        inq_res = await client.get("/api/v1/vendors/me/inquiries", headers=user_headers)
        assert inq_res.status_code == 200
        inquiries = inq_res.json()["data"]
        assert len(inquiries) >= 1
        recipient_id = inquiries[0]["recipient_id"]

        # 4. Vendor uploads quotation document and submits an itemized quotation
        doc_upload = await client.post(
            "/api/v1/vendors/upload-document",
            files={"file": ("TechGala_Quotation.pdf", b"%PDF-1.4 mock quotation content", "application/pdf")},
            headers=user_headers,
        )
        assert doc_upload.status_code == 200
        doc_url = doc_upload.json()["data"]["url"]
        doc_filename = doc_upload.json()["data"]["filename"]
        assert doc_url is not None
        assert doc_filename == "TechGala_Quotation.pdf"

        quote_res = await client.post(
            f"/api/v1/vendors/quotes/inquiries/{recipient_id}/respond",
            json={
                "title": "Complete Conference Media Package",
                "scope_of_work": "We provide 3 4K cameras and 2 dedicated editors for live turnarounds.",
                "total_amount": 250000.0,
                "currency": "NGN",
                "items": [
                    {"description": "Keynote 4K Video Recording", "amount": 150000.0},
                    {"description": "Live Highlight Reel Delivery", "amount": 100000.0},
                ],
                "valid_until": "2026-11-10T00:00:00Z",
                "notes": "50% non-refundable if cancelled within 7 days.",
                "attachment_url": doc_url,
                "attachment_name": doc_filename,
            },
            headers=user_headers,
        )
        assert quote_res.status_code == 201
        quotation_data = quote_res.json()["data"]
        quotation_id = quotation_data["id"]
        assert quotation_data["total_amount"] == 250000.0
        assert quotation_data["attachment_url"] == doc_url
        assert quotation_data["attachment_name"] == "TechGala_Quotation.pdf"

        # 5. Requester accepts quotation (which automatically initializes the booking)
        accept_res = await client.post(
            f"/api/v1/vendors/quotations/{quotation_id}/accept",
            headers=other_headers,
        )
        assert accept_res.status_code == 200
        accept_data = accept_res.json()["data"]
        assert accept_data["quotation"]["status"] == "accepted"
        booking_data = accept_data["booking"]
        booking_id = booking_data["id"]
        payment_reference = booking_data["payment_reference"]
        assert booking_data["status"] == "pending_payment"
        # Verify Model A Commission: 10% default
        assert booking_data["total_amount"] == 250000.0
        assert booking_data["commission_amount"] == 25000.0
        assert booking_data["vendor_earnings"] == 225000.0

        # 7. Simulate Paystack payment webhook
        webhook_body = json.dumps({
            "event": "charge.success",
            "data": {
                "reference": payment_reference,
                "amount": 25000000,  # 250,000 NGN in kobo
                "currency": "NGN",
                "status": "success",
            },
        }).encode("utf-8")

        sig = _paystack_signature(webhook_body)
        pay_res = await client.post(
            "/api/v1/webhooks/paystack",
            content=webhook_body,
            headers={"x-paystack-signature": sig, "content-type": "application/json"},
        )
        assert pay_res.status_code == 200

        # Verify booking is now confirmed
        booking_check = await client.get(
            "/api/v1/vendors/me/bookings",
            headers=user_headers,
        )
        assert booking_check.status_code == 200
        bookings = booking_check.json()["data"]
        matching = [b for b in bookings if b["id"] == booking_id]
        assert len(matching) == 1
        assert matching[0]["status"] == "confirmed"

        # 8. Vendor completes booking after event fulfillment
        complete_res = await client.post(
            f"/api/v1/vendors/bookings/{booking_id}/complete",
            headers=user_headers,
        )
        assert complete_res.status_code == 200
        assert complete_res.json()["data"]["status"] == "completed"

        # Verify vendor payable balance was credited with 225,000 NGN
        vendor_db = await db.get(Vendor, uuid.UUID(vendor_id))
        assert vendor_db.payable_balance == 225000.0
        assert vendor_db.total_earned == 225000.0

        # 9. Requester leaves a verified review (Phase 12)
        review_res = await client.post(
            f"/api/v1/vendors/bookings/{booking_id}/reviews",
            json={
                "rating": 5,
                "title": "Superb Experience",
                "content": "Exceptional team! Incredible image quality and ultra fast turnaround.",
            },
            headers=other_headers,
        )
        assert review_res.status_code == 201
        review_data = review_res.json()["data"]
        review_id = review_data["id"]
        assert review_data["rating"] == 5

        # Check vendor rating updated
        await db.refresh(vendor_db)
        assert vendor_db.rating_avg == 5.0
        assert vendor_db.reviews_count == 1

        # 10. Vendor responds to the review
        resp_res = await client.post(
            f"/api/v1/vendors/reviews/{review_id}/respond",
            json={"response": "Thank you so much! It was an absolute honour working with your team."},
            headers=user_headers,
        )
        assert resp_res.status_code == 200
        assert "honour" in resp_res.json()["data"]["response_from_vendor"]

    async def test_vendor_verification_workflow(
        self, client: AsyncClient, user_headers, admin_headers, db: AsyncSession
    ):
        vendor_data = await self._setup_vendor(client, user_headers)

        # 1. Vendor submits verification documents
        verif_res = await client.post(
            "/api/v1/vendors/me/verification",
            json={
                "business_registration_number": "RC-1928374",
                "tax_id": "TIN-98765432",
                "document_urls": ["https://example.com/cac_cert.pdf"],
                "government_id_url": "https://example.com/director_id.pdf",
                "notes": "CAC registered company since 2018.",
            },
            headers=user_headers,
        )
        assert verif_res.status_code == 201
        req_id = verif_res.json()["data"]["id"]

        # 2. Admin reviews and approves
        admin_res = await client.post(
            f"/api/v1/vendors/verification/requests/{req_id}/review?approved=true",
            headers=admin_headers,
        )
        assert admin_res.status_code == 200
        assert admin_res.json()["data"]["status"] == "approved"

        # Verify vendor is verified
        vendor_obj = await db.get(Vendor, uuid.UUID(vendor_data["id"]))
        assert vendor_obj.is_verified is True
        assert vendor_obj.verification_status == "verified"

    async def test_vendor_monetization_models_and_payout(
        self, client: AsyncClient, user_headers, admin_headers, db: AsyncSession
    ):
        vendor_data = await self._setup_vendor(client, user_headers)
        vendor_id = vendor_data["id"]

        # Model B: Subscription Upgrade
        res_sub = await client.post(
            "/api/v1/vendors/me/subscriptions/checkout",
            json={"tier": "pro"},
            headers=user_headers,
        )
        assert res_sub.status_code == 200
        assert res_sub.json()["data"]["tier"] == "pro"

        vendor_db = await db.get(Vendor, uuid.UUID(vendor_id))
        assert vendor_db.subscription_tier == "pro"
        assert vendor_db.lead_credits_balance == 20  # Pro gives 20 credits

        # Model C: Featured Campaign
        res_feat = await client.post(
            "/api/v1/vendors/me/campaigns/checkout",
            json={"placement": "marketplace_top", "duration_days": 30},
            headers=user_headers,
        )
        assert res_feat.status_code == 200
        await db.refresh(vendor_db)
        assert vendor_db.is_featured is True

        # Model D: Lead Credits purchase
        res_lead = await client.post(
            "/api/v1/vendors/me/lead-credits/checkout",
            json={"credits_count": 15},
            headers=user_headers,
        )
        assert res_lead.status_code == 200
        await db.refresh(vendor_db)
        assert vendor_db.lead_credits_balance == 35  # 20 + 15

        # Payout Request and Disbursement:
        # Give vendor 100,000 payable balance
        vendor_db.payable_balance = 100000.0
        await db.commit()

        payout_res = await client.post(
            "/api/v1/vendors/me/payout",
            json={
                "amount": 80000.0,
                "method": "manual",
                "account_details": {
                    "bank_code": "058",
                    "bank_name": "GTBank",
                    "account_number": "0123456789",
                    "account_name": "Apex Visuals Enterprise",
                },
            },
            headers=user_headers,
        )
        assert payout_res.status_code == 201
        payout_id = payout_res.json()["data"]["id"]

        # Admin disburses payout
        disburse_res = await client.post(
            f"/api/v1/vendors/admin/payouts/{payout_id}/disburse",
            headers=admin_headers,
        )
        assert disburse_res.status_code == 200
        assert disburse_res.json()["data"]["status"] == "completed"

        await db.refresh(vendor_db)
        assert vendor_db.payable_balance == 20000.0  # 100k - 80k
        assert vendor_db.total_withdrawn == 80000.0
