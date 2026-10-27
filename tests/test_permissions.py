"""Centralized permission matrix (app/permissions.py) - unit tests for the matrix
itself, plus integration tests confirming it's actually enforced at the two
concrete gaps the audit found: checkin_staff couldn't scan/undo check-ins, and
finance could see far more than just the finance dashboard.
"""

from __future__ import annotations

from httpx import AsyncClient

from app.permissions import Permission, has_permission


class TestPermissionMatrix:
    def test_admin_has_every_permission(self):
        for perm in Permission:
            assert has_permission("admin", perm)

    def test_organizer_lacks_admin_only_permissions(self):
        admin_only = {
            Permission.ORG_SETTINGS_EDIT,
            Permission.TEAM_MANAGE,
            Permission.PAYMENT_ACCOUNTS_MANAGE,
            Permission.API_KEYS_MANAGE,
            Permission.EVENTS_DELETE,
        }
        for perm in admin_only:
            assert not has_permission("organizer", perm)

    def test_organizer_has_operational_permissions(self):
        operational = {
            Permission.EVENTS_MANAGE,
            Permission.TICKETING_MANAGE,
            Permission.REGISTRATIONS_MANAGE,
            Permission.CAMPAIGNS_MANAGE,
            Permission.INBOX_REPLY,
            Permission.CRM_MANAGE,
            Permission.AI_USE,
            Permission.FINANCE_VIEW,
            Permission.CHECKIN_SCAN,
            Permission.CHECKIN_UNDO,
        }
        for perm in operational:
            assert has_permission("organizer", perm)

    def test_finance_role_is_scoped_to_finance_view_only(self):
        assert has_permission("finance", Permission.FINANCE_VIEW)
        for perm in Permission:
            if perm != Permission.FINANCE_VIEW:
                assert not has_permission("finance", perm)

    def test_checkin_staff_role_is_scoped_to_checkin_only(self):
        assert has_permission("checkin_staff", Permission.CHECKIN_SCAN)
        assert has_permission("checkin_staff", Permission.CHECKIN_UNDO)
        for perm in Permission:
            if perm not in (Permission.CHECKIN_SCAN, Permission.CHECKIN_UNDO):
                assert not has_permission("checkin_staff", perm)

    def test_unknown_role_has_no_permissions(self):
        for perm in Permission:
            assert not has_permission("not-a-real-role", perm)


class TestCheckinStaffEnforcement:
    """The concrete bug the audit found: checkin_staff could scan (no check
    existed at all) but was explicitly blocked from undo. Both should now work."""

    async def test_checkin_staff_can_scan(
        self, client: AsyncClient, org, published_event, registration, checkin_staff_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
            json={"registration_id": str(registration.id)},
            headers=checkin_staff_headers,
        )
        assert resp.status_code == 200

    async def test_checkin_staff_can_undo(
        self, client: AsyncClient, org, published_event, registration, checkin_staff_headers
    ):
        await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
            json={"registration_id": str(registration.id)},
            headers=checkin_staff_headers,
        )
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}"
            f"/check-in/{registration.id}/undo",
            headers=checkin_staff_headers,
        )
        assert resp.status_code == 200

    async def test_checkin_staff_cannot_manage_events(
        self, client: AsyncClient, org, checkin_staff_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events",
            json={
                "title": "Unauthorized Event",
                "start_datetime": "2027-01-01T10:00:00Z",
                "end_datetime": "2027-01-01T12:00:00Z",
            },
            headers=checkin_staff_headers,
        )
        assert resp.status_code == 403

    async def test_checkin_staff_cannot_send_campaigns(
        self, client: AsyncClient, org, published_event, checkin_staff_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/campaigns",
            json={
                "name": "Unauthorized",
                "type": "email",
                "subject": "x",
                "body": "x",
                "event_id": str(published_event.id),
            },
            headers=checkin_staff_headers,
        )
        assert resp.status_code == 403


class TestFinanceRoleEnforcement:
    """finance should see financial data and nothing else - previously it was
    only checked on the finance dashboard page, nowhere else."""

    async def test_finance_can_view_finance_page(self, client: AsyncClient, org, finance_member):
        # Page routes (app/routers/pages.py) authenticate via the tixdoo_access
        # cookie, not an Authorization header - unlike the JSON API.
        from tests.conftest import _make_token

        client.cookies.set("tixdoo_access", _make_token(str(finance_member.user_id)))
        resp = await client.get(f"/org/{org.slug}/finance")
        assert resp.status_code == 200

    async def test_finance_cannot_create_events(self, client: AsyncClient, org, finance_headers):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events",
            json={
                "title": "Unauthorized Event",
                "start_datetime": "2027-01-01T10:00:00Z",
                "end_datetime": "2027-01-01T12:00:00Z",
            },
            headers=finance_headers,
        )
        assert resp.status_code == 403

    async def test_finance_cannot_manage_payment_accounts(
        self, client: AsyncClient, org, finance_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/payment-accounts/paystack",
            json={"subaccount_code": "ACCT_x", "bank_code": "058", "account_number": "0123456789"},
            headers=finance_headers,
        )
        assert resp.status_code == 403

    async def test_finance_cannot_scan_checkins(
        self, client: AsyncClient, org, published_event, registration, finance_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events/{published_event.id}/check-in",
            json={"registration_id": str(registration.id)},
            headers=finance_headers,
        )
        assert resp.status_code == 403


class TestOrganizerRoleStillWorksAsBefore:
    """Regression guard - the migration to require_permission() shouldn't have
    changed what a plain non-owner "organizer" member can do."""

    async def test_organizer_member_can_manage_events(
        self, client: AsyncClient, org, organizer_member_headers
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/events",
            json={
                "title": "Organizer-created Event",
                "start_datetime": "2027-01-01T10:00:00Z",
                "end_datetime": "2027-01-01T12:00:00Z",
            },
            headers=organizer_member_headers,
        )
        assert resp.status_code == 201

    async def test_organizer_member_cannot_delete_org_or_manage_team(
        self, client: AsyncClient, org, organizer_member_headers
    ):
        resp = await client.patch(
            f"/api/v1/organizations/{org.slug}",
            json={"name": "Renamed"},
            headers=organizer_member_headers,
        )
        assert resp.status_code == 403

        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/members/invite",
            json={"email": "someone@example.com", "role": "organizer"},
            headers=organizer_member_headers,
        )
        assert resp.status_code == 403
