"""Organization CRUD, team management, invite flow."""

from __future__ import annotations

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


async def test_create_org_with_colliding_name_gets_auto_deduped_slug(
    client: AsyncClient, org, user_headers
):
    # Slugs are derived server-side from `name` and auto-deduplicated — there's no
    # client-supplied slug to collide on, so a same-named org just gets a distinct slug.
    resp = await client.post(
        "/api/v1/organizations",
        json={"name": org.name},
        headers=user_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["slug"] != org.slug


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
        json={"email": other_user.email, "role": "organizer"},
        headers=user_headers,
    )
    assert resp.status_code == 201
    member = resp.json()["data"]["member"]
    assert member["status"] == "invite_pending"
    # other_user already has an account, so the invite links to it immediately.
    assert member["user_id"] == str(other_user.id)


async def test_cancel_pending_invite_for_unregistered_email(client: AsyncClient, org, user_headers):
    """Regression test: an invite to someone with no Heelo account yet has no
    user_id, so cancelling it must be keyed by the membership row's own id —
    previously the remove endpoint required a user_id and silently no-op'd."""
    invite_resp = await client.post(
        f"/api/v1/organizations/{org.slug}/members/invite",
        json={"email": "not-yet-a-user@example.com", "role": "organizer"},
        headers=user_headers,
    )
    member = invite_resp.json()["data"]["member"]
    assert member["user_id"] is None
    member_id = member["id"]

    resp = await client.delete(
        f"/api/v1/organizations/{org.slug}/members/{member_id}",
        headers=user_headers,
    )
    assert resp.status_code == 204

    list_resp = await client.get(f"/api/v1/organizations/{org.slug}/members", headers=user_headers)
    assert "not-yet-a-user@example.com" not in [
        m["invited_email"] for m in list_resp.json()["data"]
    ]


async def test_remove_active_member(client: AsyncClient, db, org, other_user, user_headers):
    from datetime import UTC, datetime

    from app.models.organization import OrganizationMember

    member = OrganizationMember(
        org_id=org.id,
        user_id=other_user.id,
        role="organizer",
        invited_at=datetime.now(UTC),
        accepted_at=datetime.now(UTC),
        status="active",
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)

    resp = await client.delete(
        f"/api/v1/organizations/{org.slug}/members/{member.id}",
        headers=user_headers,
    )
    assert resp.status_code == 204

    list_resp = await client.get(f"/api/v1/organizations/{org.slug}/members", headers=user_headers)
    assert str(other_user.id) not in [
        m["user_id"] for m in list_resp.json()["data"] if m["user_id"]
    ]


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
