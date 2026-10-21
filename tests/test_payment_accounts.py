"""Payout account setup - connecting Paystack/Flutterwave subaccounts,
switching the default, and deletion. Previously only a permission-denial
test existed (test_permissions.py); this covers the actual create/set-default/
delete flows end-to-end through the router, with the provider API mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient

from app.services import payment_account_service as acc_svc


def _fake_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


def _fake_async_client(response: MagicMock) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=response)
    client.get = AsyncMock(return_value=response)
    return client


_PAYSTACK_PAYLOAD = {
    "account_number": "0123456789",
    "bank_code": "058",
    "business_name": "Test Org",
}
_FLUTTERWAVE_PAYLOAD = {
    "account_number": "0123456789",
    "bank_code": "058",
    "business_name": "Test Org",
}


async def test_connect_paystack_account_succeeds(
    client: AsyncClient, org, user_headers, monkeypatch
):
    fake = _fake_async_client(
        _fake_response(
            {
                "status": True,
                "data": {
                    "subaccount_code": "ACCT_test123",
                    "account_name": "Test Org",
                    "settlement_bank": "GTBank",
                },
            }
        )
    )
    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", lambda: fake)

    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/payment-accounts/paystack",
        json=_PAYSTACK_PAYLOAD,
        headers=user_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["provider"] == "paystack"
    assert data["is_default"] is True
    assert data["is_verified"] is True


async def test_connect_paystack_account_propagates_provider_error(
    client: AsyncClient, org, user_headers, monkeypatch
):
    fake = _fake_async_client(_fake_response({"status": False, "message": "Invalid bank code"}))
    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", lambda: fake)

    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/payment-accounts/paystack",
        json=_PAYSTACK_PAYLOAD,
        headers=user_headers,
    )
    assert resp.status_code == 502
    assert "Invalid bank code" in resp.json()["error"]["message"]


async def test_connect_second_paystack_account_demotes_the_first(
    client: AsyncClient, org, user_headers, monkeypatch
):
    fake = _fake_async_client(
        _fake_response(
            {"status": True, "data": {"subaccount_code": "ACCT_first", "account_name": "A"}}
        )
    )
    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", lambda: fake)
    first = await client.post(
        f"/api/v1/organizations/{org.slug}/payment-accounts/paystack",
        json=_PAYSTACK_PAYLOAD,
        headers=user_headers,
    )
    assert first.json()["is_default"] is True

    fake2 = _fake_async_client(
        _fake_response(
            {"status": True, "data": {"subaccount_code": "ACCT_second", "account_name": "B"}}
        )
    )
    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", lambda: fake2)
    second = await client.post(
        f"/api/v1/organizations/{org.slug}/payment-accounts/paystack",
        json=_PAYSTACK_PAYLOAD,
        headers=user_headers,
    )
    assert second.json()["is_default"] is True

    listing = await client.get(
        f"/api/v1/organizations/{org.slug}/payment-accounts", headers=user_headers
    )
    accounts = {a["provider_account_id"]: a["is_default"] for a in listing.json()}
    assert accounts["ACCT_first"] is False
    assert accounts["ACCT_second"] is True


async def test_connect_flutterwave_account_succeeds(
    client: AsyncClient, org, user_headers, monkeypatch
):
    fake = _fake_async_client(
        _fake_response(
            {
                "status": "success",
                "data": {"id": 998877, "account_name": "Test Org", "bank_name": "GTBank"},
            }
        )
    )
    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", lambda: fake)

    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/payment-accounts/flutterwave",
        json=_FLUTTERWAVE_PAYLOAD,
        headers=user_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["provider"] == "flutterwave"
    assert data["is_default"] is True


async def test_connect_flutterwave_account_propagates_provider_error(
    client: AsyncClient, org, user_headers, monkeypatch
):
    fake = _fake_async_client(_fake_response({"status": "error", "message": "Bad bank"}))
    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", lambda: fake)

    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/payment-accounts/flutterwave",
        json=_FLUTTERWAVE_PAYLOAD,
        headers=user_headers,
    )
    assert resp.status_code == 502
    assert "Bad bank" in resp.json()["error"]["message"]


async def test_set_default_account_switches_default_within_provider(
    client: AsyncClient, org, user_headers, monkeypatch
):
    fake1 = _fake_async_client(
        _fake_response({"status": True, "data": {"subaccount_code": "ACCT_1", "account_name": "A"}})
    )
    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", lambda: fake1)
    acct1 = (
        await client.post(
            f"/api/v1/organizations/{org.slug}/payment-accounts/paystack",
            json=_PAYSTACK_PAYLOAD,
            headers=user_headers,
        )
    ).json()

    fake2 = _fake_async_client(
        _fake_response({"status": True, "data": {"subaccount_code": "ACCT_2", "account_name": "B"}})
    )
    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", lambda: fake2)
    acct2 = (
        await client.post(
            f"/api/v1/organizations/{org.slug}/payment-accounts/paystack",
            json=_PAYSTACK_PAYLOAD,
            headers=user_headers,
        )
    ).json()
    assert acct2["is_default"] is True  # most-recently-connected wins by default

    resp = await client.patch(
        f"/api/v1/organizations/{org.slug}/payment-accounts/{acct1['id']}/set-default",
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_default"] is True

    listing = (
        await client.get(f"/api/v1/organizations/{org.slug}/payment-accounts", headers=user_headers)
    ).json()
    by_id = {a["id"]: a["is_default"] for a in listing}
    assert by_id[acct1["id"]] is True
    assert by_id[acct2["id"]] is False


async def test_delete_payment_account(client: AsyncClient, org, user_headers, monkeypatch):
    fake = _fake_async_client(
        _fake_response(
            {"status": True, "data": {"subaccount_code": "ACCT_del", "account_name": "A"}}
        )
    )
    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", lambda: fake)
    acct = (
        await client.post(
            f"/api/v1/organizations/{org.slug}/payment-accounts/paystack",
            json=_PAYSTACK_PAYLOAD,
            headers=user_headers,
        )
    ).json()

    resp = await client.delete(
        f"/api/v1/organizations/{org.slug}/payment-accounts/{acct['id']}",
        headers=user_headers,
    )
    assert resp.status_code == 204

    listing = (
        await client.get(f"/api/v1/organizations/{org.slug}/payment-accounts", headers=user_headers)
    ).json()
    assert all(a["id"] != acct["id"] for a in listing)


async def test_delete_nonexistent_account_returns_404(client: AsyncClient, org, user_headers):
    import uuid

    resp = await client.delete(
        f"/api/v1/organizations/{org.slug}/payment-accounts/{uuid.uuid4()}",
        headers=user_headers,
    )
    assert resp.status_code == 404


async def test_set_default_requires_payment_accounts_manage_permission(
    client: AsyncClient, org, finance_headers
):
    import uuid

    resp = await client.patch(
        f"/api/v1/organizations/{org.slug}/payment-accounts/{uuid.uuid4()}/set-default",
        headers=finance_headers,
    )
    assert resp.status_code == 403


# ── Flutterwave banks/resolve (previously hardcoded to Paystack's endpoints,
# so switching to the Flutterwave tab in the UI silently sent Paystack bank
# codes to Flutterwave's subaccount API) ────────────────────────────────────


async def test_get_flutterwave_banks(client: AsyncClient, org, user_headers, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "FLUTTERWAVE_SECRET_KEY", "test-secret")
    fake = _fake_async_client(
        _fake_response(
            {"status": "success", "data": [{"id": 1, "code": "044", "name": "Access Bank"}]}
        )
    )
    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", lambda: fake)

    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/payment-accounts/flutterwave/banks",
        headers=user_headers,
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data == [{"name": "Access Bank", "code": "044"}]


async def test_resolve_flutterwave_account_succeeds(
    client: AsyncClient, org, user_headers, monkeypatch
):
    fake = _fake_async_client(
        _fake_response(
            {
                "status": "success",
                "data": {"account_number": "0123456789", "account_name": "JOHN DOE"},
            }
        )
    )
    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", lambda: fake)

    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/payment-accounts/flutterwave/resolve",
        params={"account_number": "0123456789", "bank_code": "044"},
        headers=user_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["account_name"] == "JOHN DOE"


async def test_resolve_flutterwave_account_fails(
    client: AsyncClient, org, user_headers, monkeypatch
):
    fake = _fake_async_client(_fake_response({"status": "error", "message": "Invalid account"}))
    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", lambda: fake)

    resp = await client.get(
        f"/api/v1/organizations/{org.slug}/payment-accounts/flutterwave/resolve",
        params={"account_number": "0000000000", "bank_code": "044"},
        headers=user_headers,
    )
    assert resp.status_code == 422


# ── Manual / local account (no gateway subaccount, reference record only) ──


_MANUAL_PAYLOAD = {
    "bank_name": "GTBank",
    "account_number": "0123456789",
    "account_name": "Benevents Ltd",
}


async def test_connect_manual_account_succeeds(client: AsyncClient, org, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/payment-accounts/manual",
        json=_MANUAL_PAYLOAD,
        headers=user_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["provider"] == "manual"
    assert data["bank_name"] == "GTBank"
    assert data["account_name"] == "Benevents Ltd"
    # Self-attested, no gateway verification - must never appear "Verified".
    assert data["is_verified"] is False
    assert data["is_default"] is True


async def test_manual_account_requires_no_provider_api_call(
    client: AsyncClient, org, user_headers, monkeypatch
):
    """Adding a local account must not hit Paystack/Flutterwave at all -
    patch httpx to explode if it's ever called, proving this path is
    fully offline."""

    def _boom():
        raise AssertionError("manual account creation should never call an external API")

    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", _boom)

    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/payment-accounts/manual",
        json=_MANUAL_PAYLOAD,
        headers=user_headers,
    )
    assert resp.status_code == 201


async def test_second_manual_account_demotes_the_first(client: AsyncClient, org, user_headers):
    first = (
        await client.post(
            f"/api/v1/organizations/{org.slug}/payment-accounts/manual",
            json=_MANUAL_PAYLOAD,
            headers=user_headers,
        )
    ).json()
    second = (
        await client.post(
            f"/api/v1/organizations/{org.slug}/payment-accounts/manual",
            json={**_MANUAL_PAYLOAD, "bank_name": "Zenith Bank"},
            headers=user_headers,
        )
    ).json()
    assert second["is_default"] is True

    listing = (
        await client.get(f"/api/v1/organizations/{org.slug}/payment-accounts", headers=user_headers)
    ).json()
    by_id = {a["id"]: a["is_default"] for a in listing}
    assert by_id[first["id"]] is False
    assert by_id[second["id"]] is True


async def test_manual_account_rejects_missing_fields(client: AsyncClient, org, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/payment-accounts/manual",
        json={"bank_name": "GTBank"},
        headers=user_headers,
    )
    assert resp.status_code == 422


# ── Delete-default reassignment (previously: deleting the default account
# left no default at all for that provider, silently breaking future
# payouts since get_default_payment_account would just return None) ────────


async def test_delete_default_account_promotes_next_same_provider_account(
    client: AsyncClient, org, user_headers, monkeypatch
):
    fake1 = _fake_async_client(
        _fake_response({"status": True, "data": {"subaccount_code": "ACCT_1", "account_name": "A"}})
    )
    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", lambda: fake1)
    acct1 = (
        await client.post(
            f"/api/v1/organizations/{org.slug}/payment-accounts/paystack",
            json=_PAYSTACK_PAYLOAD,
            headers=user_headers,
        )
    ).json()

    fake2 = _fake_async_client(
        _fake_response({"status": True, "data": {"subaccount_code": "ACCT_2", "account_name": "B"}})
    )
    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", lambda: fake2)
    acct2 = (
        await client.post(
            f"/api/v1/organizations/{org.slug}/payment-accounts/paystack",
            json=_PAYSTACK_PAYLOAD,
            headers=user_headers,
        )
    ).json()
    assert acct2["is_default"] is True  # most-recently-connected

    # Delete the current default (acct2) - acct1 must be promoted, not left
    # with zero defaults for this provider.
    resp = await client.delete(
        f"/api/v1/organizations/{org.slug}/payment-accounts/{acct2['id']}",
        headers=user_headers,
    )
    assert resp.status_code == 204

    listing = (
        await client.get(f"/api/v1/organizations/{org.slug}/payment-accounts", headers=user_headers)
    ).json()
    assert len(listing) == 1
    assert listing[0]["id"] == acct1["id"]
    assert listing[0]["is_default"] is True


async def test_delete_the_only_account_leaves_none(
    client: AsyncClient, org, user_headers, monkeypatch
):
    fake = _fake_async_client(
        _fake_response(
            {"status": True, "data": {"subaccount_code": "ACCT_only", "account_name": "A"}}
        )
    )
    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", lambda: fake)
    acct = (
        await client.post(
            f"/api/v1/organizations/{org.slug}/payment-accounts/paystack",
            json=_PAYSTACK_PAYLOAD,
            headers=user_headers,
        )
    ).json()

    resp = await client.delete(
        f"/api/v1/organizations/{org.slug}/payment-accounts/{acct['id']}",
        headers=user_headers,
    )
    assert resp.status_code == 204

    listing = (
        await client.get(f"/api/v1/organizations/{org.slug}/payment-accounts", headers=user_headers)
    ).json()
    assert listing == []


async def test_delete_non_default_account_does_not_disturb_the_default(
    client: AsyncClient, org, user_headers, monkeypatch
):
    fake1 = _fake_async_client(
        _fake_response({"status": True, "data": {"subaccount_code": "ACCT_1", "account_name": "A"}})
    )
    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", lambda: fake1)
    acct1 = (
        await client.post(
            f"/api/v1/organizations/{org.slug}/payment-accounts/paystack",
            json=_PAYSTACK_PAYLOAD,
            headers=user_headers,
        )
    ).json()

    fake2 = _fake_async_client(
        _fake_response({"status": True, "data": {"subaccount_code": "ACCT_2", "account_name": "B"}})
    )
    monkeypatch.setattr(acc_svc.httpx, "AsyncClient", lambda: fake2)
    acct2 = (
        await client.post(
            f"/api/v1/organizations/{org.slug}/payment-accounts/paystack",
            json=_PAYSTACK_PAYLOAD,
            headers=user_headers,
        )
    ).json()
    assert acct2["is_default"] is True

    # Delete the non-default one (acct1) - acct2 stays default, untouched.
    resp = await client.delete(
        f"/api/v1/organizations/{org.slug}/payment-accounts/{acct1['id']}",
        headers=user_headers,
    )
    assert resp.status_code == 204

    listing = (
        await client.get(f"/api/v1/organizations/{org.slug}/payment-accounts", headers=user_headers)
    ).json()
    assert len(listing) == 1
    assert listing[0]["id"] == acct2["id"]
    assert listing[0]["is_default"] is True
