from __future__ import annotations

import uuid
from io import BytesIO

import structlog
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from PIL import Image
from pydantic import BaseModel, Field, field_validator

from app.dependencies import CurrentUser, DBSession
from app.models.vendor import VENDOR_CATEGORIES
from app.services import vendor_service as vsvc

logger = structlog.get_logger()

router_vendor = APIRouter(prefix="/api/v1/vendors", tags=["vendors"])

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 MB
_MAX_PORTFOLIO_IMAGES = 3


def _validate_portfolio_urls(v: list[str] | None) -> list[str] | None:
    if v is not None and len(v) > _MAX_PORTFOLIO_IMAGES:
        raise ValueError(f"You can upload up to {_MAX_PORTFOLIO_IMAGES} portfolio samples.")
    return v


class VendorCreateRequest(BaseModel):
    business_name: str = Field(..., min_length=2, max_length=255)
    category: str
    description: str | None = Field(None, max_length=3000)
    tagline: str | None = Field(None, max_length=255)
    location_city: str | None = Field(None, max_length=255)
    location_country: str | None = Field(None, min_length=2, max_length=2)
    address: str | None = Field(None, max_length=1000)
    capacity: int | None = Field(None, gt=0, le=1_000_000)
    contact_email: str | None = Field(None, max_length=255)
    contact_phone: str | None = Field(None, max_length=30)
    website_url: str | None = Field(None, max_length=500)
    price_range: str | None = None
    # A profile image is required — vendors are discovered visually in the
    # marketplace grid, so a listing with no photo at all isn't useful.
    cover_image_url: str = Field(..., min_length=1)
    portfolio_urls: list[str] | None = Field(None, max_length=_MAX_PORTFOLIO_IMAGES)
    portfolio_link: str | None = Field(None, max_length=500)

    _check_portfolio = field_validator("portfolio_urls")(_validate_portfolio_urls)


class VendorUpdateRequest(BaseModel):
    business_name: str | None = Field(None, min_length=2, max_length=255)
    category: str | None = None
    description: str | None = Field(None, max_length=3000)
    tagline: str | None = Field(None, max_length=255)
    location_city: str | None = Field(None, max_length=255)
    location_country: str | None = Field(None, min_length=2, max_length=2)
    address: str | None = Field(None, max_length=1000)
    capacity: int | None = Field(None, gt=0, le=1_000_000)
    contact_email: str | None = Field(None, max_length=255)
    contact_phone: str | None = Field(None, max_length=30)
    website_url: str | None = Field(None, max_length=500)
    price_range: str | None = None
    cover_image_url: str | None = Field(None, min_length=1)
    portfolio_urls: list[str] | None = Field(None, max_length=_MAX_PORTFOLIO_IMAGES)
    portfolio_link: str | None = Field(None, max_length=500)

    _check_portfolio = field_validator("portfolio_urls")(_validate_portfolio_urls)


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
        "address": v.address,
        "capacity": v.capacity,
        "contact_email": v.contact_email,
        "contact_phone": v.contact_phone,
        "website_url": v.website_url,
        "cover_image_url": v.cover_image_url,
        "portfolio_urls": v.portfolio_urls or [],
        "portfolio_link": v.portfolio_link,
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
    min_capacity: int | None = Query(None, gt=0),
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=100),
):
    vendors, total = await vsvc.list_vendors(
        db,
        q=q,
        category=category,
        city=city,
        country=country,
        price_range=price_range,
        min_capacity=min_capacity,
        page=page,
        per_page=per_page,
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
        address=data.address,
        capacity=data.capacity,
        contact_email=data.contact_email,
        contact_phone=data.contact_phone,
        website_url=data.website_url,
        price_range=data.price_range,
        cover_image_url=data.cover_image_url,
        portfolio_urls=data.portfolio_urls,
        portfolio_link=data.portfolio_link,
    )
    return {"success": True, "data": _vendor_dict(vendor)}


@router_vendor.post("/upload-image")
async def upload_vendor_image(
    current_user: CurrentUser,
    file: UploadFile = File(...),
):
    """Uploads a single image (profile photo or a portfolio sample) and
    returns its URL. Used both during signup — before the vendor row exists
    — and afterward to update an existing profile, so it's scoped by user
    id rather than vendor id."""
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, "Unsupported file type. Use JPEG, PNG or WebP.")
    image_bytes = await file.read()
    if len(image_bytes) > _MAX_UPLOAD_SIZE:
        raise HTTPException(413, "Image must be under 5 MB.")
    try:
        Image.open(BytesIO(image_bytes)).verify()
    except Exception as err:
        raise HTTPException(400, "File does not appear to be a valid image.") from err

    from app.utils import storage

    url = await storage.upload_image(
        image_bytes,
        folder=f"vendors/{current_user.id}",
        max_width=1600,
    )
    return {"success": True, "data": {"url": url}}


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

    try:
        from app.utils.email import send_vendor_lead_email

        send_vendor_lead_email(
            vendor.contact_email or vendor.user.email,
            vendor.business_name,
            data.requester_name,
            data.event_name,
            data.message,
        )
    except Exception as exc:
        logger.warning("vendor.lead_email_failed", vendor_id=str(vendor.id), error=str(exc))

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
