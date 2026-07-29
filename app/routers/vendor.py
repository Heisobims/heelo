from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, EmailStr

from app.dependencies import DBSession, CurrentUser
from app.services import vendor_service as vsvc
from app.models.vendor import VENDOR_CATEGORIES, VENDOR_PRICE_RANGES

router_vendor = APIRouter(prefix="/api/v1/vendors", tags=["vendors"])


class VendorCreateRequest(BaseModel):
    business_name: str = Field(..., min_length=2, max_length=255)
    category: str
    description: str | None = Field(None, max_length=3000)
    tagline: str | None = Field(None, max_length=255)
    location_city: str | None = Field(None, max_length=255)
    location_country: str | None = Field(None, min_length=2, max_length=2)
    contact_email: str | None = Field(None, max_length=255)
    contact_phone: str | None = Field(None, max_length=30)
    website_url: str | None = Field(None, max_length=500)
    price_range: str | None = None


class VendorUpdateRequest(BaseModel):
    business_name: str | None = Field(None, min_length=2, max_length=255)
    category: str | None = None
    description: str | None = Field(None, max_length=3000)
    tagline: str | None = Field(None, max_length=255)
    location_city: str | None = Field(None, max_length=255)
    location_country: str | None = Field(None, min_length=2, max_length=2)
    contact_email: str | None = Field(None, max_length=255)
    contact_phone: str | None = Field(None, max_length=30)
    website_url: str | None = Field(None, max_length=500)
    price_range: str | None = None


class ContactVendorRequest(BaseModel):
    requester_name: str = Field(..., min_length=1, max_length=255)
    requester_email: str = Field(..., max_length=255)
    org_id: str | None = None
    event_name: str | None = Field(None, max_length=255)
    message: str | None = Field(None, max_length=2000)


def _vendor_dict(v) -> dict:
    return {
        "id": str(v.id),
        "slug": v.slug,
        "business_name": v.business_name,
        "category": v.category,
        "tagline": v.tagline,
        "description": v.description,
        "location_city": v.location_city,
        "location_country": v.location_country,
        "contact_email": v.contact_email,
        "contact_phone": v.contact_phone,
        "website_url": v.website_url,
        "cover_image_url": v.cover_image_url,
        "portfolio_urls": v.portfolio_urls or [],
        "price_range": v.price_range,
        "status": v.status,
        "is_verified": v.is_verified,
        "lead_count": v.lead_count,
        "created_at": v.created_at.isoformat(),
    }


@router_vendor.get("")
async def list_vendors(
    db: DBSession,
    q: str | None = Query(None),
    category: str | None = Query(None),
    city: str | None = Query(None),
    country: str | None = Query(None),
    price_range: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=100),
):
    vendors, total = await vsvc.list_vendors(
        db, q=q, category=category, city=city,
        country=country, price_range=price_range,
        page=page, per_page=per_page,
    )
    return {
        "success": True,
        "data": [_vendor_dict(v) for v in vendors],
        "meta": {"total": total, "page": page, "per_page": per_page},
    }


@router_vendor.get("/categories")
async def get_categories():
    return {"success": True, "data": VENDOR_CATEGORIES}


@router_vendor.get("/me")
async def get_my_vendor_profile(db: DBSession, current_user: CurrentUser):
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found. Register as a vendor first.")
    return {"success": True, "data": _vendor_dict(vendor)}


@router_vendor.post("", status_code=201)
async def create_vendor(
    data: VendorCreateRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    vendor = await vsvc.create_vendor(
        db,
        user_id=current_user.id,
        business_name=data.business_name,
        category=data.category,
        description=data.description,
        tagline=data.tagline,
        location_city=data.location_city,
        location_country=data.location_country,
        contact_email=data.contact_email,
        contact_phone=data.contact_phone,
        website_url=data.website_url,
        price_range=data.price_range,
    )
    return {"success": True, "data": _vendor_dict(vendor)}


@router_vendor.patch("/me")
async def update_my_vendor_profile(
    data: VendorUpdateRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found.")
    updates = data.model_dump(exclude_none=True)
    vendor = await vsvc.update_vendor(db, vendor, **updates)
    return {"success": True, "data": _vendor_dict(vendor)}


@router_vendor.get("/{vendor_slug}")
async def get_vendor(vendor_slug: str, db: DBSession):
    vendor = await vsvc.get_vendor_by_slug(db, vendor_slug)
    if not vendor or vendor.status != "active":
        raise HTTPException(404, "Vendor not found.")
    return {"success": True, "data": _vendor_dict(vendor)}


@router_vendor.post("/{vendor_slug}/contact", status_code=201)
async def contact_vendor(
    vendor_slug: str,
    data: ContactVendorRequest,
    db: DBSession,
):
    vendor = await vsvc.get_vendor_by_slug(db, vendor_slug)
    if not vendor or vendor.status != "active":
        raise HTTPException(404, "Vendor not found.")

    org_id = None
    if data.org_id:
        try:
            org_id = uuid.UUID(data.org_id)
        except ValueError:
            pass

    lead = await vsvc.create_lead(
        db,
        vendor,
        org_id=org_id,
        requester_name=data.requester_name,
        requester_email=data.requester_email,
        event_name=data.event_name,
        message=data.message,
    )
    return {
        "success": True,
        "data": {"id": str(lead.id)},
        "message": "Your enquiry has been sent! The vendor will get back to you.",
    }


@router_vendor.get("/me/leads")
async def get_my_leads(
    db: DBSession,
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
):
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found.")
    leads, total = await vsvc.get_vendor_leads(db, vendor.id, page=page)
    return {
        "success": True,
        "data": [
            {
                "id": str(l.id),
                "requester_name": l.requester_name,
                "requester_email": l.requester_email,
                "event_name": l.event_name,
                "message": l.message,
                "status": l.status,
                "created_at": l.created_at.isoformat(),
            }
            for l in leads
        ],
        "meta": {"total": total, "page": page},
    }
