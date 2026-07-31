"""API key management — create, list, revoke."""

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
