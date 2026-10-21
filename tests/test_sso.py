"""Domain-restricted SSO (Enterprise) - TXT-record ownership verification,
the settings endpoints, and password-login/registration enforcement for a
verified + enforced email domain. DNS lookups are mocked; the org fixture is
on the enterprise plan (see conftest.py) so happy-path tests don't need
their own plan setup."""

from __future__ import annotations

from sqlalchemy import update

from app.models.organization import Organization
from app.services import organization_service as org_svc


async def _make_free_org(db):
    from app.models.user import User
    from app.utils.auth import hash_password

    owner = User(
        full_name="SSO Test User",
        email="sso-free@example.com",
        password_hash=hash_password("password123"),
        role="organizer",
        is_verified=True,
    )
    db.add(owner)
    await db.flush()
    org = Organization(owner_id=owner.id, name="Free SSO Org", slug="free-sso-org", plan="free")
    db.add(org)
    await db.flush()
    return owner, org


def _token_for(user_id) -> str:
    from datetime import UTC, datetime, timedelta

    from jose import jwt

    from app.config import settings

    payload = {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(hours=1), "type": "access"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _headers_for(user_id) -> dict:
    return {"Authorization": f"Bearer {_token_for(user_id)}"}


# ── Service layer ────────────────────────────────────────────────────────────


async def test_set_sso_domain_generates_verification_token(db, org):
    updated = await org_svc.set_sso_domain(db, org, "Acme.Corp.com")
    assert updated.sso_domain == "acme.corp.com"  # normalized lowercase
    assert updated.sso_domain_verified is False
    assert updated.sso_enforced is False
    assert updated.sso_verification_token


async def test_set_sso_domain_rejects_duplicate(db, org):
    other = Organization(
        owner_id=org.owner_id, name="Other", slug="other-sso-org", sso_domain="taken.com"
    )
    db.add(other)
    await db.flush()

    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await org_svc.set_sso_domain(db, org, "taken.com")
    assert exc.value.status_code == 409


async def test_verify_sso_fails_when_txt_record_missing(db, org, monkeypatch):
    await org_svc.set_sso_domain(db, org, "acme.com")
    monkeypatch.setattr(org_svc, "check_sso_domain_txt_record", lambda domain, token: False)

    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await org_svc.verify_sso_domain(db, org)
    assert exc.value.status_code == 400
    assert org.sso_domain_verified is False


async def test_verify_sso_succeeds_when_txt_record_matches(db, org, monkeypatch):
    await org_svc.set_sso_domain(db, org, "acme.com")
    monkeypatch.setattr(org_svc, "check_sso_domain_txt_record", lambda domain, token: True)

    updated = await org_svc.verify_sso_domain(db, org)
    assert updated.sso_domain_verified is True


async def test_enforce_fails_when_not_verified(db, org):
    await org_svc.set_sso_domain(db, org, "acme.com")

    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await org_svc.set_sso_enforcement(db, org, True)
    assert exc.value.status_code == 400
    assert org.sso_enforced is False


async def test_enforce_succeeds_when_verified(db, org, monkeypatch):
    await org_svc.set_sso_domain(db, org, "acme.com")
    monkeypatch.setattr(org_svc, "check_sso_domain_txt_record", lambda domain, token: True)
    await org_svc.verify_sso_domain(db, org)

    updated = await org_svc.set_sso_enforcement(db, org, True)
    assert updated.sso_enforced is True

    updated = await org_svc.set_sso_enforcement(db, org, False)
    assert updated.sso_enforced is False


async def test_remove_sso_domain_clears_everything(db, org, monkeypatch):
    await org_svc.set_sso_domain(db, org, "acme.com")
    monkeypatch.setattr(org_svc, "check_sso_domain_txt_record", lambda domain, token: True)
    await org_svc.verify_sso_domain(db, org)
    await org_svc.set_sso_enforcement(db, org, True)

    updated = await org_svc.remove_sso_domain(db, org)
    assert updated.sso_domain is None
    assert updated.sso_domain_verified is False
    assert updated.sso_verification_token is None
    assert updated.sso_enforced is False


# ── Router / permission gating ───────────────────────────────────────────────


async def test_set_sso_domain_requires_enterprise_plan(client, db):
    owner, free_org = await _make_free_org(db)
    resp = await client.post(
        f"/api/v1/organizations/{free_org.slug}/sso",
        json={"domain": "acme.com"},
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 402


async def test_set_sso_domain_succeeds_on_enterprise_org(client, org, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/sso",
        json={"domain": "acme.com"},
        headers=user_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["domain"] == "acme.com"
    assert data["verification_record"]["type"] == "TXT"
    assert data["verification_record"]["name"] == "_heelo-sso-verify.acme.com"


async def test_set_sso_domain_rejects_invalid_format(client, org, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/sso",
        json={"domain": "not a domain!!"},
        headers=user_headers,
    )
    assert resp.status_code == 422


async def test_verify_endpoint_requires_enterprise_plan(client, db):
    owner, free_org = await _make_free_org(db)
    resp = await client.post(
        f"/api/v1/organizations/{free_org.slug}/sso/verify",
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 402


async def test_enforce_endpoint_requires_enterprise_plan(client, db):
    owner, free_org = await _make_free_org(db)
    resp = await client.post(
        f"/api/v1/organizations/{free_org.slug}/sso/enforce",
        json={"enforced": True},
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 402


async def test_remove_sso_domain_endpoint(client, org, user_headers):
    await client.post(
        f"/api/v1/organizations/{org.slug}/sso",
        json={"domain": "acme.com"},
        headers=user_headers,
    )
    resp = await client.delete(f"/api/v1/organizations/{org.slug}/sso", headers=user_headers)
    assert resp.status_code == 204


# ── Login/registration enforcement ───────────────────────────────────────────


async def test_login_blocked_when_sso_enforced_for_domain(client, db, org, user):
    await db.execute(
        update(Organization)
        .where(Organization.id == org.id)
        .values(sso_domain="example.com", sso_domain_verified=True, sso_enforced=True)
    )
    await db.commit()

    resp = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "password123"}
    )
    assert resp.status_code == 403
    assert "single sign-on" in resp.json()["error"]["message"].lower()


async def test_login_allowed_when_sso_domain_set_but_not_enforced(client, db, org, user):
    await db.execute(
        update(Organization)
        .where(Organization.id == org.id)
        .values(sso_domain="example.com", sso_domain_verified=True, sso_enforced=False)
    )
    await db.commit()

    resp = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "password123"}
    )
    assert resp.status_code == 200


async def test_login_allowed_when_plan_downgraded_below_enterprise(client, db, org, user):
    """sso_enforced can be True in the DB from when the org was Enterprise -
    enforcement must still stop the moment the plan no longer has the SSO
    feature, not just when the flag is explicitly cleared."""
    await db.execute(
        update(Organization)
        .where(Organization.id == org.id)
        .values(sso_domain="example.com", sso_domain_verified=True, sso_enforced=True, plan="pro")
    )
    await db.commit()

    resp = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "password123"}
    )
    assert resp.status_code == 200


async def test_login_unaffected_for_different_domain(client, db, org, user):
    await db.execute(
        update(Organization)
        .where(Organization.id == org.id)
        .values(sso_domain="acme.com", sso_domain_verified=True, sso_enforced=True)
    )
    await db.commit()

    resp = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "password123"}
    )
    assert resp.status_code == 200


async def test_register_blocked_when_sso_enforced_for_domain(client, db, org):
    await db.execute(
        update(Organization)
        .where(Organization.id == org.id)
        .values(sso_domain="example.com", sso_domain_verified=True, sso_enforced=True)
    )
    await db.commit()

    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "New Hire",
            "email": "newhire@example.com",
            "password": "Str0ngP@ss!",
            "role": "organizer",
        },
    )
    assert resp.status_code == 403
