from __future__ import annotations

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
        "percentage_charge": 97.0,
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
        "split_value": 0.97,
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
    await db.delete(account)
    await db.commit()
