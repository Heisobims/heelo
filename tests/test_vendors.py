"""Vendor signup — image upload endpoint, required profile image, and the
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
    # `vendor` fixture belongs to `other_user`, not `user` — create a fresh
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
