"""Vendor signup - image upload endpoint, required profile image, and the
portfolio_urls/portfolio_link fields."""

from __future__ import annotations

from io import BytesIO

from httpx import AsyncClient
from PIL import Image


def _jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (100, 100), color="blue").save(buf, format="JPEG")
    return buf.getvalue()


def _vendor_payload(**overrides) -> dict:
    payload = {
        "business_name": "Lagos Lens Co.",
        "category": "photography",
        "cover_image_url": "https://example.com/cover.jpg",
    }
    payload.update(overrides)
    return payload


async def test_create_vendor_requires_cover_image(client: AsyncClient, user_headers):
    resp = await client.post(
        "/api/v1/vendors",
        json={"business_name": "Lagos Lens Co.", "category": "photography"},
        headers=user_headers,
    )
    assert resp.status_code == 422


async def test_create_vendor_with_cover_image_succeeds(client: AsyncClient, user_headers):
    resp = await client.post(
        "/api/v1/vendors",
        json=_vendor_payload(),
        headers=user_headers,
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["cover_image_url"] == "https://example.com/cover.jpg"
    assert data["portfolio_urls"] == []
    assert data["portfolio_link"] is None


async def test_create_vendor_with_portfolio_samples_and_link(client: AsyncClient, user_headers):
    resp = await client.post(
        "/api/v1/vendors",
        json=_vendor_payload(
            portfolio_urls=["https://example.com/1.jpg", "https://example.com/2.jpg"],
            portfolio_link="https://instagram.com/lagoslens",
        ),
        headers=user_headers,
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert len(data["portfolio_urls"]) == 2
    assert data["portfolio_link"] == "https://instagram.com/lagoslens"


async def test_create_vendor_rejects_more_than_three_portfolio_samples(
    client: AsyncClient, user_headers
):
    resp = await client.post(
        "/api/v1/vendors",
        json=_vendor_payload(
            portfolio_urls=[
                "https://example.com/1.jpg",
                "https://example.com/2.jpg",
                "https://example.com/3.jpg",
                "https://example.com/4.jpg",
            ]
        ),
        headers=user_headers,
    )
    assert resp.status_code == 422


async def test_upload_vendor_image_returns_url(client: AsyncClient, user_headers):
    resp = await client.post(
        "/api/v1/vendors/upload-image",
        headers=user_headers,
        files={"file": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200
    url = resp.json()["data"]["url"]
    assert url


async def test_upload_vendor_image_rejects_bad_content_type(client: AsyncClient, user_headers):
    resp = await client.post(
        "/api/v1/vendors/upload-image",
        headers=user_headers,
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400


async def test_update_vendor_profile_can_set_images(
    client: AsyncClient, user_headers, vendor, user
):
    # `vendor` fixture belongs to `other_user`, not `user` - create a fresh
    # profile owned by `user` instead so PATCH /me resolves to it.
    create = await client.post(
        "/api/v1/vendors",
        json=_vendor_payload(business_name="Studio Two"),
        headers=user_headers,
    )
    assert create.status_code == 201

    resp = await client.patch(
        "/api/v1/vendors/me",
        json={
            "cover_image_url": "https://example.com/new-cover.jpg",
            "portfolio_link": "https://behance.net/studiotwo",
        },
        headers=user_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["cover_image_url"] == "https://example.com/new-cover.jpg"
    assert data["portfolio_link"] == "https://behance.net/studiotwo"


# ── QR code ──────────────────────────────────────────────────────────────────


async def test_vendor_qr_code_returns_png(client: AsyncClient, vendor, other_headers):
    resp = await client.get("/api/v1/vendors/me/qr.png", headers=other_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_vendor_qr_code_requires_auth(client: AsyncClient, vendor):
    resp = await client.get("/api/v1/vendors/me/qr.png")
    assert resp.status_code == 401


async def test_vendor_qr_code_404_without_a_vendor_profile(client: AsyncClient, user_headers):
    resp = await client.get("/api/v1/vendors/me/qr.png", headers=user_headers)
    assert resp.status_code == 404


def _access_cookie(user_id) -> dict:
    from datetime import UTC, datetime, timedelta

    from jose import jwt

    from app.config import settings

    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(hours=1), "type": "access"},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return {"heelo_access": token}


async def test_vendor_detail_page_shows_qr_section_to_owner(
    client: AsyncClient, vendor, other_user
):
    resp = await client.get(f"/vendors/{vendor.slug}", cookies=_access_cookie(other_user.id))
    assert resp.status_code == 200
    assert b"Your QR code" in resp.content


async def test_vendor_detail_page_hides_qr_section_from_anonymous_visitor(
    client: AsyncClient, vendor
):
    resp = await client.get(f"/vendors/{vendor.slug}")
    assert resp.status_code == 200
    assert b"Your QR code" not in resp.content


async def test_vendor_detail_page_hides_qr_section_from_a_different_logged_in_user(
    client: AsyncClient, vendor, user
):
    """Regression test: is_owner must compare against the actual vendor's
    user_id, not just "is someone logged in" - otherwise any logged-in
    visitor would see another vendor's QR download link."""
    resp = await client.get(f"/vendors/{vendor.slug}", cookies=_access_cookie(user.id))
    assert resp.status_code == 200
    assert b"Your QR code" not in resp.content


async def test_my_vendor_dashboard_page_for_owner(
    client: AsyncClient, vendor, other_user
):
    resp = await client.get("/my-vendor-dashboard", cookies=_access_cookie(other_user.id))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert vendor.business_name.encode() in resp.content
    assert b"Vendor Command Center" in resp.content
    assert b"Withdraw Earnings" in resp.content
    # Verify that the 3 interactive action modals are rendered within Alpine scope
    assert b"showPayoutModal" in resp.content
    assert b"showServiceModal" in resp.content
    assert b"showQuoteModal" in resp.content
    assert b"Add Service Package" in resp.content
    assert b"Withdraw Payable Earnings" in resp.content
    assert b"Submit Quotation" in resp.content
    # Confirm modals are enclosed before </script> and within component
    content = resp.text
    modal_idx = content.find("showPayoutModal")
    script_idx = content.find("function vendorHub()")
    assert modal_idx < script_idx



async def test_my_vendor_dashboard_redirects_unauthenticated(client: AsyncClient):
    resp = await client.get("/my-vendor-dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["location"]


async def test_my_vendor_dashboard_redirects_user_without_vendor(client: AsyncClient, user):
    resp = await client.get("/my-vendor-dashboard", cookies=_access_cookie(user.id), follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/vendor-signup"


async def test_upload_vendor_document_success(client: AsyncClient, user_headers):
    # Test PDF upload
    pdf_resp = await client.post(
        "/api/v1/vendors/upload-document",
        files={"file": ("quote_proposal.pdf", b"%PDF-1.4 mock quotation pdf", "application/pdf")},
        headers=user_headers,
    )
    assert pdf_resp.status_code == 200
    pdf_data = pdf_resp.json()["data"]
    assert pdf_data["filename"] == "quote_proposal.pdf"
    assert pdf_data["url"].endswith(".pdf")

    # Test Image upload (JPEG)
    img_resp = await client.post(
        "/api/v1/vendors/upload-document",
        files={"file": ("estimate_scan.jpg", _jpeg_bytes(), "image/jpeg")},
        headers=user_headers,
    )
    assert img_resp.status_code == 200
    img_data = img_resp.json()["data"]
    assert img_data["filename"] == "estimate_scan.jpg"
    assert img_data["url"].endswith(".jpg")


async def test_upload_vendor_document_rejects_invalid_format(client: AsyncClient, user_headers):
    resp = await client.post(
        "/api/v1/vendors/upload-document",
        files={"file": ("malicious.exe", b"binary content", "application/x-msdownload")},
        headers=user_headers,
    )
    assert resp.status_code == 400
    body = resp.json()
    err_msg = body.get("detail") or body.get("error", {}).get("message", "")
    assert "Unsupported file format" in err_msg

