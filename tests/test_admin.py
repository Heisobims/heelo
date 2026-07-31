"""Admin panel — suspend org, ban user, promote to admin, list views."""

from __future__ import annotations

from httpx import AsyncClient


async def test_admin_overview_requires_admin_role(client: AsyncClient, user_headers):
    resp = await client.get("/api/v1/admin/organizations", headers=user_headers)
    assert resp.status_code == 403


async def test_admin_unauthenticated_returns_401(client: AsyncClient):
    resp = await client.get("/api/v1/admin/organizations")
    assert resp.status_code == 401


async def test_suspend_org(client: AsyncClient, org, admin_headers):
    resp = await client.post(
        f"/api/v1/admin/organizations/{org.id}/suspend",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["is_active"] is False


async def test_reinstate_org(client: AsyncClient, org, admin_headers):
    # Suspend first
    await client.post(f"/api/v1/admin/organizations/{org.id}/suspend", headers=admin_headers)
    # Reinstate
    resp = await client.post(
        f"/api/v1/admin/organizations/{org.id}/reinstate",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["is_active"] is True


async def test_set_org_plan(client: AsyncClient, org, admin_headers):
    resp = await client.patch(
        f"/api/v1/admin/organizations/{org.id}/plan",
        json={"plan": "pro"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["plan"] == "pro"


async def test_set_invalid_org_plan_returns_400(client: AsyncClient, org, admin_headers):
    resp = await client.patch(
        f"/api/v1/admin/organizations/{org.id}/plan",
        json={"plan": "diamond_ultra_tier"},
        headers=admin_headers,
    )
    assert resp.status_code == 400


async def test_ban_user(client: AsyncClient, user, admin_headers):
    resp = await client.post(
        f"/api/v1/admin/users/{user.id}/ban",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["banned"] is True


async def test_unban_user(client: AsyncClient, user, admin_headers):
    await client.post(f"/api/v1/admin/users/{user.id}/ban", headers=admin_headers)
    resp = await client.post(
        f"/api/v1/admin/users/{user.id}/unban",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["banned"] is False


async def test_promote_user_to_admin(client: AsyncClient, user, admin_headers):
    resp = await client.patch(
        f"/api/v1/admin/users/{user.id}/role",
        json={"role": "admin"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "admin"


async def test_set_invalid_role_returns_400(client: AsyncClient, user, admin_headers):
    resp = await client.patch(
        f"/api/v1/admin/users/{user.id}/role",
        json={"role": "superuser_god_mode"},
        headers=admin_headers,
    )
    assert resp.status_code == 400


async def test_banned_user_cannot_login(client: AsyncClient, user, admin_headers):
    # Ban the user
    await client.post(f"/api/v1/admin/users/{user.id}/ban", headers=admin_headers)

    # Try to login — should fail since deleted_at is set
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "password123",
        },
    )
    assert resp.status_code == 401
