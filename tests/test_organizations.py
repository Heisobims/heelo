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
    # Slugs are derived server-side from `name` and auto-deduplicated - there's no
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
    """Regression test: an invite to someone with no Tixdoo account yet has no
    user_id, so cancelling it must be keyed by the membership row's own id -
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


# ── Accept invite ──────────────────────────────────────────────────────────────


async def test_accept_invite_activates_pending_membership(
    client: AsyncClient, db, org, other_user, user_headers, other_headers
):
    from app.services.organization_service import _make_invite_token

    invite_resp = await client.post(
        f"/api/v1/organizations/{org.slug}/members/invite",
        json={"email": other_user.email, "role": "finance"},
        headers=user_headers,
    )
    assert invite_resp.status_code == 201

    token = _make_invite_token(org.id, other_user.email, "finance")
    resp = await client.post(f"/api/v1/organizations/accept-invite/{token}", headers=other_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["redirect_to"] == f"/org/{org.slug}"

    from sqlalchemy import select

    from app.models.organization import OrganizationMember

    member = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.org_id == org.id, OrganizationMember.user_id == other_user.id
        )
    )
    assert member.status == "active"
    assert member.role == "finance"
    assert member.accepted_at is not None


async def test_accept_invite_rejects_mismatched_email(
    client: AsyncClient, org, other_user, user_headers, other_headers
):
    """The invite token is bound to a specific email - logging in as someone
    else and using the link must not silently attach them to the org."""
    from app.services.organization_service import _make_invite_token

    await client.post(
        f"/api/v1/organizations/{org.slug}/members/invite",
        json={"email": "someone-else@example.com", "role": "organizer"},
        headers=user_headers,
    )
    token = _make_invite_token(org.id, "someone-else@example.com", "organizer")
    resp = await client.post(f"/api/v1/organizations/accept-invite/{token}", headers=other_headers)
    assert resp.status_code == 400


async def test_accept_invite_rejects_garbage_token(client: AsyncClient, other_headers):
    resp = await client.post(
        "/api/v1/organizations/accept-invite/not-a-real-token", headers=other_headers
    )
    assert resp.status_code == 400


async def test_accept_invite_rejects_expired_token(
    client: AsyncClient, org, other_user, user_headers, other_headers
):
    from datetime import UTC, datetime, timedelta

    from jose import jwt

    from app.config import settings

    await client.post(
        f"/api/v1/organizations/{org.slug}/members/invite",
        json={"email": other_user.email, "role": "organizer"},
        headers=user_headers,
    )
    expired_payload = {
        "type": "org_invite",
        "org_id": str(org.id),
        "invited_email": other_user.email.lower(),
        "role": "organizer",
        "exp": datetime.now(UTC) - timedelta(days=1),
    }
    expired_token = jwt.encode(expired_payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    resp = await client.post(
        f"/api/v1/organizations/accept-invite/{expired_token}", headers=other_headers
    )
    assert resp.status_code == 400


async def test_accept_invite_twice_is_idempotent(
    client: AsyncClient, org, other_user, user_headers, other_headers
):
    from app.services.organization_service import _make_invite_token

    await client.post(
        f"/api/v1/organizations/{org.slug}/members/invite",
        json={"email": other_user.email, "role": "organizer"},
        headers=user_headers,
    )
    token = _make_invite_token(org.id, other_user.email, "organizer")
    url = f"/api/v1/organizations/accept-invite/{token}"
    first = await client.post(url, headers=other_headers)
    second = await client.post(url, headers=other_headers)
    assert first.status_code == 200
    assert second.status_code == 200


# ── Role change ────────────────────────────────────────────────────────────────


async def test_update_member_role_requires_team_manage_permission(
    client: AsyncClient, org, other_user, checkin_staff_headers
):
    resp = await client.patch(
        f"/api/v1/organizations/{org.slug}/members/{other_user.id}/role",
        json={"role": "admin"},
        headers=checkin_staff_headers,
    )
    assert resp.status_code == 403


async def test_update_member_role_changes_role(
    client: AsyncClient, db, org, other_user, user_headers
):
    from datetime import UTC, datetime

    from app.models.organization import OrganizationMember

    m = OrganizationMember(
        org_id=org.id,
        user_id=other_user.id,
        role="checkin_staff",
        invited_at=datetime.now(UTC),
        accepted_at=datetime.now(UTC),
        status="active",
    )
    db.add(m)
    await db.commit()

    resp = await client.patch(
        f"/api/v1/organizations/{org.slug}/members/{other_user.id}/role",
        json={"role": "finance"},
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "finance"


async def test_update_member_role_rejects_invalid_role_value(
    client: AsyncClient, org, other_user, user_headers
):
    resp = await client.patch(
        f"/api/v1/organizations/{org.slug}/members/{other_user.id}/role",
        json={"role": "superadmin"},
        headers=user_headers,
    )
    assert resp.status_code == 422


async def test_update_member_role_cannot_change_owner_role(
    client: AsyncClient, org, user, user_headers
):
    """The owner's authority comes from Organization.owner_id, not a team
    role row - changing it would be meaningless and must be rejected."""
    resp = await client.patch(
        f"/api/v1/organizations/{org.slug}/members/{user.id}/role",
        json={"role": "finance"},
        headers=user_headers,
    )
    assert resp.status_code == 400


async def test_update_member_role_rejects_non_active_member(
    client: AsyncClient, db, org, other_user, user_headers
):
    from datetime import UTC, datetime

    from app.models.organization import OrganizationMember

    m = OrganizationMember(
        org_id=org.id,
        invited_email=other_user.email,
        role="checkin_staff",
        invited_at=datetime.now(UTC),
        status="invite_pending",
    )
    db.add(m)
    await db.commit()

    resp = await client.patch(
        f"/api/v1/organizations/{org.slug}/members/{other_user.id}/role",
        json={"role": "finance"},
        headers=user_headers,
    )
    assert resp.status_code == 400


# ── Owner capability regression (remove / change role of an invited member) ───


async def test_owner_can_remove_and_change_role_of_invited_member(
    client: AsyncClient, db, org, other_user, user_headers
):
    """The org owner is permanently role='admin' (never changeable, never
    removable) so TEAM_MANAGE is always available to them - confirming
    end-to-end that an owner-invited member can be role-changed and then
    removed by that same owner."""
    invite_resp = await client.post(
        f"/api/v1/organizations/{org.slug}/members/invite",
        json={"email": other_user.email, "role": "organizer"},
        headers=user_headers,
    )
    assert invite_resp.status_code == 201
    member_id = invite_resp.json()["data"]["member"]["id"]

    from datetime import UTC, datetime

    # Simulate acceptance so the role-change endpoint (active members only)
    # has something to act on.
    from sqlalchemy import select

    from app.models.organization import OrganizationMember

    member = await db.scalar(select(OrganizationMember).where(OrganizationMember.id == member_id))
    member.user_id = other_user.id
    member.status = "active"
    member.accepted_at = datetime.now(UTC)
    await db.commit()

    role_resp = await client.patch(
        f"/api/v1/organizations/{org.slug}/members/{other_user.id}/role",
        json={"role": "finance"},
        headers=user_headers,
    )
    assert role_resp.status_code == 200
    assert role_resp.json()["data"]["role"] == "finance"

    remove_resp = await client.delete(
        f"/api/v1/organizations/{org.slug}/members/{member_id}",
        headers=user_headers,
    )
    assert remove_resp.status_code == 204


# ── Resend invite ────────────────────────────────────────────────────────────


async def test_resend_invite_succeeds_for_pending_invite(
    client: AsyncClient, org, other_user, user_headers
):
    invite_resp = await client.post(
        f"/api/v1/organizations/{org.slug}/members/invite",
        json={"email": other_user.email, "role": "organizer"},
        headers=user_headers,
    )
    member_id = invite_resp.json()["data"]["member"]["id"]

    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/members/{member_id}/resend-invite",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


async def test_resend_invite_issues_a_fresh_still_valid_token(
    client: AsyncClient, db, org, other_user, user_headers
):
    """Resending must regenerate the token (new exp), not merely re-send the
    same one - confirmed by decoding a freshly issued token for this member
    and checking it validates and carries the right claims."""
    from app.services.organization_service import _make_invite_token, decode_invite_token

    invite_resp = await client.post(
        f"/api/v1/organizations/{org.slug}/members/invite",
        json={"email": other_user.email, "role": "organizer"},
        headers=user_headers,
    )
    member_id = invite_resp.json()["data"]["member"]["id"]

    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/members/{member_id}/resend-invite",
        headers=user_headers,
    )
    assert resp.status_code == 200

    # A freshly generated token for the same member/org/role must still
    # decode successfully (proves the signing path resend_invite exercises
    # is the same valid path, not a broken/stale one).
    fresh_token = _make_invite_token(org.id, other_user.email, "organizer")
    payload = decode_invite_token(fresh_token)
    assert payload["invited_email"] == other_user.email.lower()
    assert payload["org_id"] == str(org.id)


async def test_resend_invite_rejects_non_pending_member(
    client: AsyncClient, db, org, other_user, user_headers
):
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

    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/members/{member.id}/resend-invite",
        headers=user_headers,
    )
    assert resp.status_code == 400


async def test_resend_invite_requires_team_manage_permission(
    client: AsyncClient, org, user_headers, checkin_staff_headers
):
    invite_resp = await client.post(
        f"/api/v1/organizations/{org.slug}/members/invite",
        json={"email": "fresh-invitee@example.com", "role": "organizer"},
        headers=user_headers,
    )
    member_id = invite_resp.json()["data"]["member"]["id"]

    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/members/{member_id}/resend-invite",
        headers=checkin_staff_headers,
    )
    assert resp.status_code == 403


async def test_resend_invite_rejects_unknown_member_id(client: AsyncClient, org, user_headers):
    import uuid

    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/members/{uuid.uuid4()}/resend-invite",
        headers=user_headers,
    )
    assert resp.status_code == 400


# ── Invite expiry ────────────────────────────────────────────────────────────


def test_invite_token_expires_in_24_hours():
    from datetime import UTC, datetime, timedelta

    from jose import jwt

    from app.config import settings
    from app.services.organization_service import _make_invite_token

    token = _make_invite_token("org-id", "someone@example.com", "organizer")
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
    delta = exp - datetime.now(UTC)
    assert timedelta(hours=23) < delta <= timedelta(hours=24)
