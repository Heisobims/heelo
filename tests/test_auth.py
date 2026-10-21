"""Auth flow - register, login, token refresh, logout."""

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
    assert data["email"] == "alice@example.com"
    assert "access_token" not in data


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


async def test_register_rate_limited_per_email(client: AsyncClient, monkeypatch):
    """Regression test: /register and /resend-otp had zero throttling, so
    either could be spammed to mass-trigger OTP emails at any target
    inbox. Now backed by the same fail-open Redis counter as login."""
    from app.routers import auth as auth_router
    from app.utils import rate_limit as rl

    fake = _FakeRedis()
    monkeypatch.setattr(rl, "_redis", lambda: fake)

    email = "rate-limited@example.com"
    for i in range(auth_router._REGISTER_MAX_PER_EMAIL):
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Rate Limited",
                "email": email,
                "password": "Str0ngP@ss!",
                "role": "organizer",
            },
        )
        assert resp.status_code == 201, f"attempt {i} should have succeeded"

    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Rate Limited",
            "email": email,
            "password": "Str0ngP@ss!",
            "role": "organizer",
        },
    )
    assert resp.status_code == 429


async def test_register_not_rate_limited_when_redis_unavailable(client: AsyncClient):
    for i in range(10):
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "No Redis",
                "email": f"no-redis-{i}@example.com",
                "password": "Str0ngP@ss!",
                "role": "organizer",
            },
        )
        assert resp.status_code == 201


async def test_login_returns_tokens(client: AsyncClient, user):
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "password123",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
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


class _FakeRedis:
    """Minimal in-memory stand-in for the subset of the redis-py API the
    login rate limiter uses - Redis isn't running in the test environment,
    so this lets us exercise the actual limiting logic instead of just its
    fail-open no-Redis path."""

    def __init__(self):
        self.counts: dict[str, int] = {}

    def get(self, key):
        val = self.counts.get(key)
        return str(val) if val is not None else None

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, seconds):
        pass

    def delete(self, key):
        self.counts.pop(key, None)


async def test_login_rate_limited_after_too_many_failed_attempts(
    client: AsyncClient, user, monkeypatch
):
    """Regression test: /login had zero in-app throttling and relied
    entirely on an unverifiable Nginx-level comment. Now backed by a Redis
    attempt counter (defense-in-depth, fails open if Redis is unreachable)."""
    from app.services import auth_service

    fake = _FakeRedis()
    monkeypatch.setattr(auth_service, "_login_redis", lambda: fake)

    for _ in range(auth_service._LOGIN_MAX_ATTEMPTS):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "wrongpassword"},
        )
        assert resp.status_code == 401

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "password123"},  # correct password
    )
    assert resp.status_code == 429


async def test_login_rate_limit_resets_on_success(client: AsyncClient, user, monkeypatch):
    from app.services import auth_service

    fake = _FakeRedis()
    monkeypatch.setattr(auth_service, "_login_redis", lambda: fake)

    for _ in range(auth_service._LOGIN_MAX_ATTEMPTS - 1):
        await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "wrongpassword"},
        )

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "password123"},
    )
    assert resp.status_code == 200
    assert fake.counts.get(f"login_attempts:{user.email.lower()}") is None


async def test_login_not_rate_limited_when_redis_unavailable(client: AsyncClient, user):
    """Fails open - Redis isn't running in dev/test, and login must keep
    working exactly as before, same convention as every other
    Redis-dependent feature in this codebase."""
    for _ in range(10):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "wrongpassword"},
        )
        assert resp.status_code == 401


async def test_access_protected_endpoint_with_valid_token(client: AsyncClient, user_headers):
    resp = await client.get("/api/v1/organizations", headers=user_headers)
    # 200 or empty list - just not 401
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
    refresh_token = login.json()["refresh_token"]

    resp = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh_token},
        headers=user_headers,
    )
    assert resp.status_code == 204


async def test_token_refresh(client: AsyncClient, user):
    login = await client.post(
        "/api/v1/auth/login",
        json={
            "email": user.email,
            "password": "password123",
        },
    )
    assert login.status_code == 200
    refresh_token = login.json()["refresh_token"]

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_refresh_with_invalid_token_returns_401(client: AsyncClient):
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "bad.token.here"})
    assert resp.status_code == 401


async def test_password_reset_request_always_200(client: AsyncClient):
    """Must not reveal whether email exists."""
    resp = await client.post("/api/v1/auth/forgot-password", json={"email": "ghost@example.com"})
    assert resp.status_code == 204
