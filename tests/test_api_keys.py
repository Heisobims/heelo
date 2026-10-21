"""API key management - create, list, revoke."""

from __future__ import annotations

from httpx import AsyncClient


async def test_create_api_key(client: AsyncClient, org, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/api-keys",
        json={"name": "Production"},
        headers=user_headers,
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["key"].startswith("hlo_live_")
    assert len(data["key"]) == len("hlo_live_") + 64
    assert "warning" in resp.json()


async def test_api_key_not_shown_in_list(client: AsyncClient, org, user_headers):
    await client.post(
        f"/api/v1/organizations/{org.slug}/api-keys",
        json={"name": "Prod Key"},
        headers=user_headers,
    )
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/api-keys",
        headers=user_headers,
    )
    assert resp.status_code == 200
    for k in resp.json()["data"]:
        # key prefix should be there, but not full key
        assert "key" not in k or k.get("key") is None
        assert "key_prefix" in k
        assert k["key_prefix"].startswith("hlo_live_")


async def test_list_api_keys(client: AsyncClient, org, api_key, user_headers):
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/api-keys",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


async def test_revoke_api_key(client: AsyncClient, org, api_key, user_headers):
    _, key = api_key
    resp = await client.delete(
        f"/api/v1/organizations/{org.slug}/api-keys/{key.id}",
        headers=user_headers,
    )
    assert resp.status_code == 200

    # Key should be marked inactive in list
    list_resp = await client.get(
        f"/api/v1/organizations/{org.slug}/api-keys",
        headers=user_headers,
    )
    keys = list_resp.json()["data"]
    matching = [k for k in keys if k["id"] == str(key.id)]
    assert len(matching) == 1
    assert matching[0]["is_active"] is False


async def test_revoke_nonexistent_key_returns_404(client: AsyncClient, org, user_headers):
    import uuid

    resp = await client.delete(
        f"/api/v1/organizations/{org.slug}/api-keys/{uuid.uuid4()}",
        headers=user_headers,
    )
    assert resp.status_code == 404


async def test_non_member_cannot_create_api_key(client: AsyncClient, org, other_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/api-keys",
        json={"name": "Sneaky Key"},
        headers=other_headers,
    )
    assert resp.status_code == 403


async def test_list_api_keys_rejects_checkin_staff(client: AsyncClient, org, checkin_staff_headers):
    """Regression test: list_keys was the one endpoint in this file still
    using bare org membership instead of ApiKeysManageAccess, so a
    checkin_staff login could enumerate live API key prefixes/metadata."""
    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/api-keys",
        headers=checkin_staff_headers,
    )
    assert resp.status_code == 403


async def test_developer_settings_page_renders(client: AsyncClient, org, user, db):
    login = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "password123"}
    )
    assert login.status_code == 200

    resp = await client.get(f"/org/{org.slug}/settings/developer")
    assert resp.status_code == 200
    assert "Developer Platform" in resp.text
    assert "Secret API Keys" in resp.text
    assert "Webhook Subscriptions" in resp.text
    assert "Integration Quickstart" in resp.text

