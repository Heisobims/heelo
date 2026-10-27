from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.dependencies import DBSession, OrgAccess
from app.services import affiliate_service as aff_svc

router_affiliate = APIRouter(tags=["affiliates"])


class AffiliateCreateRequest(BaseModel):
    promoter_name: str = Field(..., min_length=2, max_length=255)
    promoter_email: str = Field(..., max_length=255)
    promoter_phone: str | None = Field(None, max_length=50)
    affiliate_code: str = Field(..., min_length=2, max_length=50)
    commission_type: str = Field("percentage", pattern="^(percentage|fixed)$")
    commission_rate: float = Field(..., gt=0)
    payout_bank_code: str | None = Field(None, max_length=50)
    payout_account_number: str | None = Field(None, max_length=50)
    payout_account_name: str | None = Field(None, max_length=255)


class AffiliatePayoutRequest(BaseModel):
    amount: float = Field(..., gt=0)
    method: str = Field("manual", pattern="^(manual|paystack_transfer)$")
    notes: str | None = Field(None, max_length=1000)


def _affiliate_dict(a) -> dict:
    event_title = None
    event_slug = None
    if "event" in a.__dict__ and a.event is not None:
        event_title = a.event.title
        event_slug = a.event.slug

    return {
        "id": str(a.id),
        "event_id": str(a.event_id),
        "event_title": event_title,
        "event_slug": event_slug,
        "promoter_name": a.promoter_name,
        "promoter_email": a.promoter_email,
        "promoter_phone": a.promoter_phone,
        "affiliate_code": a.affiliate_code,
        "commission_type": a.commission_type,
        "commission_rate": float(a.commission_rate),
        "clicks_count": a.clicks_count,
        "tickets_sold": a.tickets_sold,
        "gross_sales": float(a.gross_sales),
        "commission_earned": float(a.commission_earned),
        "commission_paid": float(a.commission_paid),
        "commission_owed": a.commission_owed,
        "payout_status": a.payout_status,
        "payout_bank_code": a.payout_bank_code,
        "payout_account_number": a.payout_account_number,
        "payout_account_name": a.payout_account_name,
        "has_automated_payout": bool(a.recipient_code),
        "is_active": a.is_active,
        "created_at": a.created_at.isoformat(),
    }


def _payout_dict(p) -> dict:
    return {
        "id": str(p.id),
        "affiliate_id": str(p.affiliate_id),
        "amount": float(p.amount),
        "currency": p.currency,
        "transfer_reference": p.transfer_reference,
        "transfer_code": p.transfer_code,
        "status": p.status,
        "method": p.method,
        "notes": p.notes,
        "created_at": p.created_at.isoformat(),
    }


@router_affiliate.get("/api/v1/organizations/{slug}/affiliates")
async def list_affiliates(
    slug: str,
    db: DBSession,
    org_access: OrgAccess,
    event_id: uuid.UUID | None = None,
):
    org = org_access[0]
    affiliates = await aff_svc.list_org_affiliates(db, org_id=org.id, event_id=event_id)
    return {"success": True, "data": [_affiliate_dict(a) for a in affiliates]}


@router_affiliate.post(
    "/api/v1/organizations/{slug}/events/{event_id}/affiliates", status_code=201
)
async def create_event_affiliate(
    slug: str,
    event_id: uuid.UUID,
    data: AffiliateCreateRequest,
    db: DBSession,
    org_access: OrgAccess,
):
    from sqlalchemy import select

    from app.models.event import Event

    org = org_access[0]
    event = await db.scalar(select(Event).where(Event.id == event_id, Event.org_id == org.id))
    if not event:
        raise HTTPException(404, "Event not found.")

    affiliate = await aff_svc.create_affiliate(
        db,
        event_id=event_id,
        promoter_name=data.promoter_name,
        promoter_email=data.promoter_email,
        affiliate_code=data.affiliate_code,
        commission_type=data.commission_type,
        commission_rate=data.commission_rate,
        promoter_phone=data.promoter_phone,
        payout_bank_code=data.payout_bank_code,
        payout_account_number=data.payout_account_number,
        payout_account_name=data.payout_account_name,
    )
    return {"success": True, "data": _affiliate_dict(affiliate)}


@router_affiliate.post("/api/v1/organizations/{slug}/affiliates/{affiliate_id}/payout")
async def disburse_payout(
    slug: str,
    affiliate_id: uuid.UUID,
    data: AffiliatePayoutRequest,
    db: DBSession,
    org_access: OrgAccess,
):
    aff = await aff_svc.get_affiliate(db, affiliate_id)
    if not aff:
        raise HTTPException(404, "Affiliate not found.")

    payout = await aff_svc.disburse_affiliate_payout(
        db,
        aff,
        amount=data.amount,
        method=data.method,  # type: ignore
        notes=data.notes,
    )
    return {
        "success": True,
        "data": _payout_dict(payout),
        "affiliate": _affiliate_dict(aff),
        "message": "Commission payout disbursed successfully.",
    }


@router_affiliate.get("/api/v1/organizations/{slug}/affiliates/{affiliate_id}/payouts")
async def get_payouts(
    slug: str,
    affiliate_id: uuid.UUID,
    db: DBSession,
    org_access: OrgAccess,
):
    payouts = await aff_svc.list_affiliate_payouts(db, affiliate_id)
    return {"success": True, "data": [_payout_dict(p) for p in payouts]}


@router_affiliate.get("/r/{code}")
async def affiliate_short_link(code: str, db: DBSession):
    """Direct referral link: increments clicks, drops cookie, redirects to event page."""
    from sqlalchemy import func, select
    from sqlalchemy.orm import selectinload

    from app.models.affiliate import EventAffiliate

    aff = await db.scalar(
        select(EventAffiliate)
        .where(
            func.upper(EventAffiliate.affiliate_code) == code.strip().upper(),
            EventAffiliate.is_active.is_(True),
        )
        .options(selectinload(EventAffiliate.event))
    )
    if not aff or not aff.event:
        raise HTTPException(404, "Referral link expired or not found.")

    await aff_svc.record_affiliate_click(db, aff)

    response = RedirectResponse(f"/e/{aff.event.slug}?ref={aff.affiliate_code}", status_code=302)
    response.set_cookie(
        key="tixdoo_ref",
        value=f"{aff.event_id}:{aff.affiliate_code}",
        max_age=30 * 24 * 3600,
        httponly=False,
        samesite="lax",
    )
    return response
