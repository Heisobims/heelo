from __future__ import annotations

import asyncio
import uuid

import httpx
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.payment import PaymentAccount
from app.schemas.payment import FlutterwaveSubaccountRequest, PaystackSubaccountRequest

# ── Paystack ──────────────────────────────────────────────────────────────────


async def list_paystack_banks(country: str = "nigeria") -> list[dict]:
    """Fetch the list of supported banks from Paystack."""
    if not settings.PAYSTACK_SECRET_KEY:
        return []
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.paystack.co/bank",
                params={"country": country, "per_page": 200, "use_cursor": "false"},
                headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
                timeout=10.0,
            )
        body = resp.json()
        if body.get("status"):
            return [{"name": b["name"], "code": b["code"]} for b in body["data"]]
    except httpx.HTTPError:
        pass
    return []


async def resolve_paystack_account(account_number: str, bank_code: str) -> dict | None:
    """Resolve an account number to the account holder's name via Paystack."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.paystack.co/bank/resolve",
            params={"account_number": account_number, "bank_code": bank_code},
            headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
            timeout=10.0,
        )
    body = resp.json()
    if not body.get("status"):
        return None
    return body["data"]  # {"account_number": "...", "account_name": "JOHN DOE"}


async def create_paystack_subaccount(
    db: AsyncSession,
    org_id: uuid.UUID,
    data: PaystackSubaccountRequest,
    org,
) -> PaymentAccount:
    """Create a Paystack subaccount for the org and save it."""
    payload: dict = {
        "business_name": data.business_name or org.name,
        "settlement_bank": data.bank_code,
        "account_number": data.account_number,
        "percentage_charge": 95.0,
    }
    if data.contact_email:
        payload["primary_contact_email"] = str(data.contact_email)

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.paystack.co/subaccount",
            json=payload,
            headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
            timeout=15.0,
        )

    body = resp.json()
    if not body.get("status"):
        raise HTTPException(
            502,
            f"Paystack: {body.get('message', 'Failed to create subaccount.')}",
        )

    sub = body["data"]

    # Demote any existing default Paystack account for this org
    await db.execute(
        update(PaymentAccount)
        .where(
            PaymentAccount.org_id == org_id,
            PaymentAccount.provider == "paystack",
        )
        .values(is_default=False)
    )

    account = PaymentAccount(
        org_id=org_id,
        provider="paystack",
        provider_account_id=sub["subaccount_code"],
        account_name=sub.get("account_name") or sub.get("business_name") or data.business_name,
        bank_name=sub.get("settlement_bank"),
        account_number=data.account_number,
        is_verified=True,
        is_default=True,
        currency=org.currency or "NGN",
        country="NG",
        instant_settlement=False,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


# ── Flutterwave ───────────────────────────────────────────────────────────────


async def create_flutterwave_subaccount(
    db: AsyncSession,
    org_id: uuid.UUID,
    data: FlutterwaveSubaccountRequest,
    org,
) -> PaymentAccount:
    """Create a Flutterwave subaccount for the org and save it."""
    payload = {
        "account_bank": data.bank_code,
        "account_number": data.account_number,
        "business_name": data.business_name or org.name,
        "business_email": getattr(org, "contact_email", None) or "",
        "country": data.country,
        "split_value": 0.95,
        "split_type": "percentage",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.flutterwave.com/v3/subaccounts",
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )

    body = resp.json()
    if body.get("status") != "success":
        raise HTTPException(
            502,
            f"Flutterwave: {body.get('message', 'Failed to create subaccount.')}",
        )

    sub = body["data"]

    await db.execute(
        update(PaymentAccount)
        .where(
            PaymentAccount.org_id == org_id,
            PaymentAccount.provider == "flutterwave",
        )
        .values(is_default=False)
    )

    account = PaymentAccount(
        org_id=org_id,
        provider="flutterwave",
        provider_account_id=str(sub["id"]),
        account_name=sub.get("account_name") or data.business_name,
        bank_name=sub.get("bank_name"),
        account_number=data.account_number,
        is_verified=True,
        is_default=True,
        currency=getattr(org, "currency", "NGN") or "NGN",
        country=data.country,
        instant_settlement=False,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


async def list_flutterwave_banks(country: str = "NG") -> list[dict]:
    """Fetch the list of supported banks from Flutterwave - mirrors
    list_paystack_banks() but Flutterwave uses its own bank-code namespace,
    distinct from Paystack's, so this can't be shared."""
    if not settings.FLUTTERWAVE_SECRET_KEY:
        return []
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.flutterwave.com/v3/banks/{country}",
                headers={"Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}"},
                timeout=10.0,
            )
        body = resp.json()
        if body.get("status") == "success":
            return [{"name": b["name"], "code": b["code"]} for b in body["data"]]
    except httpx.HTTPError:
        pass
    return []


async def resolve_flutterwave_account(account_number: str, bank_code: str) -> dict | None:
    """Resolve an account number to the account holder's name via
    Flutterwave. Distinct endpoint/payload shape from Paystack's resolve."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.flutterwave.com/v3/accounts/resolve",
            json={"account_number": account_number, "account_bank": bank_code},
            headers={
                "Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )
    body = resp.json()
    if body.get("status") != "success":
        return None
    return body["data"]  # {"account_number": "...", "account_name": "JOHN DOE"}


# ── Stripe Connect (Express) ─────────────────────────────────────────────────
#
# Destination-charge model, matching the Paystack/Flutterwave subaccount
# split: the organizer gets their own Stripe Express account (Stripe hosts
# onboarding/KYC and their payout dashboard - least engineering/compliance
# overhead of the three Connect account types), and each checkout charge is
# created on Heelo's own platform account with `transfer_data.destination`
# pointing at it (see _initialize_stripe in payment_service.py). An Express
# account isn't usable until the organizer completes Stripe-hosted
# onboarding, so this returns an *onboarding URL*, not a ready account.


async def create_stripe_connect_account(db: AsyncSession, org_id: uuid.UUID, org) -> str:
    """Create a Stripe Express account for the org and return the onboarding
    URL to redirect the organizer to. The PaymentAccount row is created
    immediately but starts unverified - _initialize_stripe only splits to
    accounts with is_verified=True, so nothing routes there until Stripe
    confirms onboarding is actually complete."""
    import stripe

    def _create_account():
        return stripe.Account.create(
            api_key=settings.STRIPE_SECRET_KEY,
            type="express",
            country=org.country or "NG",
            email=org.contact_email or None,
            capabilities={"transfers": {"requested": True}},
        )

    acct = await asyncio.to_thread(_create_account)

    await db.execute(
        update(PaymentAccount)
        .where(PaymentAccount.org_id == org_id, PaymentAccount.provider == "stripe")
        .values(is_default=False)
    )

    account = PaymentAccount(
        org_id=org_id,
        provider="stripe",
        provider_account_id=acct.id,
        account_name=org.name,
        bank_name=None,
        account_number=None,
        is_verified=False,
        is_default=True,
        currency=org.currency or "USD",
        country=org.country or "NG",
        instant_settlement=False,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)

    return await create_stripe_onboarding_link(account, org)


async def create_stripe_onboarding_link(account: PaymentAccount, org) -> str:
    """Fresh AccountLink for `account` - used both right after creation and
    to recover if the organizer's link expired before they finished
    onboarding (Stripe's refresh_url flow)."""
    import stripe

    def _create_link():
        return stripe.AccountLink.create(
            api_key=settings.STRIPE_SECRET_KEY,
            account=account.provider_account_id,
            refresh_url=f"{settings.FRONTEND_URL}/org/{org.slug}/settings/payments/stripe/refresh",
            return_url=f"{settings.FRONTEND_URL}/org/{org.slug}/settings/payments/stripe/return",
            type="account_onboarding",
        )

    link = await asyncio.to_thread(_create_link)
    return link.url


async def refresh_stripe_connect_status(
    db: AsyncSession, account: PaymentAccount
) -> PaymentAccount:
    """Re-check onboarding status with Stripe and update is_verified.
    Called from the onboarding return page and from the account.updated
    webhook, so is_verified stays correct whichever path the organizer's
    browser actually takes back."""
    import stripe

    def _retrieve():
        return stripe.Account.retrieve(
            account.provider_account_id, api_key=settings.STRIPE_SECRET_KEY
        )

    acct = await asyncio.to_thread(_retrieve)
    account.is_verified = bool(acct.details_submitted and acct.payouts_enabled)
    await db.commit()
    await db.refresh(account)
    return account


# ── Manual / local account ──────────────────────────────────────────────────
#
# Not tied to any payment gateway - no subaccount is created, so this can
# never receive an automatic split from a Paystack/Flutterwave charge (that
# lookup is always scoped to the actual charge provider). It exists purely
# as a reference record for orgs whose bank isn't covered by either
# integrated provider, or who simply want to note where they're paid.


async def add_manual_account(
    db: AsyncSession,
    org_id: uuid.UUID,
    data,
    currency: str = "NGN",
) -> PaymentAccount:
    await db.execute(
        update(PaymentAccount)
        .where(PaymentAccount.org_id == org_id, PaymentAccount.provider == "manual")
        .values(is_default=False)
    )

    bank_code = getattr(data, "bank_code", None)
    if not bank_code and data.bank_name:
        clean_bank = data.bank_name.strip()
        if clean_bank.isdigit():
            bank_code = clean_bank

    account = PaymentAccount(
        org_id=org_id,
        provider="manual",
        provider_account_id=f"manual-{uuid.uuid4().hex[:12]}",
        account_name=data.account_name,
        bank_name=data.bank_name,
        account_number=data.account_number,
        bank_code=bank_code,
        recipient_code=None,
        is_verified=False,
        is_default=True,
        currency=currency,
        country="NG",
        instant_settlement=False,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


# ── Shared helpers ────────────────────────────────────────────────────────────


async def get_default_payment_account(
    db: AsyncSession,
    org_id: uuid.UUID,
    provider: str,
) -> PaymentAccount | None:
    return await db.scalar(
        select(PaymentAccount).where(
            PaymentAccount.org_id == org_id,
            PaymentAccount.provider == provider,
            PaymentAccount.is_default.is_(True),
        )
    )


async def list_payment_accounts(db: AsyncSession, org_id: uuid.UUID) -> list[PaymentAccount]:
    result = await db.scalars(
        select(PaymentAccount)
        .where(PaymentAccount.org_id == org_id)
        .order_by(PaymentAccount.created_at.desc())
    )
    return list(result.all())


async def delete_payment_account(db: AsyncSession, account: PaymentAccount) -> None:
    """Deleting the default account for a provider silently orphans future
    payouts for that provider (get_default_payment_account would just
    return None, so charges stop splitting to the organizer at all) unless
    another account of the same provider is promoted to default."""
    was_default = account.is_default
    provider = account.provider
    org_id = account.org_id

    await db.delete(account)
    await db.flush()

    if was_default:
        replacement = await db.scalar(
            select(PaymentAccount)
            .where(PaymentAccount.org_id == org_id, PaymentAccount.provider == provider)
            .order_by(PaymentAccount.created_at.desc())
        )
        if replacement:
            replacement.is_default = True

    await db.commit()
