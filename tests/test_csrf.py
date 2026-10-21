"""CSRF middleware (app/middleware/csrf.py) - a double-submit token on top
of SameSite=Lax for cookie-authenticated browser requests. The shared
`client` fixture auto-echoes the token (mirroring what the real frontend's
fetch()/HTMX wrapper does - see tests/conftest.py's _attach_csrf_header), so
these tests build their own raw client to exercise the rejection paths."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.main import app


async def _raw_client(db) -> AsyncClient:
    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_login_is_never_blocked_by_csrf(client: AsyncClient, user):
    """No session cookie exists yet pre-login, so the CSRF check (which only
    fires when a heelo_access cookie is present) must not fire here."""
    resp = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "password123"}
    )
    assert resp.status_code == 200


async def test_csrf_cookie_is_issued_on_first_response(db):
    async with await _raw_client(db) as raw:
        resp = await raw.get("/health")
        assert "csrf_token" in resp.cookies
    app.dependency_overrides.pop(get_db, None)


async def test_cookie_authed_post_without_csrf_token_is_rejected(db, user):
    async with await _raw_client(db) as raw:
        login = await raw.post(
            "/api/v1/auth/login", json={"email": user.email, "password": "password123"}
        )
        assert login.status_code == 200
        assert "heelo_access" in raw.cookies

        # No X-CSRF-Token header attached - unlike the shared `client`
        # fixture, this raw client has no auto-echo hook.
        resp = await raw.post("/api/v1/auth/logout")
        assert resp.status_code == 403
    app.dependency_overrides.pop(get_db, None)


async def test_cookie_authed_post_with_mismatched_csrf_token_is_rejected(db, user):
    async with await _raw_client(db) as raw:
        login = await raw.post(
            "/api/v1/auth/login", json={"email": user.email, "password": "password123"}
        )
        assert login.status_code == 200

        resp = await raw.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "not-the-token"})
        assert resp.status_code == 403
    app.dependency_overrides.pop(get_db, None)


async def test_cookie_authed_post_with_matching_csrf_token_succeeds(db, user):
    async with await _raw_client(db) as raw:
        login = await raw.post(
            "/api/v1/auth/login", json={"email": user.email, "password": "password123"}
        )
        assert login.status_code == 200
        token = raw.cookies.get("csrf_token")
        assert token

        resp = await raw.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token})
        assert resp.status_code == 204
    app.dependency_overrides.pop(get_db, None)


async def test_bearer_token_auth_is_never_blocked_by_csrf(client: AsyncClient, user_headers):
    """A genuine API client authenticating with an explicit Authorization
    header (not the auto-attached session cookie) can't be forged by a
    cross-site attacker, so it's exempt from the CSRF check entirely."""
    resp = await client.post(
        "/api/v1/organizations",
        json={"name": "Bearer Auth Org", "country": "NG", "currency": "NGN"},
        headers=user_headers,
    )
    assert resp.status_code == 201


async def test_get_requests_are_never_blocked_by_csrf(db):
    async with await _raw_client(db) as raw:
        resp = await raw.get("/health")
        assert resp.status_code == 200
    app.dependency_overrides.pop(get_db, None)
