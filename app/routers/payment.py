from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from app.dependencies import DBSession, OrgAccess
from app.models.payment import PaymentAccount
from app.permissions import Permission, require_permission
from app.schemas.payment import (
    FlutterwaveSubaccountRequest,
    ManualAccountRequest,
    PaymentAccountOut,
    PaystackSubaccountRequest,
)
from app.services import billing_service as billing_svc
from app.services import payment_account_service as acc_svc
from app.services import payment_service as pay_svc

# ── Webhooks - raw body, no JSON body parsing by FastAPI ─────────────────────

router_webhooks = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


@router_webhooks.post("/paystack", status_code=200)
async def paystack_webhook(request: Request, db: DBSession):
    body = await request.body()
    signature = request.headers.get("x-paystack-signature", "")

    if not pay_svc.verify_paystack_signature(body, signature):
        raise HTTPException(400, "Invalid signature.")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as err:
        raise HTTPException(400, "Invalid JSON payload.") from err

    event = payload.get("event", "")
    data = payload.get("data", {})

    if event == "charge.success":
        reference = data.get("reference", "")
        if reference.startswith("tixdoo_plan_"):
            invoice = await pay_svc.verify_paystack_plan(db, reference)
            if invoice:
                await billing_svc.confirm_plan_invoice(db, invoice)
        elif reference.startswith("booth_"):
            from sqlalchemy import select

            from app.models.vendor import BoothApplication
            from app.services import vendor_service as vsvc

            app_record = await db.scalar(
                select(BoothApplication).where(BoothApplication.payment_reference == reference)
            )
            if app_record and app_record.status != "paid":
                await vsvc.confirm_booth_payment(db, app_record, payment_reference=reference)
                try:
                    from app.tasks.email import send_booth_application_confirmed

                    send_booth_application_confirmed.delay(str(app_record.id))
                except Exception:
                    pass
        elif reference.startswith("vbook_"):
            from sqlalchemy import select
            from app.models.vendor import VendorBooking
            from app.services import vendor_service as vsvc

            booking = await db.scalar(
                select(VendorBooking).where(VendorBooking.payment_reference == reference)
            )
            if booking and booking.status == "pending_payment":
                await vsvc.confirm_booking_payment(
                    db, booking, payment_reference=reference, payment_method="paystack"
                )
        elif reference.startswith("vsub_"):
            from sqlalchemy import select
            from app.models.vendor import Vendor, VendorSubscription
            from app.services import vendor_service as vsvc

            sub = await db.scalar(
                select(VendorSubscription).where(VendorSubscription.payment_reference == reference)
            )
            if sub and sub.status != "active":
                vendor = await db.get(Vendor, sub.vendor_id)
                if vendor:
                    await vsvc.activate_vendor_subscription(
                        db, vendor, tier=sub.tier, payment_reference=reference
                    )
        elif reference.startswith("vfeat_"):
            from sqlalchemy import select
            from app.models.vendor import Vendor, VendorFeaturedCampaign

            camp = await db.scalar(
                select(VendorFeaturedCampaign).where(
                    VendorFeaturedCampaign.payment_reference == reference
                )
            )
            if camp and camp.status != "active":
                camp.status = "active"
                vendor = await db.get(Vendor, camp.vendor_id)
                if vendor:
                    vendor.is_featured = True
                    vendor.featured_until = camp.end_date
                await db.commit()
        elif reference.startswith("vlead_"):
            from sqlalchemy import select
            from app.models.vendor import Vendor, VendorLeadCreditPurchase

            lcp = await db.scalar(
                select(VendorLeadCreditPurchase).where(
                    VendorLeadCreditPurchase.payment_reference == reference
                )
            )
            if lcp and lcp.status != "completed":
                lcp.status = "completed"
                vendor = await db.get(Vendor, lcp.vendor_id)
                if vendor:
                    vendor.lead_credits_balance += lcp.credits_purchased
                await db.commit()
        elif reference.startswith("tixdoo_"):
            await pay_svc.verify_paystack(db, reference)
    elif event == "transfer.success":
        reference = data.get("reference", "")
        if reference.startswith("payout_"):
            try:
                payout_id = uuid.UUID(reference[7:])
                from app.models.payment import Payout
                from app.services import payout_service as payout_svc

                payout = await db.get(Payout, payout_id)
                if payout and payout.status != "paid":
                    await payout_svc.mark_payout_paid(
                        db, payout, provider_reference=data.get("transfer_code") or reference
                    )
            except ValueError:
                pass
        elif reference.startswith("aff_payout_"):
            try:
                payout_id = uuid.UUID(reference[11:])
                from app.models.affiliate import AffiliatePayout, EventAffiliate

                aff_payout = await db.get(AffiliatePayout, payout_id)
                if aff_payout and aff_payout.status != "completed":
                    aff_payout.status = "completed"
                    aff_payout.transfer_code = data.get("transfer_code") or reference
                    aff = await db.get(EventAffiliate, aff_payout.affiliate_id)
                    if aff:
                        aff.commission_paid = float(aff.commission_paid) + float(aff_payout.amount)
                        if aff.commission_paid >= aff.commission_earned:
                            aff.payout_status = "paid"
                        else:
                            aff.payout_status = "partial"
                    await db.commit()
            except Exception as err:
                logger.warning("affiliate.webhook_transfer_failed", error=str(err))
        elif reference.startswith("vpayout_"):
            try:
                payout_id = uuid.UUID(reference[8:])
                from app.models.vendor import VendorPayout
                from app.services import vendor_service as vsvc

                payout = await db.get(VendorPayout, payout_id)
                if payout and payout.status != "completed":
                    await vsvc.disburse_vendor_payout(
                        db,
                        payout,
                        provider_reference=reference,
                        transfer_code=data.get("transfer_code"),
                    )
            except ValueError:
                pass
    elif event in ("transfer.failed", "transfer.reversed"):
        reference = data.get("reference", "")
        if reference.startswith("payout_"):
            try:
                payout_id = uuid.UUID(reference[7:])
                from app.models.payment import Payout
                from app.services import payout_service as payout_svc

                payout = await db.get(Payout, payout_id)
                if payout and payout.status != "paid":
                    await payout_svc.mark_payout_failed(
                        db, payout, reason=data.get("reason") or "Transfer failed or reversed"
                    )
            except ValueError:
                pass
        elif reference.startswith("vpayout_"):
            try:
                payout_id = uuid.UUID(reference[8:])
                from app.models.vendor import Vendor, VendorPayout

                payout = await db.get(VendorPayout, payout_id)
                if payout and payout.status != "failed":
                    payout.status = "failed"
                    payout.failure_reason = data.get("reason") or "Transfer failed or reversed"
                    vendor = await db.get(Vendor, payout.vendor_id)
                    if vendor:
                        vendor.payable_balance = float(vendor.payable_balance) + float(payout.amount)
                        vendor.total_withdrawn = max(0.0, float(vendor.total_withdrawn) - float(payout.amount))
                    await db.commit()
            except ValueError:
                pass

    return {"status": "ok"}


@router_webhooks.post("/flutterwave", status_code=200)
async def flutterwave_webhook(request: Request, db: DBSession):
    body = await request.body()
    signature = request.headers.get("verif-hash", "")

    if not pay_svc.verify_flutterwave_signature(signature):
        raise HTTPException(400, "Invalid signature.")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as err:
        raise HTTPException(400, "Invalid JSON payload.") from err

    if payload.get("status") == "successful":
        tx_data = payload.get("data", {})
        tx_id = tx_data.get("id")
        tx_ref = tx_data.get("tx_ref", "")
        if tx_id and tx_ref.startswith("tixdoo_plan_"):
            invoice = await pay_svc.verify_flutterwave_plan(db, int(tx_id))
            if invoice:
                await billing_svc.confirm_plan_invoice(db, invoice)
        elif tx_id and tx_ref.startswith("tixdoo_"):
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
    except stripe.error.SignatureVerificationError as err:
        raise HTTPException(400, "Invalid Stripe signature.") from err
    except Exception as err:
        raise HTTPException(400, "Invalid Stripe payload.") from err

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata") or {}

        if metadata.get("kind") == "plan_invoice":
            invoice_id_str = metadata.get("invoice_id")
            if invoice_id_str:
                try:
                    invoice_id = uuid.UUID(invoice_id_str)
                except ValueError:
                    return {"status": "ok"}
                from app.models.payment import PlanInvoice

                invoice = await db.get(PlanInvoice, invoice_id)
                if invoice and invoice.status != "paid":
                    invoice.provider_reference = session.get("payment_intent") or session["id"]
                    await billing_svc.confirm_plan_invoice(db, invoice)
            return {"status": "ok"}

        order_id_str = metadata.get("order_id")
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

    elif event["type"] == "account.updated":
        acct = event["data"]["object"]
        account = await db.scalar(
            select(PaymentAccount).where(
                PaymentAccount.provider == "stripe",
                PaymentAccount.provider_account_id == acct["id"],
            )
        )
        if account:
            account.is_verified = bool(
                acct.get("details_submitted") and acct.get("payouts_enabled")
            )
            await db.commit()

    return {"status": "ok"}


# ── Payment account management ────────────────────────────────────────────────

router_payment_accounts = APIRouter(
    prefix="/api/v1/organizations/{slug}/payment-accounts",
    tags=["payment-accounts"],
)

PaymentAccountsManageAccess = Annotated[
    tuple, Depends(require_permission(Permission.PAYMENT_ACCOUNTS_MANAGE))
]


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


@router_payment_accounts.get("/flutterwave/banks")
async def get_flutterwave_banks(slug: str, org_access: OrgAccess, country: str = "NG"):
    org_access  # auth check only
    banks = await acc_svc.list_flutterwave_banks(country=country)
    return {"success": True, "data": banks}


@router_payment_accounts.get("/flutterwave/resolve")
async def resolve_flutterwave_account_route(
    slug: str,
    account_number: str,
    bank_code: str,
    db: DBSession,
    org_access: OrgAccess,
):
    org_access  # auth check only
    result = await acc_svc.resolve_flutterwave_account(account_number, bank_code)
    if not result:
        raise HTTPException(422, "Could not resolve account. Check the account number and bank.")
    return {"success": True, "data": result}


@router_payment_accounts.post("/paystack", response_model=PaymentAccountOut, status_code=201)
async def connect_paystack(
    slug: str,
    data: PaystackSubaccountRequest,
    db: DBSession,
    org_access: PaymentAccountsManageAccess,
):
    org, role, is_owner = org_access
    account = await acc_svc.create_paystack_subaccount(db, org.id, data, org)
    return account


@router_payment_accounts.post("/flutterwave", response_model=PaymentAccountOut, status_code=201)
async def connect_flutterwave(
    slug: str,
    data: FlutterwaveSubaccountRequest,
    db: DBSession,
    org_access: PaymentAccountsManageAccess,
):
    org, role, is_owner = org_access
    account = await acc_svc.create_flutterwave_subaccount(db, org.id, data, org)
    return account


@router_payment_accounts.post("/stripe/connect")
async def connect_stripe(
    slug: str,
    db: DBSession,
    org_access: PaymentAccountsManageAccess,
):
    org, role, is_owner = org_access
    url = await acc_svc.create_stripe_connect_account(db, org.id, org)
    return {"success": True, "data": {"url": url}}


@router_payment_accounts.post("/manual", response_model=PaymentAccountOut, status_code=201)
async def connect_manual_account(
    slug: str,
    data: ManualAccountRequest,
    db: DBSession,
    org_access: PaymentAccountsManageAccess,
):
    org, role, is_owner = org_access
    account = await acc_svc.add_manual_account(db, org.id, data, org.currency or "NGN")
    return account


@router_payment_accounts.patch("/{account_id}/set-default", response_model=PaymentAccountOut)
async def set_default_account(
    slug: str,
    account_id: str,
    db: DBSession,
    org_access: PaymentAccountsManageAccess,
):
    org, role, is_owner = org_access

    try:
        aid = uuid.UUID(account_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid account ID.") from err

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
    org_access: PaymentAccountsManageAccess,
):
    org, role, is_owner = org_access

    try:
        aid = uuid.UUID(account_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid account ID.") from err

    account = await db.scalar(
        select(PaymentAccount).where(
            PaymentAccount.id == aid,
            PaymentAccount.org_id == org.id,
        )
    )
    if not account:
        raise HTTPException(404, "Payment account not found.")

    await acc_svc.delete_payment_account(db, account)
