from __future__ import annotations

import re
import uuid
from typing import Literal

import httpx
import structlog
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.affiliate import AffiliatePayout, EventAffiliate
from app.models.event import Event

logger = structlog.get_logger()


def _sanitize_code(code: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", code).upper()
    return cleaned[:40] or uuid.uuid4().hex[:8].upper()


async def create_affiliate(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    promoter_name: str,
    promoter_email: str,
    affiliate_code: str,
    commission_type: str = "percentage",
    commission_rate: float = 10.0,
    promoter_phone: str | None = None,
    payout_bank_code: str | None = None,
    payout_account_number: str | None = None,
    payout_account_name: str | None = None,
) -> EventAffiliate:
    code = _sanitize_code(affiliate_code)

    existing = await db.scalar(
        select(EventAffiliate).where(
            EventAffiliate.event_id == event_id,
            func.upper(EventAffiliate.affiliate_code) == code,
        )
    )
    if existing:
        raise HTTPException(400, f"Referral code '{code}' already exists for this event.")

    recipient_code = None
    if settings.PAYSTACK_SECRET_KEY and payout_bank_code and payout_account_number:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.post(
                    "https://api.paystack.co/transferrecipient",
                    headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
                    json={
                        "type": "nuban",
                        "name": payout_account_name or promoter_name,
                        "account_number": payout_account_number,
                        "bank_code": payout_bank_code,
                        "currency": "NGN",
                    },
                )
                if res.status_code == 201:
                    rdata = res.json().get("data", {})
                    recipient_code = rdata.get("recipient_code")
        except Exception as exc:
            logger.warning("affiliate.recipient_create_failed", error=str(exc))

    affiliate = EventAffiliate(
        event_id=event_id,
        promoter_name=promoter_name.strip(),
        promoter_email=promoter_email.strip().lower(),
        promoter_phone=promoter_phone.strip() if promoter_phone else None,
        affiliate_code=code,
        commission_type=(
            commission_type if commission_type in ("percentage", "fixed") else "percentage"
        ),
        commission_rate=commission_rate,
        payout_bank_code=payout_bank_code,
        payout_account_number=payout_account_number,
        payout_account_name=payout_account_name,
        recipient_code=recipient_code,
        clicks_count=0,
        tickets_sold=0,
        gross_sales=0.0,
        commission_earned=0.0,
        commission_paid=0.0,
        payout_status="pending",
        is_active=True,
    )
    db.add(affiliate)
    await db.commit()
    await db.refresh(affiliate)
    return affiliate


async def list_org_affiliates(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    event_id: uuid.UUID | None = None,
) -> list[EventAffiliate]:
    stmt = (
        select(EventAffiliate)
        .join(Event, EventAffiliate.event_id == Event.id)
        .where(Event.org_id == org_id)
        .options(selectinload(EventAffiliate.event))
        .order_by(EventAffiliate.created_at.desc())
    )
    if event_id:
        stmt = stmt.where(EventAffiliate.event_id == event_id)

    result = await db.scalars(stmt)
    return list(result.all())


async def get_affiliate(db: AsyncSession, affiliate_id: uuid.UUID) -> EventAffiliate | None:
    return await db.scalar(
        select(EventAffiliate)
        .where(EventAffiliate.id == affiliate_id)
        .options(selectinload(EventAffiliate.event))
    )


async def get_affiliate_by_code(
    db: AsyncSession, event_id: uuid.UUID, code: str
) -> EventAffiliate | None:
    cleaned = code.strip().upper()
    return await db.scalar(
        select(EventAffiliate).where(
            EventAffiliate.event_id == event_id,
            func.upper(EventAffiliate.affiliate_code) == cleaned,
            EventAffiliate.is_active.is_(True),
        )
    )


async def record_affiliate_click(db: AsyncSession, affiliate: EventAffiliate) -> None:
    affiliate.clicks_count += 1
    await db.commit()


async def attribute_order_to_affiliate(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    referral_code: str,
    order_amount: float,
    tickets_count: int = 1,
) -> EventAffiliate | None:
    affiliate = await get_affiliate_by_code(db, event_id, referral_code)
    if not affiliate:
        return None

    affiliate.tickets_sold += max(1, tickets_count)
    affiliate.gross_sales = float(affiliate.gross_sales) + float(order_amount)

    if affiliate.commission_type == "percentage":
        new_commission = float(order_amount) * (float(affiliate.commission_rate) / 100.0)
    else:
        new_commission = float(affiliate.commission_rate) * max(1, tickets_count)

    affiliate.commission_earned = float(affiliate.commission_earned) + new_commission
    if affiliate.commission_owed > 0:
        affiliate.payout_status = "pending" if float(affiliate.commission_paid) == 0 else "partial"

    await db.commit()
    await db.refresh(affiliate)
    return affiliate


async def disburse_affiliate_payout(
    db: AsyncSession,
    affiliate: EventAffiliate,
    *,
    amount: float,
    method: Literal["manual", "paystack_transfer"] = "manual",
    notes: str | None = None,
) -> AffiliatePayout:
    owed = affiliate.commission_owed
    if amount <= 0:
        raise HTTPException(400, "Payout amount must be greater than zero.")
    if amount > owed + 0.01:
        raise HTTPException(
            400, f"Payout amount ({amount}) cannot exceed commission owed ({owed:.2f})."
        )

    transfer_reference = f"aff_payout_{uuid.uuid4().hex}"
    transfer_code = None
    status = "completed"

    if method == "paystack_transfer":
        if not settings.PAYSTACK_SECRET_KEY:
            raise HTTPException(503, "Paystack is not configured for automated transfers.")
        if not affiliate.recipient_code:
            raise HTTPException(400, "Affiliate has no Paystack recipient code configured.")

        amount_kobo = int(round(amount * 100))
        payload = {
            "source": "balance",
            "amount": amount_kobo,
            "recipient": affiliate.recipient_code,
            "reason": f"Commission payout for {affiliate.promoter_name}",
            "reference": transfer_reference,
        }
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                res = await client.post(
                    "https://api.paystack.co/transfer",
                    headers={
                        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                rdata = res.json()
                if not rdata.get("status"):
                    raise HTTPException(400, f"Transfer rejected: {rdata.get('message')}")
                transfer_code = rdata.get("data", {}).get("transfer_code")
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("affiliate.transfer_failed", error=str(exc))
            raise HTTPException(502, f"Failed to initiate bank transfer: {str(exc)}") from exc

    payout = AffiliatePayout(
        affiliate_id=affiliate.id,
        amount=amount,
        currency="NGN",
        transfer_reference=transfer_reference,
        transfer_code=transfer_code,
        status=status,
        method=method,
        notes=notes,
    )
    db.add(payout)

    affiliate.commission_paid = float(affiliate.commission_paid) + amount
    if affiliate.commission_paid >= float(affiliate.commission_earned) - 0.01:
        affiliate.payout_status = "paid"
    else:
        affiliate.payout_status = "partial"

    await db.commit()
    await db.refresh(payout)
    return payout


async def list_affiliate_payouts(
    db: AsyncSession, affiliate_id: uuid.UUID
) -> list[AffiliatePayout]:
    stmt = (
        select(AffiliatePayout)
        .where(AffiliatePayout.affiliate_id == affiliate_id)
        .order_by(AffiliatePayout.created_at.desc())
    )
    result = await db.scalars(stmt)
    return list(result.all())

