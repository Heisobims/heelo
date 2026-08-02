"""Tests for admin vendor/venue moderation (suspend/reinstate) — service and router layers."""

from __future__ import annotations

import uuid

import pytest

from app.services import admin_service as adm_svc


class TestVendorModerationService:
    async def test_suspend_vendor(self, db, vendor):
        result = await adm_svc.suspend_vendor(db, vendor.id)
        assert result.status == "suspended"

    async def test_reinstate_vendor(self, db, vendor):
        await adm_svc.suspend_vendor(db, vendor.id)
        result = await adm_svc.reinstate_vendor(db, vendor.id)
        assert result.status == "active"

    async def test_suspend_unknown_vendor_raises(self, db):
        with pytest.raises(ValueError):
            await adm_svc.suspend_vendor(db, uuid.uuid4())

    async def test_list_vendors_filters_by_status(self, db, vendor):
        await adm_svc.suspend_vendor(db, vendor.id)

        active_results, active_total = await adm_svc.list_vendors(db, status="active")
        assert active_total == 0

        suspended_results, suspended_total = await adm_svc.list_vendors(db, status="suspended")
        assert suspended_total == 1
        assert suspended_results[0].id == vendor.id

    async def test_list_vendors_search(self, db, vendor):
        results, total = await adm_svc.list_vendors(db, search="landmark")
        assert total == 1
        assert results[0].id == vendor.id

        no_results, no_total = await adm_svc.list_vendors(db, search="nonexistent")
        assert no_total == 0


class TestVendorModerationEndpoints:
    async def test_suspend_requires_admin(self, client, user_headers, vendor):
        resp = await client.post(f"/api/v1/admin/vendors/{vendor.id}/suspend", headers=user_headers)
        assert resp.status_code == 403

    async def test_admin_can_suspend_and_reinstate(self, client, admin_headers, vendor):
        resp = await client.post(
            f"/api/v1/admin/vendors/{vendor.id}/suspend", headers=admin_headers
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "suspended"

        resp = await client.post(
            f"/api/v1/admin/vendors/{vendor.id}/reinstate", headers=admin_headers
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "active"

    async def test_suspend_unknown_vendor_404(self, client, admin_headers):
        resp = await client.post(
            f"/api/v1/admin/vendors/{uuid.uuid4()}/suspend", headers=admin_headers
        )
        assert resp.status_code == 404

    async def test_vendors_page_requires_admin_cookie(self, client, vendor):
        resp = await client.get("/admin/vendors", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"].startswith("/login")
