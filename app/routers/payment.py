from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.dependencies import DBSession, OrgAccess
from app.models.payment import PaymentAccount
from app.schemas.payment import (
    FlutterwaveSubaccountRequest,
    PaymentAccountOut,
    PaystackSubaccountRequest,
)
from app.services import payment_account_service as acc_svc
from app.services import payment_service as pay_svc

# ── Webhooks — raw body, no JSON body parsing by FastAPI ─────────────────────

router_webhooks = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


@router_webhooks.post("/paystack", status_code=200)
async def paystack_webhook(request: Request, db: DBSession):
    body = await request.body()
    signature = request.headers.get("x-paystack-signature", "")

    if not pay_svc.verify_paystack_signature(body, signature):
        raise HTTPException(400, "Invalid signature.")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON payload.")

    event = payload.get("event", "")
    data = payload.get("data", {})

    if event == "charge.success":
        reference = data.get("reference", "")
        if reference.startswith("heelo_"):
            await pay_svc.verify_paystack(db, reference)

    return {"status": "ok"}


@router_webhooks.post("/flutterwave", status_code=200)
async def flutterwave_webhook(request: Request, db: DBSession):
    body = await request.body()
    signature = request.headers.get("verif-hash", "")

    if not pay_svc.verify_flutterwave_signature(signature):
        raise HTTPException(400, "Invalid signature.")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON payload.")

    if payload.get("status") == "successful":
        tx_data = payload.get("data", {})
        tx_id = tx_data.get("id")
        tx_ref = tx_data.get("tx_ref", "")
        if tx_id and tx_ref.startswith("heelo_"):
            await pay_svc.verify_flutterwave(db, int(tx_id))

    return {"status": "ok"}


@router_webhooks.post("/stripe", status_code=200)
async def stripe_webhook(request: Request, db: DBSession):
    import asyncio
    import stripe  # type: ignore

    from app.config import settings

    body = await request.body()
    sig = request.headers.get("stripe-signature", "")

    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(503, "Stripe webhooks not configured.")

    try:
        event = await asyncio.to_thread(
            stripe.Webhook.construct_event,
            body,
            sig,
            settings.STRIPE_WEBHOOK_SECRET,
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400, "Invalid Stripe signature.")
    except Exception:
        raise HTTPException(400, "Invalid Stripe payload.")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        order_id_str = (session.get("metadata") or {}).get("order_id")
        if order_id_str:
            try:
                oid = uuid.UUID(order_id_str)
            except ValueError:
                return {"status": "ok"}
            from app.services.ticketing_service import get_order
            order = await get_order(db, oid)
            if order and order.payment_status != "paid":
                order.payment_reference = session.get("payment_intent") or session["id"]
                await pay_svc.confirm_order(db, order)

    return {"status": "ok"}


# ── Payment account management ────────────────────────────────────────────────

router_payment_accounts = APIRouter(
    prefix="/api/v1/organizations/{slug}/payment-accounts",
    tags=["payment-accounts"],
)


@router_payment_accounts.get("", response_model=list[PaymentAccountOut])
async def list_accounts(slug: str, db: DBSession, org_access: OrgAccess):
    org, role, is_owner = org_access
    return await acc_svc.list_payment_accounts(db, org.id)


@router_payment_accounts.get("/paystack/banks")
async def get_paystack_banks(slug: str, org_access: OrgAccess, country: str = "nigeria"):
    org_access  # auth check only
    banks = await acc_svc.list_paystack_banks(country=country)
    return {"success": True, "data": banks}


@router_payment_accounts.get("/paystack/resolve")
async def resolve_account(
    slug: str,
    account_number: str,
    bank_code: str,
    db: DBSession,
    org_access: OrgAccess,
):
    org_access  # auth check only
    result = await acc_svc.resolve_paystack_account(account_number, bank_code)
    if not result:
        raise HTTPException(422, "Could not resolve account. Check the account number and bank.")
    return {"success": True, "data": result}


@router_payment_accounts.post("/paystack", response_model=PaymentAccountOut, status_code=201)
async def connect_paystack(
    slug: str,
    data: PaystackSubaccountRequest,
    db: DBSession,
    org_access: OrgAccess,
):
    org, role, is_owner = org_access
    if not is_owner and role != "admin":
        raise HTTPException(403, "Only the organization owner or admin can manage payment accounts.")

    account = await acc_svc.create_paystack_subaccount(db, org.id, data, org)
    return account


@router_payment_accounts.post("/flutterwave", response_model=PaymentAccountOut, status_code=201)
async def connect_flutterwave(
    slug: str,
    data: FlutterwaveSubaccountRequest,
    db: DBSession,
    org_access: OrgAccess,
):
    org, role, is_owner = org_access
    if not is_owner and role != "admin":
        raise HTTPException(403, "Only the organization owner or admin can manage payment accounts.")

    account = await acc_svc.create_flutterwave_subaccount(db, org.id, data, org)
    return account


@router_payment_accounts.patch("/{account_id}/set-default", response_model=PaymentAccountOut)
async def set_default_account(
    slug: str,
    account_id: str,
    db: DBSession,
    org_access: OrgAccess,
):
    org, role, is_owner = org_access
    if not is_owner and role != "admin":
        raise HTTPException(403, "Insufficient permissions.")

    try:
        aid = uuid.UUID(account_id)
    except ValueError:
        raise HTTPException(422, "Invalid account ID.")

    account = await db.scalar(
        select(PaymentAccount).where(
            PaymentAccount.id == aid,
            PaymentAccount.org_id == org.id,
        )
    )
    if not account:
        raise HTTPException(404, "Payment account not found.")

    from sqlalchemy import update as sqla_update
    await db.execute(
        sqla_update(PaymentAccount)
        .where(
            PaymentAccount.org_id == org.id,
            PaymentAccount.provider == account.provider,
        )
        .values(is_default=False)
    )
    account.is_default = True
    await db.commit()
    await db.refresh(account)
    return account


@router_payment_accounts.delete("/{account_id}", status_code=204)
async def delete_account(
    slug: str,
    account_id: str,
    db: DBSession,
    org_access: OrgAccess,
):
    org, role, is_owner = org_access
    if not is_owner and role != "admin":
        raise HTTPException(403, "Insufficient permissions.")

    try:
        aid = uuid.UUID(account_id)
    except ValueError:
        raise HTTPException(422, "Invalid account ID.")

    account = await db.scalar(
        select(PaymentAccount).where(
            PaymentAccount.id == aid,
            PaymentAccount.org_id == org.id,
        )
    )
    if not account:
        raise HTTPException(404, "Payment account not found.")

    await acc_svc.delete_payment_account(db, account)
