"""Event lifecycle transitions at the HTTP layer - go-live, cancel, end, and
cover/gallery image uploads. Previously these were exercised only by setting
Event.status directly on fixtures (e.g. test_certificates.py), never through
the actual endpoints - so the transition guards themselves (only published
events can go live, only live/published events can end, etc.) had no
coverage."""

from __future__ import annotations

from io import BytesIO

from httpx import AsyncClient
from PIL import Image


def _jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (100, 100), color="green").save(buf, format="JPEG")
    return buf.getvalue()


# ── go-live ──────────────────────────────────────────────────────────────────


async def test_go_live_from_published(client: AsyncClient, org, published_event, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/go-live",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "live"


async def test_go_live_rejects_draft_event(client: AsyncClient, org, event, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/go-live",
        headers=user_headers,
    )
    assert resp.status_code == 400


# ── cancel ───────────────────────────────────────────────────────────────────


async def test_cancel_published_event(client: AsyncClient, org, published_event, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/cancel",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"


async def test_cancel_already_cancelled_event_returns_400(
    client: AsyncClient, org, published_event, user_headers
):
    url = f"/api/v1/organizations/{org.slug}/events/{published_event.id}/cancel"
    first = await client.post(url, headers=user_headers)
    second = await client.post(url, headers=user_headers)
    assert first.status_code == 200
    assert second.status_code == 400


# ── end ──────────────────────────────────────────────────────────────────────


async def test_end_live_event(client: AsyncClient, org, published_event, user_headers):
    base = f"/api/v1/organizations/{org.slug}/events/{published_event.id}"
    await client.post(f"{base}/go-live", headers=user_headers)

    resp = await client.post(f"{base}/end", headers=user_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ended"


async def test_end_published_event_without_going_live_first(
    client: AsyncClient, org, published_event, user_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/end",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ended"


async def test_end_draft_event_returns_400(client: AsyncClient, org, event, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{event.id}/end",
        headers=user_headers,
    )
    assert resp.status_code == 400


async def test_certificates_can_only_be_generated_after_end(
    client: AsyncClient, org, published_event, user_headers
):
    """Regression coverage tying the /end transition to the certificate
    availability gate - generating certificates before the event has
    actually been ended through the endpoint must fail."""
    base = f"/api/v1/organizations/{org.slug}/events/{published_event.id}"

    too_early = await client.post(f"{base}/certificates/generate", headers=user_headers)
    assert too_early.status_code == 400

    await client.post(f"{base}/end", headers=user_headers)

    now_ok = await client.post(f"{base}/certificates/generate", headers=user_headers)
    assert now_ok.status_code == 200


# ── Cover / gallery uploads ─────────────────────────────────────────────────────


async def test_upload_cover_image(client: AsyncClient, org, published_event, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/cover",
        files={"cover": ("cover.jpg", _jpeg_bytes(), "image/jpeg")},
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["cover_image_url"]


async def test_upload_cover_rejects_non_image_content_type(
    client: AsyncClient, org, published_event, user_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/cover",
        files={"cover": ("cover.txt", b"not an image", "text/plain")},
        headers=user_headers,
    )
    assert resp.status_code == 400


async def test_upload_gallery_image_valid_slot(
    client: AsyncClient, org, published_event, user_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/gallery/1",
        files={"image": ("gallery.jpg", _jpeg_bytes(), "image/jpeg")},
        headers=user_headers,
    )
    assert resp.status_code == 200


async def test_upload_gallery_image_rejects_invalid_slot(
    client: AsyncClient, org, published_event, user_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/gallery/3",
        files={"image": ("gallery.jpg", _jpeg_bytes(), "image/jpeg")},
        headers=user_headers,
    )
    assert resp.status_code == 400


# ── Permission gating on lifecycle endpoints ──────────────────────────────────


async def test_checkin_staff_cannot_go_live(
    client: AsyncClient, org, published_event, checkin_staff_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/go-live",
        headers=checkin_staff_headers,
    )
    assert resp.status_code == 403


async def test_checkin_staff_cannot_cancel_event(
    client: AsyncClient, org, published_event, checkin_staff_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/cancel",
        headers=checkin_staff_headers,
    )
    assert resp.status_code == 403
