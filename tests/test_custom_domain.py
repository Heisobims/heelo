"""Custom domain mapping (Pro+) - TXT-record ownership verification, the
settings endpoints, and the root-path redirect middleware. Verification
DNS lookups are mocked; the org fixture is on the enterprise plan (see
conftest.py) so happy-path tests don't need their own plan setup."""

from __future__ import annotations

from httpx import AsyncClient

from app.services import organization_service as org_svc


async def _make_free_org(db):
    from app.models.organization import Organization
    from app.models.user import User
    from app.utils.auth import hash_password

    owner = User(
        full_name="Domain Test User",
        email="domain-free@example.com",
        password_hash=hash_password("password123"),
        role="organizer",
        is_verified=True,
    )
    db.add(owner)
    await db.flush()
    org = Organization(
        owner_id=owner.id, name="Free Domain Org", slug="free-domain-org", plan="free"
    )
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


async def test_set_custom_domain_generates_verification_token(db, org):
    updated = await org_svc.set_custom_domain(db, org, "Events.MyOrg.com")
    assert updated.custom_domain == "events.myorg.com"  # normalized lowercase
    assert updated.custom_domain_verified is False
    assert updated.custom_domain_verification_token


async def test_set_custom_domain_rejects_duplicate(db, org):
    from app.models.organization import Organization

    other = Organization(
        owner_id=org.owner_id, name="Other", slug="other-domain-org", custom_domain="taken.com"
    )
    db.add(other)
    await db.flush()

    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await org_svc.set_custom_domain(db, org, "taken.com")
    assert exc.value.status_code == 409


async def test_verify_fails_when_txt_record_missing(db, org, monkeypatch):
    await org_svc.set_custom_domain(db, org, "events.example.com")
    monkeypatch.setattr(org_svc, "check_custom_domain_txt_record", lambda domain, token: False)

    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await org_svc.verify_custom_domain(db, org)
    assert exc.value.status_code == 400
    assert org.custom_domain_verified is False


async def test_verify_succeeds_when_txt_record_matches(db, org, monkeypatch):
    await org_svc.set_custom_domain(db, org, "events.example.com")
    monkeypatch.setattr(org_svc, "check_custom_domain_txt_record", lambda domain, token: True)

    updated = await org_svc.verify_custom_domain(db, org)
    assert updated.custom_domain_verified is True


async def test_remove_custom_domain_clears_everything(db, org):
    await org_svc.set_custom_domain(db, org, "events.example.com")
    updated = await org_svc.remove_custom_domain(db, org)
    assert updated.custom_domain is None
    assert updated.custom_domain_verified is False
    assert updated.custom_domain_verification_token is None


# ── Router / permission gating ───────────────────────────────────────────────


async def test_set_custom_domain_requires_pro_plan(client: AsyncClient, db):
    owner, free_org = await _make_free_org(db)
    resp = await client.post(
        f"/api/v1/organizations/{free_org.slug}/custom-domain",
        json={"domain": "events.example.com"},
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 402


async def test_set_custom_domain_succeeds_on_enterprise_org(client: AsyncClient, org, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/custom-domain",
        json={"domain": "events.example.com"},
        headers=user_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["domain"] == "events.example.com"
    assert data["verification_record"]["type"] == "TXT"
    assert data["verification_record"]["name"] == "_heelo-verify.events.example.com"


async def test_set_custom_domain_rejects_invalid_format(client: AsyncClient, org, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/custom-domain",
        json={"domain": "not a domain!!"},
        headers=user_headers,
    )
    assert resp.status_code == 422


async def test_verify_endpoint_requires_pro_plan(client: AsyncClient, db):
    owner, free_org = await _make_free_org(db)
    resp = await client.post(
        f"/api/v1/organizations/{free_org.slug}/custom-domain/verify",
        headers=_headers_for(owner.id),
    )
    assert resp.status_code == 402


async def test_remove_custom_domain_endpoint(client: AsyncClient, org, user_headers):
    await client.post(
        f"/api/v1/organizations/{org.slug}/custom-domain",
        json={"domain": "events.example.com"},
        headers=user_headers,
    )
    resp = await client.delete(
        f"/api/v1/organizations/{org.slug}/custom-domain", headers=user_headers
    )
    assert resp.status_code == 204


# ── Middleware ───────────────────────────────────────────────────────────────


async def test_middleware_redirects_verified_domain_root_to_active_event(
    client: AsyncClient, db, org, published_event
):
    from sqlalchemy import update

    from app.models.organization import Organization

    await db.execute(
        update(Organization)
        .where(Organization.id == org.id)
        .values(custom_domain="events.example.com", custom_domain_verified=True)
    )
    await db.commit()

    resp = await client.get("/", headers={"Host": "events.example.com"}, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == f"/e/{published_event.slug}"


async def test_middleware_ignores_unverified_domain(client: AsyncClient, db, org):
    from sqlalchemy import update

    from app.models.organization import Organization

    await db.execute(
        update(Organization)
        .where(Organization.id == org.id)
        .values(custom_domain="events.example.com", custom_domain_verified=False)
    )
    await db.commit()

    resp = await client.get("/", headers={"Host": "events.example.com"}, follow_redirects=False)
    assert resp.status_code == 200


async def test_middleware_ignores_unknown_host(client: AsyncClient):
    resp = await client.get(
        "/", headers={"Host": "not-a-real-domain.example"}, follow_redirects=False
    )
    assert resp.status_code == 200


async def test_middleware_does_not_touch_non_root_paths(
    client: AsyncClient, db, org, published_event
):
    from sqlalchemy import update

    from app.models.organization import Organization

    await db.execute(
        update(Organization)
        .where(Organization.id == org.id)
        .values(custom_domain="events.example.com", custom_domain_verified=True)
    )
    await db.commit()

    resp = await client.get(
        f"/e/{published_event.slug}",
        headers={"Host": "events.example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
