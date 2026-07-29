"""CRM — attendee list, search, filter, CSV export."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def test_list_registrations(
    client: AsyncClient, org, published_event, registration, user_headers
):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/registrations/export.csv",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert b"jane@example.com" in resp.content


async def test_crm_page_requires_auth(client: AsyncClient, org):
    resp = await client.get(f"/org/{org.slug}/registrations")
    # Should redirect to login, not 200
    assert resp.status_code in (302, 401)


async def test_csv_export_contains_headers(
    client: AsyncClient, org, registration, user_headers
):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/registrations/export.csv",
        headers=user_headers,
    )
    assert resp.status_code == 200
    first_line = resp.content.split(b"\n")[0].decode()
    assert "email" in first_line.lower() or "name" in first_line.lower()


async def test_csv_export_for_org_with_no_registrations(
    client: AsyncClient, org, user_headers
):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/registrations/export.csv",
        headers=user_headers,
    )
    assert resp.status_code == 200
    # Just headers row or empty
    assert len(resp.content) > 0


async def test_crm_export_requires_org_membership(
    client: AsyncClient, org, other_headers
):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/registrations/export.csv",
        headers=other_headers,
    )
    assert resp.status_code == 403
