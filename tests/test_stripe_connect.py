"""Stripe Connect (Express) - organizer onboarding, status refresh via the
return page and the account.updated webhook, and the checkout-time
destination-charge split. The Stripe SDK isn't httpx-based, so provider
calls are mocked via unittest.mock.patch on the stripe module directly,
mirroring the existing pattern in tests/test_payment_refunds.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from httpx import AsyncClient

from app.services import payment_account_service as acc_svc


def _fake_account(id="acct_test123", details_submitted=False, payouts_enabled=False):
    return MagicMock(id=id, details_submitted=details_submitted, payouts_enabled=payouts_enabled)


def _fake_account_link(url="https://connect.stripe.com/setup/test"):
    return MagicMock(url=url)


# ── create_stripe_connect_account ───────────────────────────────────────────


async def test_create_stripe_connect_account_creates_unverified_payment_account(db, org):
    with (
        patch("stripe.Account.create", return_value=_fake_account()),
        patch("stripe.AccountLink.create", return_value=_fake_account_link()) as mock_link,
    ):
        url = await acc_svc.create_stripe_connect_account(db, org.id, org)

    assert url == "https://connect.stripe.com/setup/test"
    assert mock_link.call_args.kwargs["account"] == "acct_test123"

    account = await acc_svc.get_default_payment_account(db, org.id, "stripe")
    assert account is not None
    assert account.provider_account_id == "acct_test123"
    assert account.is_verified is False
    assert account.is_default is True


async def test_create_stripe_connect_account_demotes_prior_default(db, org):
    with (
        patch("stripe.Account.create", return_value=_fake_account(id="acct_first")),
        patch("stripe.AccountLink.create", return_value=_fake_account_link()),
    ):
        await acc_svc.create_stripe_connect_account(db, org.id, org)

    with (
        patch("stripe.Account.create", return_value=_fake_account(id="acct_second")),
        patch("stripe.AccountLink.create", return_value=_fake_account_link()),
    ):
        await acc_svc.create_stripe_connect_account(db, org.id, org)

    from sqlalchemy import select

    from app.models.payment import PaymentAccount

    accounts = (
        await db.scalars(
            select(PaymentAccount).where(
                PaymentAccount.org_id == org.id, PaymentAccount.provider == "stripe"
            )
        )
    ).all()
    assert len(accounts) == 2
    defaults = [a for a in accounts if a.is_default]
    assert len(defaults) == 1
    assert defaults[0].provider_account_id == "acct_second"


# ── refresh_stripe_connect_status ───────────────────────────────────────────


async def test_refresh_stripe_connect_status_marks_verified_when_ready(db, org):
    with (
        patch("stripe.Account.create", return_value=_fake_account()),
        patch("stripe.AccountLink.create", return_value=_fake_account_link()),
    ):
        await acc_svc.create_stripe_connect_account(db, org.id, org)

    account = await acc_svc.get_default_payment_account(db, org.id, "stripe")
    assert account.is_verified is False

    with patch(
        "stripe.Account.retrieve",
        return_value=_fake_account(details_submitted=True, payouts_enabled=True),
    ):
        account = await acc_svc.refresh_stripe_connect_status(db, account)

    assert account.is_verified is True


async def test_refresh_stripe_connect_status_stays_unverified_when_incomplete(db, org):
    with (
        patch("stripe.Account.create", return_value=_fake_account()),
        patch("stripe.AccountLink.create", return_value=_fake_account_link()),
    ):
        await acc_svc.create_stripe_connect_account(db, org.id, org)
    account = await acc_svc.get_default_payment_account(db, org.id, "stripe")

    with patch(
        "stripe.Account.retrieve",
        return_value=_fake_account(details_submitted=True, payouts_enabled=False),
    ):
        account = await acc_svc.refresh_stripe_connect_status(db, account)

    assert account.is_verified is False


# ── Router: POST /payment-accounts/stripe/connect ───────────────────────────


async def test_connect_stripe_route_returns_onboarding_url(client: AsyncClient, org, user_headers):
    with (
        patch("stripe.Account.create", return_value=_fake_account()),
        patch("stripe.AccountLink.create", return_value=_fake_account_link()),
    ):
        resp = await client.post(
            f"/api/v1/organizations/{org.slug}/payment-accounts/stripe/connect",
            headers=user_headers,
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["url"] == "https://connect.stripe.com/setup/test"


async def test_connect_stripe_route_requires_permission(client: AsyncClient, org, other_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/payment-accounts/stripe/connect",
        headers=other_headers,
    )
    assert resp.status_code == 403


# ── Page routes: onboarding return / refresh ────────────────────────────────


async def test_stripe_return_page_redirects_connected_when_verified(
    client: AsyncClient, db, org, user
):
    login = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "password123"}
    )
    assert login.status_code == 200

    with (
        patch("stripe.Account.create", return_value=_fake_account()),
        patch("stripe.AccountLink.create", return_value=_fake_account_link()),
    ):
        await acc_svc.create_stripe_connect_account(db, org.id, org)

    with patch(
        "stripe.Account.retrieve",
        return_value=_fake_account(details_submitted=True, payouts_enabled=True),
    ):
        resp = await client.get(
            f"/org/{org.slug}/settings/payments/stripe/return", follow_redirects=False
        )
    assert resp.status_code == 302
    assert "stripe_connected=1" in resp.headers["location"]


async def test_stripe_return_page_redirects_pending_when_not_verified(
    client: AsyncClient, db, org, user
):
    login = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "password123"}
    )
    assert login.status_code == 200

    with (
        patch("stripe.Account.create", return_value=_fake_account()),
        patch("stripe.AccountLink.create", return_value=_fake_account_link()),
    ):
        await acc_svc.create_stripe_connect_account(db, org.id, org)

    with patch(
        "stripe.Account.retrieve",
        return_value=_fake_account(details_submitted=False, payouts_enabled=False),
    ):
        resp = await client.get(
            f"/org/{org.slug}/settings/payments/stripe/return", follow_redirects=False
        )
    assert resp.status_code == 302
    assert "stripe_pending=1" in resp.headers["location"]


async def test_stripe_refresh_page_redirects_to_fresh_link(client: AsyncClient, db, org, user):
    login = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "password123"}
    )
    assert login.status_code == 200

    with (
        patch("stripe.Account.create", return_value=_fake_account()),
        patch("stripe.AccountLink.create", return_value=_fake_account_link()),
    ):
        await acc_svc.create_stripe_connect_account(db, org.id, org)

    with patch(
        "stripe.AccountLink.create",
        return_value=_fake_account_link(url="https://connect.stripe.com/setup/refreshed"),
    ):
        resp = await client.get(
            f"/org/{org.slug}/settings/payments/stripe/refresh", follow_redirects=False
        )
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://connect.stripe.com/setup/refreshed"


# ── Webhook: account.updated ─────────────────────────────────────────────────


async def test_account_updated_webhook_marks_verified(client: AsyncClient, db, org, monkeypatch):
    with (
        patch("stripe.Account.create", return_value=_fake_account()),
        patch("stripe.AccountLink.create", return_value=_fake_account_link()),
    ):
        await acc_svc.create_stripe_connect_account(db, org.id, org)

    fake_event = {
        "type": "account.updated",
        "data": {
            "object": {
                "id": "acct_test123",
                "details_submitted": True,
                "payouts_enabled": True,
            }
        },
    }
    from app.config import settings

    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    with patch("stripe.Webhook.construct_event", return_value=fake_event):
        resp = await client.post(
            "/api/v1/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "t=1,v1=fake"},
        )
    assert resp.status_code == 200

    account = await acc_svc.get_default_payment_account(db, org.id, "stripe")
    assert account.is_verified is True


# ── Checkout split ───────────────────────────────────────────────────────────


async def test_initialize_stripe_splits_only_when_account_verified(db, org, published_event):
    from app.models.ticketing import Order
    from app.services import payment_service as pay_svc

    order = Order(
        event_id=published_event.id,
        buyer_name="Jane Doe",
        buyer_email="jane@example.com",
        total_amount=1066.01,
        net_amount=1000.0,
        platform_fee=66.01,
        currency="NGN",
        payment_status="pending",
        fees_passed_to_buyer=True,
    )
    db.add(order)
    await db.flush()

    fake_session = MagicMock(url="https://checkout.stripe.com/pay/cs_test")

    # No stripe account connected - no split.
    with patch("stripe.checkout.Session.create", return_value=fake_session) as mock_create:
        await pay_svc._initialize_stripe(db, order, published_event, org)
    assert "payment_intent_data" not in mock_create.call_args.kwargs

    # Connect an account but leave it unverified - still no split.
    with (
        patch("stripe.Account.create", return_value=_fake_account()),
        patch("stripe.AccountLink.create", return_value=_fake_account_link()),
    ):
        await acc_svc.create_stripe_connect_account(db, org.id, org)

    with patch("stripe.checkout.Session.create", return_value=fake_session) as mock_create:
        await pay_svc._initialize_stripe(db, order, published_event, org)
    assert "payment_intent_data" not in mock_create.call_args.kwargs

    # Verify it - now the split fields are set.
    account = await acc_svc.get_default_payment_account(db, org.id, "stripe")
    account.is_verified = True
    await db.commit()

    with patch("stripe.checkout.Session.create", return_value=fake_session) as mock_create:
        await pay_svc._initialize_stripe(db, order, published_event, org)
    pi_data = mock_create.call_args.kwargs["payment_intent_data"]
    assert pi_data["transfer_data"]["destination"] == account.provider_account_id
    assert pi_data["application_fee_amount"] == 6601  # platform_fee (66.01) in cents
