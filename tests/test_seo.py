"""SEO surface added in this pass: robots.txt, sitemap.xml, canonical/OG/
Twitter tags in base.html, JSON-LD on event and vendor pages, and noindex
on private/token-gated pages."""

from __future__ import annotations

import json
import re

from httpx import AsyncClient


def _extract_ld_json(html: str) -> dict:
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert match, "no JSON-LD block found"
    return json.loads(match.group(1))


async def test_robots_txt(client: AsyncClient):
    resp = await client.get("/robots.txt")
    assert resp.status_code == 200
    assert "Disallow: /dashboard" in resp.text
    assert "Disallow: /admin" in resp.text
    assert "Sitemap:" in resp.text


async def test_sitemap_xml_includes_marketing_and_event_pages(client: AsyncClient, published_event):
    resp = await client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    assert f"/e/{published_event.slug}" in resp.text
    assert "<loc>" in resp.text and "/pricing</loc>" in resp.text


async def test_sitemap_excludes_draft_events(client: AsyncClient, event):
    """`event` fixture is status=draft - must never appear in the sitemap."""
    resp = await client.get("/sitemap.xml")
    assert f"/e/{event.slug}" not in resp.text


async def test_landing_page_has_canonical_and_og_tags(client: AsyncClient):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert '<link rel="canonical" href="http://test/">' in resp.text
    assert 'property="og:url" content="http://test/"' in resp.text
    assert 'property="og:type" content="website"' in resp.text
    assert 'name="twitter:title"' in resp.text


async def test_event_page_has_valid_event_json_ld(
    client: AsyncClient, published_event, ticket_type
):
    resp = await client.get(f"/e/{published_event.slug}")
    assert resp.status_code == 200
    data = _extract_ld_json(resp.text)
    assert data["@type"] == "Event"
    assert data["name"] == published_event.title
    assert data["offers"][0]["price"] == 5000.0


async def test_vendor_page_has_valid_local_business_json_ld(client: AsyncClient, vendor):
    resp = await client.get(f"/vendors/{vendor.slug}")
    assert resp.status_code == 200
    data = _extract_ld_json(resp.text)
    assert data["@type"] == "LocalBusiness"
    assert data["name"] == vendor.business_name


async def test_vendor_page_has_og_overrides(client: AsyncClient, vendor):
    resp = await client.get(f"/vendors/{vendor.slug}")
    assert f'property="og:title" content="{vendor.business_name}"' in resp.text


async def test_dashboard_pages_are_noindex(client: AsyncClient, user, org):
    """Defense-in-depth on top of robots.txt's Disallow: /org/ - an
    externally-linked dashboard page must still tell crawlers not to index
    it if they somehow reach it."""
    login = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "password123"}
    )
    assert login.status_code == 200

    resp = await client.get(f"/org/{org.slug}")
    assert resp.status_code == 200
    assert 'name="robots" content="noindex, nofollow"' in resp.text


async def test_sponsor_invite_claim_page_is_noindex(
    client: AsyncClient, org, published_event, user_headers
):
    import uuid

    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/events/{published_event.id}/sponsors",
        json={"name": "SEO Test Sponsor"},
        headers=user_headers,
    )
    sponsor_id = resp.json()["data"]["id"]

    from app.services import sponsor_service as sp_svc

    token = sp_svc._make_sponsor_invite_token(uuid.UUID(sponsor_id))

    resp = await client.get(f"/sponsor-invite/{token}")
    assert resp.status_code == 200
    assert 'name="robots" content="noindex, nofollow"' in resp.text
