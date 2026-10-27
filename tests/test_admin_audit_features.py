from __future__ import annotations

import uuid
from httpx import AsyncClient
from jose import jwt
from app.config import settings


def _set_admin_cookie(client: AsyncClient, admin_user):
    token = jwt.encode({"sub": str(admin_user.id)}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    client.cookies.set("tixdoo_access", token)


# ── Feature & Status Toggles ──────────────────────────────────────────────────


async def test_toggle_event_featured(client: AsyncClient, event, admin_headers):
    # Initially is_featured is False/None
    resp = await client.post(
        f"/api/v1/admin/events/{event.id}/toggle-featured",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["is_featured"] is True

    # Toggle back to False
    resp2 = await client.post(
        f"/api/v1/admin/events/{event.id}/toggle-featured",
        headers=admin_headers,
    )
    assert resp2.status_code == 200
    assert resp2.json()["data"]["is_featured"] is False


async def test_set_event_status(client: AsyncClient, event, admin_headers):
    resp = await client.post(
        f"/api/v1/admin/events/{event.id}/status",
        json={"status": "cancelled"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"

    # Test invalid status returns 400
    resp_invalid = await client.post(
        f"/api/v1/admin/events/{event.id}/status",
        json={"status": "super_active"},
        headers=admin_headers,
    )
    assert resp_invalid.status_code == 400


async def test_verify_custom_domain(client: AsyncClient, org, admin_headers):
    resp = await client.post(
        f"/api/v1/admin/organizations/{org.id}/verify-domain",
        json={"verified": True},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["custom_domain_verified"] is True

    resp_revoke = await client.post(
        f"/api/v1/admin/organizations/{org.id}/verify-domain",
        json={"verified": False},
        headers=admin_headers,
    )
    assert resp_revoke.status_code == 200
    assert resp_revoke.json()["data"]["custom_domain_verified"] is False


async def test_toggle_sso_domain(client: AsyncClient, org, admin_headers):
    resp = await client.post(
        f"/api/v1/admin/organizations/{org.id}/toggle-sso",
        json={"verified": True, "enforced": True},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["sso_domain_verified"] is True
    assert resp.json()["data"]["sso_enforced"] is True


async def test_admin_vendor_suspend_and_reinstate(client: AsyncClient, vendor, admin_headers):
    resp_suspend = await client.post(
        f"/api/v1/admin/vendors/{vendor.id}/suspend",
        headers=admin_headers,
    )
    assert resp_suspend.status_code == 200
    assert resp_suspend.json()["data"]["status"] == "suspended"
    assert resp_suspend.json()["data"]["is_active"] is False

    resp_reinstate = await client.post(
        f"/api/v1/admin/vendors/{vendor.id}/reinstate",
        headers=admin_headers,
    )
    assert resp_reinstate.status_code == 200
    assert resp_reinstate.json()["data"]["status"] == "active"
    assert resp_reinstate.json()["data"]["is_active"] is True


# ── Page Rendering & Tab Access ───────────────────────────────────────────────


async def test_admin_overview_page_metrics(client: AsyncClient, admin_user):
    _set_admin_cookie(client, admin_user)
    resp = await client.get("/admin")
    assert resp.status_code == 200
    assert "Platform Overview" in resp.text
    assert "Ticket GMV" in resp.text
    assert "Subscription Revenue" in resp.text
    assert "Marketplace Volume" in resp.text


async def test_admin_finance_page_tabs(client: AsyncClient, admin_user):
    _set_admin_cookie(client, admin_user)

    # Orders tab
    resp = await client.get("/admin/finance?tab=orders")
    assert resp.status_code == 200
    assert "Ticket Orders" in resp.text
    assert "Platform Finances &amp; Orders" in resp.text

    # Invoices tab
    resp_inv = await client.get("/admin/finance?tab=invoices")
    assert resp_inv.status_code == 200
    assert "Plan Subscription Invoices" in resp_inv.text

    # Marketplace tab
    resp_mkt = await client.get("/admin/finance?tab=marketplace")
    assert resp_mkt.status_code == 200
    assert "Vendor Escrow &amp; Bookings" in resp_mkt.text


async def test_admin_events_page_filters(client: AsyncClient, admin_user, event):
    _set_admin_cookie(client, admin_user)

    resp_all = await client.get("/admin/events")
    assert resp_all.status_code == 200
    assert "All Events" in resp_all.text

    resp_feat = await client.get("/admin/events?featured=true")
    assert resp_feat.status_code == 200

    resp_status = await client.get("/admin/events?status=published")
    assert resp_status.status_code == 200


async def test_admin_organizations_list_and_detail(client: AsyncClient, admin_user, org):
    _set_admin_cookie(client, admin_user)

    # List page
    resp_list = await client.get("/admin/organizations?plan=free")
    assert resp_list.status_code == 200
    assert "Organizations" in resp_list.text

    # Detail page
    resp_detail = await client.get(f"/admin/organizations/{org.id}")
    assert resp_detail.status_code == 200
    assert org.name in resp_detail.text
    assert "Domains &amp; Enterprise SSO" in resp_detail.text
    assert "Subscription Billing History" in resp_detail.text


async def test_admin_vendors_page_tabs(client: AsyncClient, admin_user):
    _set_admin_cookie(client, admin_user)

    resp_dir = await client.get("/admin/vendors?tab=directory")
    assert resp_dir.status_code == 200
    assert "Vendor Directory" in resp_dir.text

    resp_verif = await client.get("/admin/vendors?tab=verifications")
    assert resp_verif.status_code == 200
    assert "Verification Queue" in resp_verif.text

    resp_pay = await client.get("/admin/vendors?tab=payouts")
    assert resp_pay.status_code == 200
    assert "Vendor Payouts" in resp_pay.text


async def test_admin_users_list_and_detail(client: AsyncClient, admin_user, user):
    _set_admin_cookie(client, admin_user)

    resp_users = await client.get("/admin/users?category=all")
    assert resp_users.status_code == 200
    assert "Users" in resp_users.text

    resp_detail = await client.get(f"/admin/users/{user.id}")
    assert resp_detail.status_code == 200
    assert user.full_name in resp_detail.text
    assert "Account &amp; Demographics" in resp_detail.text


async def test_admin_payouts_page(client: AsyncClient, admin_user):
    _set_admin_cookie(client, admin_user)

    resp = await client.get("/admin/payouts")
    assert resp.status_code == 200
    assert "Payouts" in resp.text
    assert "Owed" in resp.text
    assert "In flight" in resp.text


async def test_admin_insights_page(client: AsyncClient, admin_user):
    _set_admin_cookie(client, admin_user)

    resp = await client.get("/admin/insights")
    assert resp.status_code == 200
    assert "Audience Insights" in resp.text


async def test_admin_broadcasts_page(client: AsyncClient, admin_user):
    _set_admin_cookie(client, admin_user)

    resp = await client.get("/admin/broadcasts")
    assert resp.status_code == 200
    assert "Broadcasts" in resp.text
    assert "Audience" in resp.text
    assert "Send test to myself" in resp.text


async def test_admin_vendors_category_venue(client: AsyncClient, admin_user):
    _set_admin_cookie(client, admin_user)

    resp = await client.get("/admin/vendors?category=venue")
    assert resp.status_code == 200
    assert "Vendor Directory" in resp.text


async def test_admin_finance_status_filters(client: AsyncClient, admin_user):
    _set_admin_cookie(client, admin_user)

    resp_orders = await client.get("/admin/finance?tab=orders&status=completed")
    assert resp_orders.status_code == 200

    resp_invoices = await client.get("/admin/finance?tab=invoices&status=paid")
    assert resp_invoices.status_code == 200


async def test_admin_events_search_query(client: AsyncClient, admin_user):
    _set_admin_cookie(client, admin_user)

    resp = await client.get("/admin/events?q=gala")
    assert resp.status_code == 200


async def test_admin_users_search_query(client: AsyncClient, admin_user):
    _set_admin_cookie(client, admin_user)

    resp = await client.get("/admin/users?q=alex")
    assert resp.status_code == 200


# ── Auth Enforcement ──────────────────────────────────────────────────────────


async def test_unauthorized_user_redirected_to_login(client: AsyncClient, user):
    # Non-admin user tries to access admin pages
    token = jwt.encode({"sub": str(user.id)}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    client.cookies.set("tixdoo_access", token)

    for route in ["/admin", "/admin/organizations", "/admin/events", "/admin/finance", "/admin/payouts", "/admin/users"]:
        resp = await client.get(route)
        assert resp.status_code == 302
        assert "/login" in resp.headers.get("location", "")
