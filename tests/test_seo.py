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


def _extract_all_ld_json(html: str) -> list[dict]:
    matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    return [json.loads(m) for m in matches]


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


async def test_robots_txt_disallows_sensitive_paths(client: AsyncClient):
    resp = await client.get("/robots.txt")
    assert resp.status_code == 200
    assert "Disallow: /orders/" in resp.text
    assert "Disallow: /payments/" in resp.text
    assert "Disallow: /billing/" in resp.text
    assert "Disallow: /booths/" in resp.text
    assert "Disallow: /feedback/" in resp.text
    assert "Disallow: /messages" in resp.text
    assert "Allow: /events" in resp.text
    assert "Allow: /venues" in resp.text


async def test_auth_pages_have_noindex_follow(client: AsyncClient):
    for path in ["/login", "/register", "/forgot-password"]:
        resp = await client.get(path)
        assert resp.status_code == 200
        assert 'name="robots" content="noindex, follow"' in resp.text


async def test_landing_page_has_website_and_faq_schema(client: AsyncClient):
    resp = await client.get("/")
    assert resp.status_code == 200
    blocks = _extract_all_ld_json(resp.text)
    assert len(blocks) >= 1
    graph = blocks[0].get("@graph", [])
    types = [item.get("@type") for item in graph]
    assert "WebSite" in types
    assert "Organization" in types
    assert "FAQPage" in types


async def test_pricing_page_has_faq_and_breadcrumbs(client: AsyncClient):
    resp = await client.get("/pricing")
    assert resp.status_code == 200
    blocks = _extract_all_ld_json(resp.text)
    assert len(blocks) >= 1
    graph = blocks[0].get("@graph", [])
    types = [item.get("@type") for item in graph]
    assert "BreadcrumbList" in types
    assert "FAQPage" in types


async def test_event_page_has_rich_schema_and_breadcrumbs(
    client: AsyncClient, published_event, ticket_type
):
    resp = await client.get(f"/e/{published_event.slug}")
    assert resp.status_code == 200
    blocks = _extract_all_ld_json(resp.text)
    assert len(blocks) >= 2
    types = [b.get("@type") for b in blocks]
    assert "Event" in types
    assert "BreadcrumbList" in types
    event_block = next(b for b in blocks if b.get("@type") == "Event")
    assert event_block["inLanguage"] == "en"
    assert "eventStatus" in event_block


async def test_speaker_page_has_person_and_breadcrumbs(
    client: AsyncClient, org, published_event, user_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/speakers",
        json={"name": "Grace Hopper", "title": "Chief Scientist"},
        headers=user_headers,
    )
    assert resp.status_code == 201
    speaker_data = resp.json()["data"]

    resp = await client.get(f"/speakers/{speaker_data['slug']}")
    assert resp.status_code == 200
    blocks = _extract_all_ld_json(resp.text)
    types = [b.get("@type") for b in blocks]
    assert "Person" in types
    assert "BreadcrumbList" in types


async def test_programmatic_category_and_city_routes(client: AsyncClient, published_event):
    resp_cat = await client.get("/events/category/tech")
    assert resp_cat.status_code == 200
    assert "/events/category/tech" in resp_cat.text

    resp_city = await client.get("/events/city/lagos")
    assert resp_city.status_code == 200
    assert "/events/city/lagos" in resp_city.text


async def test_sitemap_xml_includes_venues_and_categories(client: AsyncClient, published_event):
    resp = await client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "/venues</loc>" in resp.text
    assert "/events/category/" in resp.text

