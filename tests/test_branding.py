"""Org branding — brand_color accent color, plus the update_organization fix
that makes explicitly clearing a field (e.g. removing the brand color) via
the settings form actually persist instead of being silently ignored.
"""

from __future__ import annotations

from httpx import AsyncClient


class TestBrandColor:
    async def test_set_brand_color(self, client: AsyncClient, org, user_headers):
        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}",
            json={"brand_color": "#FF3ECB"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["brand_color"] == "#FF3ECB"

    async def test_invalid_brand_color_rejected(self, client: AsyncClient, org, user_headers):
        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}",
            json={"brand_color": "not-a-color"},
            headers=user_headers,
        )
        assert resp.status_code == 422

    async def test_explicit_null_clears_a_field(self, client: AsyncClient, org, user_headers):
        """Regression test: update_organization used to dump with
        exclude_none=True, so sending an explicit null (e.g. from the
        settings page's "clear this field" flow) was silently dropped
        instead of clearing the stored value."""
        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}",
            json={"website": "https://example.com"},
            headers=user_headers,
        )
        assert resp.json()["data"]["website"] == "https://example.com"

        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}",
            json={"website": None},
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["website"] is None

    async def test_public_event_page_reflects_brand_color(
        self, client: AsyncClient, org, published_event, user_headers
    ):
        await client.patch(
            f"/api/v1/organizations/{org.slug}",
            json={"brand_color": "#123ABC"},
            headers=user_headers,
        )
        resp = await client.get(f"/e/{published_event.slug}")
        assert resp.status_code == 200
        assert "#123ABC" in resp.text

    async def test_register_page_reflects_brand_color(
        self, client: AsyncClient, org, published_event, ticket_type, user_headers
    ):
        await client.patch(
            f"/api/v1/organizations/{org.slug}",
            json={"brand_color": "#123ABC"},
            headers=user_headers,
        )
        resp = await client.get(f"/e/{published_event.slug}/register")
        assert resp.status_code == 200
        assert "#123ABC" in resp.text
