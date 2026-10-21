"""Tests for /host smart routing and authenticated redirects on /register & /login."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.auth import create_access_token


@pytest.mark.asyncio
async def test_host_unauthenticated_redirects_to_register(client: AsyncClient):
    resp = await client.get("/host", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/register?next=/host"


@pytest.mark.asyncio
async def test_host_authenticated_with_org_redirects_to_new_event(
    client: AsyncClient, user, org
):
    token = create_access_token(str(user.id), user.role)
    client.cookies.set("heelo_access", token)

    resp = await client.get("/host", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == f"/org/{org.slug}/events/new"


@pytest.mark.asyncio
async def test_host_authenticated_without_org_redirects_to_org_new(
    client: AsyncClient, user
):
    token = create_access_token(str(user.id), user.role)
    client.cookies.set("heelo_access", token)

    resp = await client.get("/host", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/org/new"


@pytest.mark.asyncio
async def test_register_page_authenticated_redirects_to_dashboard(
    client: AsyncClient, user
):
    token = create_access_token(str(user.id), user.role)
    client.cookies.set("heelo_access", token)

    resp = await client.get("/register", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/dashboard"


@pytest.mark.asyncio
async def test_register_page_authenticated_with_next_redirects_to_next(
    client: AsyncClient, user
):
    token = create_access_token(str(user.id), user.role)
    client.cookies.set("heelo_access", token)

    resp = await client.get("/register?next=/host", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/host"


@pytest.mark.asyncio
async def test_login_page_authenticated_redirects_to_dashboard(
    client: AsyncClient, user
):
    token = create_access_token(str(user.id), user.role)
    client.cookies.set("heelo_access", token)

    resp = await client.get("/login", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/dashboard"


@pytest.mark.asyncio
async def test_home_page_authenticated_renders_hub(client: AsyncClient, user):
    token = create_access_token(str(user.id), user.role)
    client.cookies.set("heelo_access", token)

    resp = await client.get("/home", follow_redirects=True)
    assert resp.status_code == 200
    assert "Welcome back" in resp.text
    assert "Active Event Tickets" in resp.text


@pytest.mark.asyncio
async def test_dashboard_redirects_single_org_to_org_overview(
    client: AsyncClient, user, org
):
    token = create_access_token(str(user.id), user.role)
    client.cookies.set("heelo_access", token)

    resp = await client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == f"/org/{org.slug}"

