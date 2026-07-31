"""Auth flow — register, login, token refresh, logout."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def test_register_creates_unverified_user(client: AsyncClient, db: AsyncSession):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Alice Smith",
            "email": "alice@example.com",
            "password": "Str0ngP@ss!",
            "role": "organizer",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["success"] is True
    assert "access_token" not in data.get("data", {})


async def test_register_duplicate_email_returns_409(client: AsyncClient, user):
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Dup User",
            "email": user.email,
            "password": "Str0ngP@ss!",
            "role": "organizer",
        },
    )
    assert resp.status_code == 409


async def test_login_returns_tokens(client: AsyncClient, user):
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "password123",
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "access_token" in data
    assert "refresh_token" in data


async def test_login_wrong_password_returns_401(client: AsyncClient, user):
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "wrongpassword",
        },
    )
    assert resp.status_code == 401


async def test_login_unknown_email_returns_401(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "nobody@example.com",
            "password": "password123",
        },
    )
    assert resp.status_code == 401


async def test_access_protected_endpoint_with_valid_token(client: AsyncClient, user_headers):
    resp = await client.get("/api/v1/organizations", headers=user_headers)
    # 200 or empty list — just not 401
    assert resp.status_code != 401


async def test_access_protected_endpoint_without_token(client: AsyncClient):
    resp = await client.get("/api/v1/organizations")
    assert resp.status_code == 401


async def test_access_protected_endpoint_with_invalid_token(client: AsyncClient):
    resp = await client.get(
        "/api/v1/organizations",
        headers={"Authorization": "Bearer totally.invalid.token"},
    )
    assert resp.status_code == 401


async def test_logout_succeeds(client: AsyncClient, user_headers):
    # First login to get a real refresh token
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "organizer@example.com",
            "password": "password123",
        },
    )
    refresh_token = login.json()["data"]["refresh_token"]

    resp = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh_token},
        headers=user_headers,
    )
    assert resp.status_code == 200


async def test_token_refresh(client: AsyncClient, user):
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "password123",
        },
    )
    assert login.status_code == 200
    refresh_token = login.json()["data"]["refresh_token"]

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert "access_token" in resp.json()["data"]


async def test_refresh_with_invalid_token_returns_401(client: AsyncClient):
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "bad.token.here"})
    assert resp.status_code == 401


async def test_password_reset_request_always_200(client: AsyncClient):
    """Must not reveal whether email exists."""
    resp = await client.post("/api/v1/auth/forgot-password", json={"email": "ghost@example.com"})
    assert resp.status_code == 200
