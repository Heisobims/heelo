"""Organization CRUD, team management, invite flow."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def test_create_organization(client: AsyncClient, user_headers):
    resp = await client.post(
        "/api/v1/organizations",
        json={"name": "Lagos Tech Hub", "slug": "lagos-tech-hub", "country": "NG"},
        headers=user_headers,
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["name"] == "Lagos Tech Hub"
    assert data["slug"] == "lagos-tech-hub"


async def test_create_org_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/v1/organizations",
        json={"name": "Anon Org", "slug": "anon-org"},
    )
    assert resp.status_code == 401


async def test_create_org_duplicate_slug_returns_409(client: AsyncClient, org, user_headers):
    resp = await client.post(
        "/api/v1/organizations",
        json={"name": "Other Org", "slug": org.slug},
        headers=user_headers,
    )
    assert resp.status_code == 409


async def test_get_organization(client: AsyncClient, org, user_headers):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["slug"] == org.slug


async def test_get_org_as_non_member_returns_403(client: AsyncClient, org, other_headers):
    resp = await client.get(f"/api/v1/organizations/{org.slug}", headers=other_headers)
    assert resp.status_code == 403


async def test_update_organization(client: AsyncClient, org, user_headers):
    resp = await client.patch(
        f"/api/v1/organizations/{org.slug}",
        json={"name": "Updated Org Name"},
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "Updated Org Name"


async def test_invite_team_member(client: AsyncClient, org, other_user, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/members/invite",
        json={"email": other_user.email, "role": "staff"},
        headers=user_headers,
    )
    assert resp.status_code in (200, 201)


async def test_list_org_members(client: AsyncClient, org, user_headers):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/members",
        headers=user_headers,
    )
    assert resp.status_code == 200
    members = resp.json()["data"]
    assert isinstance(members, list)


async def test_list_user_organizations(client: AsyncClient, org, user_headers):
    resp = await client.get("/api/v1/organizations", headers=user_headers)
    assert resp.status_code == 200
    orgs = resp.json()["data"]
    assert any(o["slug"] == org.slug for o in orgs)
