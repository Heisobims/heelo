from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path

import structlog
from fastapi import APIRouter, File, HTTPException, Query, Request, Response, UploadFile
from PIL import Image
from pydantic import BaseModel, Field, field_validator

from app.dependencies import CurrentUser, DBSession, OrgAccess
from app.models.vendor import VENDOR_CATEGORIES
from sqlalchemy import select
from app.services import vendor_service as vsvc
from app.utils.qr_code import fetch_logo_bytes, generate_qr_png
from app.utils.rate_limit import check_and_record, get_client_ip

logger = structlog.get_logger()

router_vendor = APIRouter(prefix="/api/v1/vendors", tags=["vendors"])

# Public, unauthenticated - spammable to flood a vendor's inbox/leads table.
_CONTACT_MAX_PER_IP = 10
_CONTACT_WINDOW_SECONDS = 60 * 60

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
    # A profile image is required - vendors are discovered visually in the
    # marketplace grid, so a listing with no photo at all isn't useful.
    cover_image_url: str = Field(..., min_length=1)
    logo_url: str | None = None
    service_areas: list[str] | None = None
    social_links: dict[str, str] | None = None
    operating_hours: dict[str, dict] | None = None
    starting_price: float | None = None
    currency: str = "NGN"
    faqs: list[dict] | None = None
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
    logo_url: str | None = None
    service_areas: list[str] | None = None
    social_links: dict[str, str] | None = None
    operating_hours: dict[str, dict] | None = None
    starting_price: float | None = None
    currency: str | None = None
    faqs: list[dict] | None = None
    portfolio_urls: list[str] | None = None
    portfolio_link: str | None = Field(None, max_length=500)


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
        "logo_url": v.logo_url,
        "service_areas": v.service_areas or [],
        "social_links": v.social_links or {},
        "operating_hours": v.operating_hours or {},
        "starting_price": float(v.starting_price) if v.starting_price is not None else None,
        "currency": v.currency or "NGN",
        "faqs": v.faqs or [],
        "portfolio_urls": v.portfolio_urls or [],
        "portfolio_link": v.portfolio_link,
        "price_range": v.price_range,
        "status": v.status,
        "is_verified": v.is_verified,
        "verification_status": v.verification_status,
        "subscription_tier": v.subscription_tier,
        "lead_credits_balance": v.lead_credits_balance,
        "rating_avg": float(v.rating_avg) if v.rating_avg is not None else 0.0,
        "reviews_count": v.reviews_count,
        "is_featured": v.is_featured,
        "payable_balance": float(v.payable_balance) if v.payable_balance is not None else 0.0,
        "total_earned": float(v.total_earned) if v.total_earned is not None else 0.0,
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
    verified_only: bool = Query(False),
    min_rating: float | None = Query(None, ge=1, le=5),
    sort_by: str = Query("relevance"),
    min_capacity: int | None = Query(None, gt=0),
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=100),
):
    if min_capacity:
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
    else:
        vendors, total = await vsvc.list_vendors_advanced(
            db,
            q=q,
            category=category,
            city=city,
            country=country,
            price_range=price_range,
            verified_only=verified_only,
            min_rating=min_rating,
            sort_by=sort_by,
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
        currency=data.currency,
        starting_price=data.starting_price,
    )
    return {"success": True, "data": _vendor_dict(vendor)}


@router_vendor.post("/upload-image")
async def upload_vendor_image(
    current_user: CurrentUser,
    file: UploadFile = File(...),
):
    """Uploads a single image (profile photo or a portfolio sample) and
    returns its URL. Used both during signup - before the vendor row exists
    - and afterward to update an existing profile, so it's scoped by user
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


@router_vendor.post("/upload-document")
async def upload_vendor_document(
    current_user: CurrentUser,
    file: UploadFile = File(...),
):
    """Uploads a quotation document or brochure (PDF or image up to 15MB)
    and returns its public URL and original filename."""
    allowed_types = {
        "application/pdf",
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
    }
    ext = Path(file.filename or "doc").suffix.lower()
    if file.content_type not in allowed_types and ext not in {".pdf", ".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(400, "Unsupported file format. Please upload a PDF document or image (JPG, PNG, WebP).")

    doc_bytes = await file.read()
    if len(doc_bytes) > 15 * 1024 * 1024:
        raise HTTPException(413, "Document size must be under 15 MB.")

    if ext not in {".pdf", ".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".pdf" if file.content_type == "application/pdf" else ".jpg"

    safe_name = f"{uuid.uuid4().hex}{ext}"
    key = f"vendors/{current_user.id}/quotations/{safe_name}"

    from app.utils import storage

    content_type = file.content_type or ("application/pdf" if ext == ".pdf" else "image/jpeg")
    url = await storage.upload_bytes(doc_bytes, key=key, content_type=content_type)
    return {
        "success": True,
        "data": {
            "url": url,
            "filename": file.filename or safe_name,
        },
    }


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
    request: Request,
):
    check_and_record(
        f"vendor_contact:ip:{get_client_ip(request)}",
        max_attempts=_CONTACT_MAX_PER_IP,
        window_seconds=_CONTACT_WINDOW_SECONDS,
        error_message="Too many enquiries sent. Please try again later.",
    )

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
        from app.tasks.email import send_vendor_lead_notification

        send_vendor_lead_notification.delay(str(lead.id))
    except Exception as exc:
        logger.warning("vendor.lead_email_enqueue_failed", vendor_id=str(vendor.id), error=str(exc))

    return {
        "success": True,
        "data": {"id": str(lead.id)},
        "message": "Your enquiry has been sent! The vendor will get back to you.",
    }


@router_vendor.get("/me/qr.png", include_in_schema=False)
async def my_vendor_qr_image(
    db: DBSession,
    current_user: CurrentUser,
    request: Request,
):
    """QR code encoding the vendor's public profile URL, for the vendor to
    display/print/share so people can scan it to view their profile."""
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found.")

    url = f"{str(request.base_url).rstrip('/')}/vendors/{vendor.slug}"
    logo_bytes = await fetch_logo_bytes(vendor.logo_url) if vendor.logo_url else None
    qr_bytes = generate_qr_png(
        url,
        logo_bytes=logo_bytes,
        org_name=vendor.business_name,
    )
    return Response(
        content=qr_bytes,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


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




# ── New Schemas ──────────────────────────────────────────────────────────────
class ServiceListingCreateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    category: str
    description: str | None = None
    pricing_type: str = "fixed"
    price: float = Field(0.0, ge=0)
    price_max: float | None = None
    currency: str = "NGN"
    inclusions: list[str] | None = None
    image_urls: list[str] | None = None
    duration_hours: int | None = None


class ServiceListingUpdateRequest(BaseModel):
    title: str | None = None
    category: str | None = None
    description: str | None = None
    pricing_type: str | None = None
    price: float | None = None
    price_max: float | None = None
    inclusions: list[str] | None = None
    image_urls: list[str] | None = None
    duration_hours: int | None = None
    is_active: bool | None = None


class QuoteRequestCreate(BaseModel):
    event_name: str = Field(..., min_length=2, max_length=255)
    service_category: str
    requirements: str = Field(..., min_length=5, max_length=5000)
    event_type: str | None = None
    event_date: str | None = None
    event_location: str | None = None
    expected_attendance: int | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    currency: str = "NGN"
    preferred_deadline: str | None = None
    attachments: list[str] | None = None
    vendor_ids: list[str] | None = None


class QuotationSubmitRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    scope_of_work: str = Field(..., min_length=5, max_length=5000)
    total_amount: float = Field(..., gt=0)
    items: list[dict] | None = None
    currency: str = "NGN"
    deposit_required: float = 0.0
    valid_until: str | None = None
    notes: str | None = None
    attachment_url: str | None = None
    attachment_name: str | None = None


class BookingCreateRequest(BaseModel):
    quotation_id: str | None = None
    service_listing_id: str | None = None
    vendor_id: str | None = None
    event_name: str | None = None
    event_date: str | None = None
    event_location: str | None = None
    cancellation_policy: str = "moderate"
    cancellation_terms: str | None = None


class VendorDeliverySubmitRequest(BaseModel):
    proof_notes: str | None = Field(None, max_length=2000)
    proof_urls: list[str] | None = None


class VendorBookingDisputeRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=2000)


class VendorReviewCreateRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    title: str | None = Field(None, max_length=255)
    content: str = Field(..., min_length=5, max_length=2000)


class ReviewResponseRequest(BaseModel):
    response: str = Field(..., min_length=2, max_length=2000)


class VendorPayoutRequest(BaseModel):
    amount: float = Field(..., gt=0)
    method: str = "manual"
    account_details: dict | None = None


class VendorVerificationSubmit(BaseModel):
    business_registration_number: str | None = None
    tax_id: str | None = None
    document_urls: list[str] | None = None
    government_id_url: str | None = None
    notes: str | None = None


class VendorSubscriptionCheckoutRequest(BaseModel):
    tier: str = Field(..., min_length=2, max_length=30)


class VendorCampaignCheckoutRequest(BaseModel):
    placement: str = "marketplace_top"
    duration_days: int = 30
    category: str | None = None


class VendorLeadCreditCheckoutRequest(BaseModel):
    credits_count: int = Field(5, ge=1)


# ── Serializers ───────────────────────────────────────────────────────────────
def _service_listing_dict(s) -> dict:
    return {
        "id": str(s.id),
        "vendor_id": str(s.vendor_id),
        "title": s.title,
        "slug": s.slug,
        "category": s.category,
        "description": s.description,
        "pricing_type": s.pricing_type,
        "price": float(s.price),
        "price_max": float(s.price_max) if s.price_max is not None else None,
        "currency": s.currency,
        "inclusions": s.inclusions or [],
        "image_urls": s.image_urls or [],
        "duration_hours": s.duration_hours,
        "is_active": s.is_active,
        "created_at": s.created_at.isoformat(),
    }


def _quote_request_dict(r) -> dict:
    return {
        "id": str(r.id),
        "requester_id": str(r.requester_id),
        "event_name": r.event_name,
        "event_type": r.event_type,
        "event_date": r.event_date.isoformat() if r.event_date else None,
        "event_location": r.event_location,
        "expected_attendance": r.expected_attendance,
        "service_category": r.service_category,
        "budget_min": float(r.budget_min) if r.budget_min is not None else None,
        "budget_max": float(r.budget_max) if r.budget_max is not None else None,
        "currency": r.currency,
        "requirements": r.requirements,
        "preferred_deadline": r.preferred_deadline.isoformat() if r.preferred_deadline else None,
        "attachments": r.attachments or [],
        "status": r.status,
        "created_at": r.created_at.isoformat(),
        "quotations": [_quotation_dict(q) for q in r.quotations] if "quotations" in r.__dict__ else [],
    }


def _quotation_dict(q) -> dict:
    return {
        "id": str(q.id),
        "vendor_id": str(q.vendor_id),
        "vendor_name": q.vendor.business_name if "vendor" in q.__dict__ and q.vendor else None,
        "vendor_slug": q.vendor.slug if "vendor" in q.__dict__ and q.vendor else None,
        "requester_id": str(q.requester_id),
        "quote_request_id": str(q.quote_request_id) if q.quote_request_id else None,
        "title": q.title,
        "scope_of_work": q.scope_of_work,
        "items": q.items or [],
        "total_amount": float(q.total_amount),
        "currency": q.currency,
        "deposit_required": float(q.deposit_required),
        "valid_until": q.valid_until.isoformat() if q.valid_until else None,
        "notes": q.notes,
        "attachment_url": q.attachment_url,
        "attachment_name": q.attachment_name,
        "status": q.status,
        "created_at": q.created_at.isoformat(),
    }


def _booking_dict(b) -> dict:
    return {
        "id": str(b.id),
        "booking_reference": b.booking_reference,
        "vendor_id": str(b.vendor_id),
        "vendor_name": b.vendor.business_name if "vendor" in b.__dict__ and b.vendor else None,
        "requester_id": str(b.requester_id),
        "requester_name": b.requester.full_name if "requester" in b.__dict__ and b.requester else None,
        "service_listing_id": str(b.service_listing_id) if b.service_listing_id else None,
        "quotation_id": str(b.quotation_id) if b.quotation_id else None,
        "event_name": b.event_name,
        "event_date": b.event_date.isoformat() if b.event_date else None,
        "event_location": b.event_location,
        "service_summary": b.service_summary,
        "total_amount": float(b.total_amount),
        "platform_commission_rate": float(b.platform_commission_rate),
        "commission_amount": float(b.commission_amount),
        "vendor_earnings": float(b.vendor_earnings),
        "currency": b.currency,
        "cancellation_policy": b.cancellation_policy,
        "cancellation_terms": b.cancellation_terms,
        "status": b.status,
        "escrow_status": getattr(b, "escrow_status", "pending"),
        "fulfillment_submitted_at": b.fulfillment_submitted_at.isoformat() if getattr(b, "fulfillment_submitted_at", None) else None,
        "fulfillment_proof_notes": getattr(b, "fulfillment_proof_notes", None),
        "fulfillment_proof_urls": getattr(b, "fulfillment_proof_urls", None) or [],
        "escrow_released_at": b.escrow_released_at.isoformat() if getattr(b, "escrow_released_at", None) else None,
        "auto_release_deadline": b.auto_release_deadline.isoformat() if getattr(b, "auto_release_deadline", None) else None,
        "payment_reference": b.payment_reference,
        "paid_at": b.paid_at.isoformat() if b.paid_at else None,
        "completed_at": b.completed_at.isoformat() if b.completed_at else None,
        "cancelled_at": b.cancelled_at.isoformat() if b.cancelled_at else None,
        "cancellation_reason": b.cancellation_reason,
        "refund_amount": float(b.refund_amount),
        "created_at": b.created_at.isoformat(),
        "has_review": b.review is not None if "review" in b.__dict__ else False,
    }


def _review_dict(rev) -> dict:
    return {
        "id": str(rev.id),
        "vendor_id": str(rev.vendor_id),
        "booking_id": str(rev.booking_id) if rev.booking_id else None,
        "reviewer_id": str(rev.reviewer_id),
        "reviewer_name": rev.reviewer.full_name if "reviewer" in rev.__dict__ and rev.reviewer else "Verified Client",
        "rating": rev.rating,
        "title": rev.title,
        "content": rev.content,
        "response_from_vendor": rev.response_from_vendor,
        "status": rev.status,
        "created_at": rev.created_at.isoformat(),
    }


# ── Services Endpoints ────────────────────────────────────────────────────────
@router_vendor.post("/me/services", status_code=201)
async def create_my_service(
    data: ServiceListingCreateRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found. Please register as a vendor first.")
    listing = await vsvc.create_service_listing(
        db,
        vendor_id=vendor.id,
        title=data.title,
        category=data.category,
        description=data.description,
        price=data.price,
        price_max=data.price_max,
        pricing_type=data.pricing_type,
        currency=data.currency,
        inclusions=data.inclusions,
        image_urls=data.image_urls,
        duration_hours=data.duration_hours,
    )
    return {"success": True, "data": _service_listing_dict(listing)}


@router_vendor.get("/{vendor_slug_or_id}/services")
async def list_vendor_services_endpoint(vendor_slug_or_id: str, db: DBSession):
    vendor = None
    try:
        vid = uuid.UUID(vendor_slug_or_id)
        vendor = await vsvc.get_vendor_by_id(db, vid)
    except ValueError:
        vendor = await vsvc.get_vendor_by_slug(db, vendor_slug_or_id)

    if not vendor:
        raise HTTPException(404, "Vendor not found.")

    services = await vsvc.list_vendor_services(db, vendor.id, active_only=True)
    return {"success": True, "data": [_service_listing_dict(s) for s in services]}


@router_vendor.get("/services/{listing_id}")
async def get_service_listing_endpoint(listing_id: uuid.UUID, db: DBSession):
    listing = await vsvc.get_service_listing(db, listing_id)
    if not listing:
        raise HTTPException(404, "Service listing not found.")
    return {"success": True, "data": _service_listing_dict(listing)}


@router_vendor.patch("/me/services/{listing_id}")
async def update_my_service(
    listing_id: uuid.UUID,
    data: ServiceListingUpdateRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found.")
    listing = await vsvc.get_service_listing(db, listing_id)
    if not listing or listing.vendor_id != vendor.id:
        raise HTTPException(404, "Service listing not found.")

    updates = data.model_dump(exclude_none=True)
    listing = await vsvc.update_service_listing(db, listing, **updates)
    return {"success": True, "data": _service_listing_dict(listing)}


@router_vendor.delete("/me/services/{listing_id}")
async def delete_my_service(
    listing_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
):
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found.")
    listing = await vsvc.get_service_listing(db, listing_id)
    if not listing or listing.vendor_id != vendor.id:
        raise HTTPException(404, "Service listing not found.")

    await vsvc.delete_service_listing(db, listing)
    return {"success": True, "message": "Service listing deleted successfully."}


# ── Request-a-Quote (RFQ) Endpoints ───────────────────────────────────────────
@router_vendor.post("/quotes/requests", status_code=201)
async def submit_quote_request_endpoint(
    data: QuoteRequestCreate,
    db: DBSession,
    current_user: CurrentUser,
):
    from datetime import datetime

    vendor_uuids = []
    if data.vendor_ids:
        for vid in data.vendor_ids:
            try:
                vendor_uuids.append(uuid.UUID(vid))
            except ValueError:
                pass

    ev_date = None
    if data.event_date:
        try:
            ev_date = datetime.fromisoformat(data.event_date.replace("Z", "+00:00"))
        except Exception:
            pass

    pref_deadline = None
    if data.preferred_deadline:
        try:
            pref_deadline = datetime.fromisoformat(data.preferred_deadline.replace("Z", "+00:00"))
        except Exception:
            pass

    req = await vsvc.create_quote_request(
        db,
        requester_id=current_user.id,
        event_name=data.event_name,
        service_category=data.service_category,
        requirements=data.requirements,
        event_type=data.event_type,
        event_date=ev_date,
        event_location=data.event_location,
        expected_attendance=data.expected_attendance,
        budget_min=data.budget_min,
        budget_max=data.budget_max,
        currency=data.currency,
        preferred_deadline=pref_deadline,
        attachments=data.attachments,
        vendor_ids=vendor_uuids,
    )
    try:
        from app.tasks.email import send_vendor_quote_request_notification
        send_vendor_quote_request_notification.delay(str(req.id))
    except Exception:
        pass
    return {
        "success": True,
        "data": _quote_request_dict(req),
        "message": "Quote request submitted successfully! Matching vendors have been notified.",
    }


@router_vendor.get("/quotes/requests/{request_id}")
async def get_quote_request_endpoint(
    request_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
):
    req = await vsvc.get_quote_request(db, request_id)
    if not req:
        raise HTTPException(404, "Quote request not found.")
    # Permitted only to requester, admin, or assigned vendors
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    is_recipient = vendor and any(rcp.vendor_id == vendor.id for rcp in req.recipients)
    if req.requester_id != current_user.id and current_user.role != "admin" and not is_recipient:
        raise HTTPException(403, "Not authorized to view this quote request.")
    return {"success": True, "data": _quote_request_dict(req)}


@router_vendor.get("/me/inquiries")
async def list_vendor_inquiries_endpoint(
    db: DBSession,
    current_user: CurrentUser,
    status: str | None = None,
):
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found.")
    inquiries = await vsvc.list_vendor_inquiries(db, vendor.id, status=status)

    out = []
    for inq in inquiries:
        r = inq.request
        out.append({
            "recipient_id": str(inq.id),
            "status": inq.status,
            "declined_reason": inq.declined_reason,
            "created_at": inq.created_at.isoformat(),
            "request": _quote_request_dict(r),
        })
    return {"success": True, "data": out}


@router_vendor.get("/quotes/my-requests")
async def list_my_quote_requests(
    db: DBSession,
    current_user: CurrentUser,
    status: str | None = None,
):
    requests = await vsvc.list_requester_quote_requests(db, current_user.id, status=status)
    return {"success": True, "data": [_quote_request_dict(r) for r in requests]}


@router_vendor.post("/quotes/inquiries/{recipient_id}/respond", status_code=201)
async def submit_quotation_endpoint(
    recipient_id: uuid.UUID,
    data: QuotationSubmitRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    from datetime import datetime

    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found.")

    from app.models.vendor import VendorQuoteRecipient
    recipient = await db.get(VendorQuoteRecipient, recipient_id)
    if not recipient or recipient.vendor_id != vendor.id:
        raise HTTPException(404, "Inquiry not found.")

    req = await vsvc.get_quote_request(db, recipient.request_id)
    if not req:
        raise HTTPException(404, "Quote request not found.")

    valid_dt = None
    if data.valid_until:
        try:
            valid_dt = datetime.fromisoformat(data.valid_until.replace("Z", "+00:00"))
        except Exception:
            pass

    quotation = await vsvc.submit_quotation(
        db,
        vendor_id=vendor.id,
        requester_id=req.requester_id,
        quote_request_id=req.id,
        recipient_id=recipient.id,
        title=data.title,
        scope_of_work=data.scope_of_work,
        items=data.items,
        total_amount=data.total_amount,
        currency=data.currency,
        deposit_required=data.deposit_required,
        valid_until=valid_dt,
        notes=data.notes,
        attachment_url=data.attachment_url,
        attachment_name=data.attachment_name,
    )
    try:
        from app.tasks.email import send_vendor_quotation_submitted_notification
        send_vendor_quotation_submitted_notification.delay(str(quotation.id))
    except Exception:
        pass
    return {
        "success": True,
        "data": _quotation_dict(quotation),
        "message": "Quotation submitted to the client.",
    }


@router_vendor.post("/quotations/{quotation_id}/accept")
async def accept_quotation_endpoint(
    quotation_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
):
    quote = await vsvc.get_quotation(db, quotation_id)
    if not quote or quote.requester_id != current_user.id:
        raise HTTPException(404, "Quotation not found.")

    quote = await vsvc.accept_quotation(db, quote)

    # Automatically initialize a booking for this accepted quotation
    booking = await vsvc.create_booking_from_quotation(db, quote)
    return {
        "success": True,
        "data": {
            "quotation": _quotation_dict(quote),
            "booking": _booking_dict(booking),
        },
        "message": "Quotation accepted! Proceed to confirm contract terms and payment.",
    }


@router_vendor.post("/quotes/inquiries/{recipient_id}/decline")
async def decline_inquiry_endpoint(
    recipient_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
    reason: str | None = None,
):
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found.")
    from app.models.vendor import VendorQuoteRecipient
    recipient = await db.get(VendorQuoteRecipient, recipient_id)
    if not recipient or recipient.vendor_id != vendor.id:
        raise HTTPException(404, "Inquiry not found.")

    recipient = await vsvc.decline_quote_request(db, recipient, reason=reason)
    return {"success": True, "message": "Inquiry declined."}


@router_vendor.post("/quotes/inquiries/{recipient_id}/unlock")
async def unlock_lead_details(
    recipient_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
):
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found.")
    from app.models.vendor import VendorQuoteRecipient
    recipient = await db.get(VendorQuoteRecipient, recipient_id)
    if not recipient or recipient.vendor_id != vendor.id:
        raise HTTPException(404, "Inquiry not found.")

    if vendor.subscription_tier == "free" and vendor.lead_credits_balance <= 0:
        raise HTTPException(402, "You have 0 lead credits remaining. Please purchase credits to unlock direct contact info.")

    if vendor.lead_credits_balance > 0:
        await vsvc.deduct_lead_credit(db, vendor)

    req = await vsvc.get_quote_request(db, recipient.request_id)
    return {
        "success": True,
        "data": {
            "client_name": req.requester.full_name,
            "client_email": req.requester.email,
            "client_whatsapp": req.requester.whatsapp_number,
        },
        "credits_remaining": vendor.lead_credits_balance,
    }


# ── Booking & Contract Endpoints ──────────────────────────────────────────────
@router_vendor.post("/bookings", status_code=201)
async def create_booking_endpoint(
    data: BookingCreateRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    from datetime import datetime

    if data.quotation_id:
        qid = uuid.UUID(data.quotation_id)
        quote = await vsvc.get_quotation(db, qid)
        if not quote or quote.requester_id != current_user.id:
            raise HTTPException(404, "Quotation not found.")
        booking = await vsvc.create_booking_from_quotation(
            db,
            quote,
            cancellation_policy=data.cancellation_policy,
            cancellation_terms=data.cancellation_terms,
        )
    elif data.service_listing_id and data.vendor_id:
        sid = uuid.UUID(data.service_listing_id)
        vid = uuid.UUID(data.vendor_id)
        ev_date = None
        if data.event_date:
            try:
                ev_date = datetime.fromisoformat(data.event_date.replace("Z", "+00:00"))
            except Exception:
                pass
        booking = await vsvc.create_direct_booking(
            db,
            vendor_id=vid,
            requester_id=current_user.id,
            service_listing_id=sid,
            event_name=data.event_name,
            event_date=ev_date,
            event_location=data.event_location,
            cancellation_policy=data.cancellation_policy,
        )
    else:
        raise HTTPException(400, "Provide either quotation_id or service_listing_id and vendor_id.")

    return {"success": True, "data": _booking_dict(booking)}


@router_vendor.get("/bookings/{booking_id_or_ref}")
async def get_booking_endpoint(
    booking_id_or_ref: str,
    db: DBSession,
    current_user: CurrentUser,
):
    booking = None
    try:
        bid = uuid.UUID(booking_id_or_ref)
        booking = await vsvc.get_booking_by_id(db, bid)
    except ValueError:
        booking = await vsvc.get_booking_by_ref(db, booking_id_or_ref)

    if not booking:
        raise HTTPException(404, "Booking not found.")

    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    is_vendor = vendor and booking.vendor_id == vendor.id
    if booking.requester_id != current_user.id and current_user.role != "admin" and not is_vendor:
        raise HTTPException(403, "Not authorized to view this booking.")

    return {"success": True, "data": _booking_dict(booking)}


@router_vendor.get("/me/bookings")
async def list_my_vendor_bookings_endpoint(
    db: DBSession,
    current_user: CurrentUser,
    status: str | None = None,
):
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found.")
    bookings = await vsvc.list_vendor_bookings(db, vendor.id, status=status)
    return {"success": True, "data": [_booking_dict(b) for b in bookings]}


@router_vendor.get("/my-bookings")
async def list_my_client_bookings_endpoint(
    db: DBSession,
    current_user: CurrentUser,
    status: str | None = None,
):
    bookings = await vsvc.list_requester_bookings(db, current_user.id, status=status)
    return {"success": True, "data": [_booking_dict(b) for b in bookings]}


@router_vendor.post("/bookings/{booking_id}/initialize-payment")
async def initialize_booking_payment(
    booking_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
    request: Request,
):
    booking = await vsvc.get_booking_by_id(db, booking_id)
    if not booking or booking.requester_id != current_user.id:
        raise HTTPException(404, "Booking not found.")
    if booking.status != "pending_payment":
        raise HTTPException(400, f"Booking is already in '{booking.status}' status.")

    ref = f"vbook_{booking.id.hex[:12]}_{uuid.uuid4().hex[:6]}"
    booking.payment_reference = ref
    await db.commit()

    base_url = str(request.base_url).rstrip("/")
    checkout_url = f"{base_url}/vendors/bookings/{booking.id}/pay?reference={ref}"

    from app.config import settings
    from app.services.payment_service import resolve_payment_provider

    provider = resolve_payment_provider(booking.currency)

    if provider == "stripe" and settings.STRIPE_SECRET_KEY:
        import stripe  # type: ignore
        try:
            stripe.api_key = settings.STRIPE_SECRET_KEY
            unit_amount = int(round(float(booking.total_amount) * 100))
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency": booking.currency.lower(),
                        "product_data": {
                            "name": f"Booking: {booking.event_name or 'Event Service'}",
                            "description": booking.service_summary or "Vendor booking on Heelo",
                        },
                        "unit_amount": unit_amount,
                    },
                    "quantity": 1,
                }],
                mode="payment",
                customer_email=current_user.email,
                client_reference_id=ref,
                metadata={
                    "booking_id": str(booking.id),
                    "kind": "vendor_booking",
                    "vendor_id": str(booking.vendor_id),
                },
                success_url=f"{base_url}/vendors/bookings/{booking.id}/pay?reference={ref}&verify=1",
                cancel_url=f"{base_url}/vendors/bookings/{booking.id}/pay?reference={ref}&cancelled=1",
            )
            if session and session.url:
                checkout_url = session.url
        except Exception as exc:
            logger.warning("vendor_booking.stripe_init_failed", error=str(exc))
    elif settings.PAYSTACK_SECRET_KEY:
        import httpx
        try:
            amount_kobo = int(round(float(booking.total_amount) * 100))
            async with httpx.AsyncClient(timeout=15.0) as http_client:
                res = await http_client.post(
                    "https://api.paystack.co/transaction/initialize",
                    headers={"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"},
                    json={
                        "email": current_user.email,
                        "amount": amount_kobo,
                        "currency": booking.currency,
                        "reference": ref,
                        "callback_url": f"{base_url}/vendors/bookings/{booking.id}/pay?reference={ref}&verify=1",
                        "metadata": {
                            "booking_id": str(booking.id),
                            "kind": "vendor_booking",
                            "vendor_id": str(booking.vendor_id),
                        },
                    },
                )
                if res.status_code == 200:
                    payload = res.json()
                    if payload.get("status") and payload.get("data", {}).get("authorization_url"):
                        checkout_url = payload["data"]["authorization_url"]
        except Exception as exc:
            logger.warning("vendor_booking.paystack_init_failed", error=str(exc))

    return {
        "success": True,
        "data": {
            "booking_id": str(booking.id),
            "reference": ref,
            "checkout_url": checkout_url,
            "amount": float(booking.total_amount),
            "currency": booking.currency,
        },
    }


@router_vendor.post("/bookings/{booking_id}/confirm-payment")
async def confirm_booking_payment_endpoint(
    booking_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
    payment_reference: str | None = None,
):
    booking = await vsvc.get_booking_by_id(db, booking_id)
    if not booking or booking.requester_id != current_user.id:
        raise HTTPException(404, "Booking not found.")

    ref = payment_reference or booking.payment_reference or f"vbook_{booking.id.hex[:12]}"
    booking = await vsvc.confirm_booking_payment(db, booking, payment_reference=ref)
    return {
        "success": True,
        "data": _booking_dict(booking),
        "message": "Payment confirmed! Your vendor booking is secured.",
    }


@router_vendor.post("/bookings/{booking_id}/deliver")
async def deliver_booking_endpoint(
    booking_id: uuid.UUID,
    data: VendorDeliverySubmitRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    booking = await vsvc.get_booking_by_id(db, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found.")

    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    is_vendor = vendor and booking.vendor_id == vendor.id
    if not is_vendor and current_user.role != "admin":
        raise HTTPException(403, "Only the assigned vendor can mark this booking as delivered.")

    booking = await vsvc.mark_booking_delivered(
        db,
        booking,
        proof_notes=data.proof_notes,
        proof_urls=data.proof_urls,
    )
    return {
        "success": True,
        "data": _booking_dict(booking),
        "message": "Service marked as delivered. The client has 48 hours to confirm and release escrow.",
    }


@router_vendor.post("/bookings/{booking_id}/release-escrow")
async def release_booking_escrow_endpoint(
    booking_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
):
    booking = await vsvc.get_booking_by_id(db, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found.")

    if booking.requester_id != current_user.id and current_user.role != "admin":
        raise HTTPException(403, "Only the client who booked this service (or admin) can release escrow.")

    booking = await vsvc.release_booking_escrow(db, booking, reason="client_confirmation")
    return {
        "success": True,
        "data": _booking_dict(booking),
        "message": "Payment released from escrow to vendor payable balance.",
    }


@router_vendor.post("/bookings/{booking_id}/dispute")
async def dispute_booking_endpoint(
    booking_id: uuid.UUID,
    data: VendorBookingDisputeRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    booking = await vsvc.get_booking_by_id(db, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found.")

    if booking.requester_id != current_user.id and current_user.role != "admin":
        raise HTTPException(403, "Only the client who booked this service can raise a dispute.")

    booking = await vsvc.dispute_booking(db, booking, reason=data.reason)
    return {
        "success": True,
        "data": _booking_dict(booking),
        "message": "Dispute lodged. Escrow funds have been frozen pending support review.",
    }


@router_vendor.post("/bookings/{booking_id}/complete")
async def complete_booking_endpoint(
    booking_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
):
    booking = await vsvc.get_booking_by_id(db, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found.")

    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    is_vendor = vendor and booking.vendor_id == vendor.id
    if booking.requester_id != current_user.id and current_user.role != "admin" and not is_vendor:
        raise HTTPException(403, "Not authorized to complete this booking.")

    booking = await vsvc.complete_booking(db, booking)
    return {"success": True, "data": _booking_dict(booking), "message": "Booking marked as completed."}


@router_vendor.post("/bookings/{booking_id}/cancel")
async def cancel_booking_endpoint(
    booking_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
    reason: str = "Client requested cancellation",
):
    booking = await vsvc.get_booking_by_id(db, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found.")

    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    is_vendor = vendor and booking.vendor_id == vendor.id
    if booking.requester_id != current_user.id and current_user.role != "admin" and not is_vendor:
        raise HTTPException(403, "Not authorized to cancel this booking.")

    booking = await vsvc.cancel_booking(db, booking, reason=reason)
    return {"success": True, "data": _booking_dict(booking), "message": "Booking cancelled."}


# ── Reviews Endpoints (Phase 12) ──────────────────────────────────────────────
@router_vendor.post("/bookings/{booking_id}/reviews", status_code=201)
async def submit_booking_review(
    booking_id: uuid.UUID,
    data: VendorReviewCreateRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    rev = await vsvc.create_vendor_review(
        db,
        booking_id=booking_id,
        reviewer_id=current_user.id,
        rating=data.rating,
        content=data.content,
        title=data.title,
    )
    return {"success": True, "data": _review_dict(rev), "message": "Thank you! Your verified review has been published."}


@router_vendor.get("/{vendor_slug}/reviews")
async def list_vendor_reviews_endpoint(vendor_slug: str, db: DBSession):
    vendor = await vsvc.get_vendor_by_slug(db, vendor_slug)
    if not vendor:
        raise HTTPException(404, "Vendor not found.")
    reviews = await vsvc.list_vendor_reviews(db, vendor.id)
    return {"success": True, "data": [_review_dict(r) for r in reviews]}


@router_vendor.post("/reviews/{review_id}/respond")
async def respond_to_review_endpoint(
    review_id: uuid.UUID,
    data: ReviewResponseRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found.")
    from app.models.vendor import VendorReview
    rev = await db.get(VendorReview, review_id)
    if not rev or rev.vendor_id != vendor.id:
        raise HTTPException(404, "Review not found.")

    rev = await vsvc.respond_to_review(db, rev, response=data.response)
    return {"success": True, "data": _review_dict(rev)}


# ── Monetization & Ledger Endpoints ───────────────────────────────────────────
@router_vendor.get("/me/financial-overview")
async def get_my_financial_overview(
    db: DBSession,
    current_user: CurrentUser,
):
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found.")

    from app.models.vendor import VendorTransaction, VendorPayout
    txs = await db.scalars(
        select(VendorTransaction)
        .where(VendorTransaction.vendor_id == vendor.id)
        .order_by(VendorTransaction.created_at.desc())
        .limit(50)
    )
    payouts = await db.scalars(
        select(VendorPayout)
        .where(VendorPayout.vendor_id == vendor.id)
        .order_by(VendorPayout.created_at.desc())
        .limit(20)
    )

    return {
        "success": True,
        "data": {
            "payable_balance": float(vendor.payable_balance),
            "escrow_balance": float(vendor.escrow_balance or 0.0),
            "disputed_balance": float(vendor.disputed_balance or 0.0),
            "total_earned": float(vendor.total_earned),
            "total_withdrawn": float(vendor.total_withdrawn),
            "currency": vendor.currency,
            "subscription_tier": vendor.subscription_tier,
            "lead_credits": vendor.lead_credits_balance,
            "commission_rate": float(vendor.custom_commission_rate or 10.0),
            "transactions": [
                {
                    "reference": t.reference,
                    "type": t.type,
                    "gross_amount": float(t.gross_amount),
                    "platform_fee": float(t.platform_fee),
                    "net_amount": float(t.net_amount),
                    "status": t.status,
                    "created_at": t.created_at.isoformat(),
                }
                for t in txs
            ],
            "payouts": [
                {
                    "id": str(p.id),
                    "amount": float(p.amount),
                    "currency": p.currency,
                    "method": p.method,
                    "status": p.status,
                    "created_at": p.created_at.isoformat(),
                }
                for p in payouts
            ],
        },
    }


@router_vendor.post("/me/payout", status_code=201)
async def request_payout_endpoint(
    data: VendorPayoutRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found.")

    payout = await vsvc.request_vendor_payout(
        db,
        vendor,
        amount=data.amount,
        method=data.method,
        account_details=data.account_details,
        initiated_by=current_user.id,
    )
    return {
        "success": True,
        "data": {
            "id": str(payout.id),
            "amount": float(payout.amount),
            "currency": payout.currency,
            "status": payout.status,
            "remaining_payable_balance": float(vendor.payable_balance),
        },
        "message": f"Withdrawal request of ₦{payout.amount:,.2f} submitted for disbursement.",
    }


@router_vendor.get("/admin/payouts")
async def list_vendor_payouts_admin(
    db: DBSession,
    current_user: CurrentUser,
    status: str | None = None,
):
    if current_user.role != "admin":
        raise HTTPException(403, "Admin access required.")
    from app.models.vendor import VendorPayout
    from sqlalchemy.orm import selectinload

    stmt = select(VendorPayout).options(selectinload(VendorPayout.vendor)).order_by(VendorPayout.created_at.desc())
    if status:
        stmt = stmt.where(VendorPayout.status == status)
    payouts = await db.scalars(stmt)
    return {
        "success": True,
        "data": [
            {
                "id": str(p.id),
                "vendor_id": str(p.vendor_id),
                "business_name": p.vendor.business_name if p.vendor else "Unknown",
                "amount": float(p.amount),
                "currency": p.currency,
                "status": p.status,
                "method": p.method,
                "account_details": p.account_details or {},
                "created_at": p.created_at.isoformat(),
            }
            for p in payouts
        ],
    }


class VendorPayoutDisburseRequest(BaseModel):
    provider_reference: str | None = None


@router_vendor.post("/admin/payouts/{payout_id}/disburse")
async def disburse_vendor_payout_admin(
    payout_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
    body: VendorPayoutDisburseRequest | None = None,
    provider_reference: str | None = None,
):
    if current_user.role != "admin":
        raise HTTPException(403, "Admin access required.")
    from app.models.vendor import VendorPayout

    ref = (body.provider_reference if body and body.provider_reference else None) or provider_reference
    payout = await db.get(VendorPayout, payout_id)
    if not payout:
        raise HTTPException(404, "Payout not found.")
    payout = await vsvc.disburse_vendor_payout(db, payout, provider_reference=ref)
    return {
        "success": True,
        "data": {
            "id": str(payout.id),
            "status": payout.status,
            "provider_reference": payout.provider_reference,
        },
        "message": "Payout successfully disbursed and marked completed.",
    }


@router_vendor.post("/me/subscriptions/checkout")
async def vendor_subscription_checkout(
    data: VendorSubscriptionCheckoutRequest,
    db: DBSession,
    current_user: CurrentUser,
    request: Request,
):
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found.")

    plan = vsvc.VENDOR_SUBSCRIPTION_PLANS.get(data.tier)
    if not plan:
        raise HTTPException(400, "Invalid plan.")

    ref = f"vsub_{vendor.id.hex[:10]}_{uuid.uuid4().hex[:6]}"
    sub = await vsvc.activate_vendor_subscription(db, vendor, tier=data.tier, payment_reference=ref)

    return {
        "success": True,
        "data": {
            "tier": sub.tier,
            "status": sub.status,
            "reference": ref,
            "price": float(sub.price),
        },
        "message": f"Vendor plan upgraded to {plan['name']}!",
    }


@router_vendor.post("/me/campaigns/checkout")
async def vendor_campaign_checkout(
    data: VendorCampaignCheckoutRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found.")

    ref = f"vfeat_{vendor.id.hex[:10]}_{uuid.uuid4().hex[:6]}"
    camp = await vsvc.create_featured_campaign(
        db,
        vendor,
        placement=data.placement,
        duration_days=data.duration_days,
        category=data.category,
        payment_reference=ref,
    )
    return {
        "success": True,
        "data": {
            "placement": camp.placement,
            "price_paid": float(camp.price_paid),
            "status": camp.status,
            "end_date": camp.end_date.isoformat(),
        },
        "message": "Featured placement activated! Your profile now receives priority display.",
    }


@router_vendor.post("/me/lead-credits/checkout")
async def vendor_lead_credits_checkout(
    data: VendorLeadCreditCheckoutRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found.")

    ref = f"vlead_{vendor.id.hex[:10]}_{uuid.uuid4().hex[:6]}"
    purchase = await vsvc.purchase_lead_credits(
        db,
        vendor,
        credits_count=data.credits_count,
        payment_reference=ref,
    )
    return {
        "success": True,
        "data": {
            "credits_purchased": purchase.credits_purchased,
            "new_balance": vendor.lead_credits_balance,
            "price_paid": float(purchase.price_paid),
        },
        "message": f"Purchased {purchase.credits_purchased} lead credits successfully.",
    }


# ── Vendor Verification (Phase 11) ─────────────────────────────────────────────
@router_vendor.post("/me/verification", status_code=201)
async def submit_vendor_verification_endpoint(
    data: VendorVerificationSubmit,
    db: DBSession,
    current_user: CurrentUser,
):
    vendor = await vsvc.get_vendor_by_user(db, current_user.id)
    if not vendor:
        raise HTTPException(404, "No vendor profile found.")

    req = await vsvc.submit_verification_request(
        db,
        vendor,
        business_registration_number=data.business_registration_number,
        tax_id=data.tax_id,
        document_urls=data.document_urls,
        government_id_url=data.government_id_url,
        notes=data.notes,
    )
    return {
        "success": True,
        "data": {
            "id": str(req.id),
            "status": req.status,
            "created_at": req.created_at.isoformat(),
        },
        "message": "Verification documents received. Admin review is pending.",
    }


@router_vendor.get("/verification/requests")
async def list_verification_requests_admin(
    db: DBSession,
    current_user: CurrentUser,
    status: str = "pending",
):
    if current_user.role != "admin":
        raise HTTPException(403, "Admin access required.")

    from app.models.vendor import VendorVerificationRequest
    from sqlalchemy.orm import selectinload

    reqs = await db.scalars(
        select(VendorVerificationRequest)
        .where(VendorVerificationRequest.status == status)
        .options(selectinload(VendorVerificationRequest.vendor))
        .order_by(VendorVerificationRequest.created_at.desc())
    )
    return {
        "success": True,
        "data": [
            {
                "id": str(r.id),
                "vendor_id": str(r.vendor_id),
                "business_name": r.vendor.business_name if r.vendor else "Unknown",
                "business_registration_number": r.business_registration_number,
                "tax_id": r.tax_id,
                "document_urls": r.document_urls or [],
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in reqs
        ],
    }


class VerificationReviewRequest(BaseModel):
    approved: bool | None = None
    admin_notes: str | None = None


@router_vendor.post("/verification/requests/{request_id}/review")
async def review_verification_request_admin(
    request_id: uuid.UUID,
    db: DBSession,
    current_user: CurrentUser,
    body: VerificationReviewRequest | None = None,
    approved: bool | None = None,
    admin_notes: str | None = None,
):
    if current_user.role != "admin":
        raise HTTPException(403, "Admin access required.")

    is_approved = body.approved if (body and body.approved is not None) else approved
    notes = (body.admin_notes if body and body.admin_notes is not None else None) or admin_notes
    if is_approved is None:
        raise HTTPException(422, "Field 'approved' (boolean) is required.")

    req = await vsvc.review_verification_request(
        db, request_id, approved=is_approved, reviewer_id=current_user.id, admin_notes=notes
    )
    return {
        "success": True,
        "data": {"id": str(req.id), "status": req.status},
        "message": f"Verification request marked as {req.status}.",
    }


# ── Booth Packages & Applications ─────────────────────────────────────────────

router_booth = APIRouter(tags=["booths"])


class BoothPackageCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    price: float = Field(..., ge=0)
    currency: str = Field("NGN", min_length=3, max_length=3)
    dimensions: str | None = Field(None, max_length=100)
    total_booths: int = Field(10, ge=1, le=1000)
    description: str | None = Field(None, max_length=2000)
    amenities: list[str] | None = None


class BoothApplicationCreateRequest(BaseModel):
    business_name: str = Field(..., min_length=2, max_length=255)
    contact_name: str = Field(..., min_length=2, max_length=255)
    contact_email: str = Field(..., max_length=255)
    contact_phone: str = Field(..., min_length=5, max_length=50)
    category: str = Field(..., max_length=100)
    package_id: str | None = None
    description: str | None = Field(None, max_length=3000)
    booth_requirements: str | None = Field(None, max_length=2000)


class BoothApproveRequest(BaseModel):
    assigned_booth_number: str | None = Field(None, max_length=50)


class BoothRejectRequest(BaseModel):
    reason: str | None = Field(None, max_length=1000)


def _booth_package_dict(pkg) -> dict:
    return {
        "id": str(pkg.id),
        "event_id": str(pkg.event_id),
        "name": pkg.name,
        "description": pkg.description,
        "price": float(pkg.price),
        "currency": pkg.currency,
        "dimensions": pkg.dimensions,
        "total_booths": pkg.total_booths,
        "booths_remaining": pkg.booths_remaining,
        "amenities": pkg.amenities or [],
        "is_active": pkg.is_active,
        "created_at": pkg.created_at.isoformat(),
    }


def _booth_application_dict(app) -> dict:
    package_name = None
    if "package" in app.__dict__ and app.package is not None:
        package_name = app.package.name
    event_title = None
    event_slug = None
    if "event" in app.__dict__ and app.event is not None:
        event_title = app.event.title
        event_slug = app.event.slug

    return {
        "id": str(app.id),
        "event_id": str(app.event_id),
        "event_title": event_title,
        "event_slug": event_slug,
        "vendor_id": str(app.vendor_id) if app.vendor_id else None,
        "package_id": str(app.package_id) if app.package_id else None,
        "package_name": package_name,
        "business_name": app.business_name,
        "contact_name": app.contact_name,
        "contact_email": app.contact_email,
        "contact_phone": app.contact_phone,
        "category": app.category,
        "description": app.description,
        "booth_requirements": app.booth_requirements,
        "status": app.status,
        "price": float(app.price),
        "currency": app.currency,
        "assigned_booth_number": app.assigned_booth_number,
        "payment_reference": app.payment_reference,
        "invoice_url": app.invoice_url,
        "paid_at": app.paid_at.isoformat() if app.paid_at else None,
        "rejection_reason": app.rejection_reason,
        "created_at": app.created_at.isoformat(),
    }


@router_booth.post("/api/v1/organizations/{slug}/events/{event_id}/booth-packages", status_code=201)
async def create_event_booth_package(
    slug: str,
    event_id: uuid.UUID,
    data: BoothPackageCreateRequest,
    db: DBSession,
    org_access: OrgAccess,
):
    from app.models.event import Event

    event = await db.scalar(
        select(Event).where(Event.id == event_id, Event.org_id == org_access[0].id)
    )
    if not event:
        raise HTTPException(404, "Event not found.")

    pkg = await vsvc.create_booth_package(
        db,
        event_id=event_id,
        name=data.name,
        price=data.price,
        currency=data.currency,
        total_booths=data.total_booths,
        description=data.description,
        dimensions=data.dimensions,
        amenities=data.amenities,
    )
    return {"success": True, "data": _booth_package_dict(pkg)}


@router_booth.get("/api/v1/events/{event_id}/booth-packages")
async def list_event_booth_packages(event_id: uuid.UUID, db: DBSession):
    packages = await vsvc.list_booth_packages(db, event_id, active_only=True)
    return {"success": True, "data": [_booth_package_dict(p) for p in packages]}


@router_booth.post("/api/v1/events/{event_id}/booth-applications", status_code=201)
async def submit_booth_application(
    event_id: uuid.UUID,
    data: BoothApplicationCreateRequest,
    db: DBSession,
    request: Request,
):
    from app.models.event import Event

    event = await db.scalar(select(Event).where(Event.id == event_id))
    if not event or event.deleted_at is not None:
        raise HTTPException(404, "Event not found.")

    pkg_id = None
    if data.package_id:
        try:
            pkg_id = uuid.UUID(data.package_id)
        except ValueError:
            pass

    app = await vsvc.create_booth_application(
        db,
        event_id=event_id,
        business_name=data.business_name,
        contact_name=data.contact_name,
        contact_email=data.contact_email,
        contact_phone=data.contact_phone,
        category=data.category,
        package_id=pkg_id,
        description=data.description,
        booth_requirements=data.booth_requirements,
    )

    try:
        from app.tasks.email import send_booth_application_submitted

        send_booth_application_submitted.delay(str(app.id))
    except Exception as exc:
        logger.warning("booth.application_email_failed", app_id=str(app.id), error=str(exc))

    return {
        "success": True,
        "data": _booth_application_dict(app),
        "message": "Your booth application has been submitted! The organizer will review your details.",
    }


@router_booth.get("/api/v1/organizations/{slug}/booth-applications")
async def list_org_booth_applications(
    slug: str,
    db: DBSession,
    org_access: OrgAccess,
    event_id: uuid.UUID | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
):
    org = org_access[0]
    applications, total = await vsvc.list_booth_applications(
        db,
        org_id=org.id,
        event_id=event_id,
        status=status,
        page=page,
        per_page=per_page,
    )
    return {
        "success": True,
        "data": [_booth_application_dict(a) for a in applications],
        "meta": {"total": total, "page": page, "per_page": per_page},
    }


@router_booth.post("/api/v1/organizations/{slug}/booth-applications/{app_id}/approve")
async def approve_application(
    slug: str,
    app_id: uuid.UUID,
    data: BoothApproveRequest,
    db: DBSession,
    org_access: OrgAccess,
    request: Request,
):
    app = await vsvc.get_booth_application(db, app_id)
    if not app:
        raise HTTPException(404, "Application not found.")

    base_url = str(request.base_url).rstrip("/")
    app = await vsvc.approve_booth_application(
        db, app, assigned_booth_number=data.assigned_booth_number, base_url=base_url
    )

    try:
        from app.tasks.email import send_booth_application_approved

        send_booth_application_approved.delay(str(app.id))
    except Exception as exc:
        logger.warning("booth.approval_email_failed", app_id=str(app.id), error=str(exc))

    return {
        "success": True,
        "data": _booth_application_dict(app),
        "message": "Booth application approved. An automated invoice and payment link have been emailed to the applicant.",
    }


@router_booth.post("/api/v1/organizations/{slug}/booth-applications/{app_id}/reject")
async def reject_application(
    slug: str,
    app_id: uuid.UUID,
    data: BoothRejectRequest,
    db: DBSession,
    org_access: OrgAccess,
):
    app = await vsvc.get_booth_application(db, app_id)
    if not app:
        raise HTTPException(404, "Application not found.")

    app = await vsvc.reject_booth_application(db, app, reason=data.reason)
    return {
        "success": True,
        "data": _booth_application_dict(app),
        "message": "Booth application has been rejected.",
    }


@router_booth.get("/api/v1/booth-applications/{app_id}")
async def get_booth_app_details(app_id: uuid.UUID, db: DBSession):
    app = await vsvc.get_booth_application(db, app_id)
    if not app:
        raise HTTPException(404, "Application not found.")
    return {"success": True, "data": _booth_application_dict(app)}


@router_booth.post("/api/v1/booth-applications/{app_id}/initialize-payment")
async def initialize_booth_app_payment(app_id: uuid.UUID, db: DBSession, request: Request):
    import httpx

    from app.config import settings

    app = await vsvc.get_booth_application(db, app_id)
    if not app:
        raise HTTPException(404, "Application not found.")
    if app.status == "paid":
        return {"success": True, "already_paid": True, "message": "Booth is already confirmed and paid."}

    base_url = str(request.base_url).rstrip("/")
    # If price is 0 (complimentary/sponsored), immediately confirm
    if float(app.price) <= 0:
        await vsvc.confirm_booth_payment(db, app, payment_reference=f"free_{app.id.hex[:10]}")
        try:
            from app.tasks.email import send_booth_application_confirmed

            send_booth_application_confirmed.delay(str(app.id))
        except Exception:
            pass
        return {
            "success": True,
            "checkout_url": f"{base_url}/booths/{app.id}/pay?confirmed=1",
            "reference": app.payment_reference,
        }

    reference = app.payment_reference or f"booth_{app.id.hex[:12]}_{uuid.uuid4().hex[:6]}"
    app.payment_reference = reference
    await db.commit()

    checkout_url = f"{base_url}/booths/{app.id}/pay?reference={reference}"

    if settings.PAYSTACK_SECRET_KEY:
        amount_kobo = max(int(float(app.price) * 100), 100)
        payload = {
            "email": app.contact_email,
            "amount": amount_kobo,
            "reference": reference,
            "callback_url": f"{base_url}/booths/{app.id}/pay?reference={reference}&verify=1",
            "currency": app.currency or "NGN",
            "metadata": {
                "booth_application_id": str(app.id),
                "kind": "booth_payment",
                "business_name": app.business_name,
                "event_id": str(app.event_id),
            },
        }
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    "https://api.paystack.co/transaction/initialize",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") and "authorization_url" in data.get("data", {}):
                        checkout_url = data["data"]["authorization_url"]
        except Exception as exc:
            logger.warning("booth.paystack_init_failed", error=str(exc))

    return {"success": True, "checkout_url": checkout_url, "reference": reference}


class BoothConfirmRequest(BaseModel):
    payment_reference: str | None = None


@router_booth.post("/api/v1/booths/{app_id}/confirm-payment")
@router_booth.post("/api/v1/booth-applications/{app_id}/confirm-payment")
async def confirm_booth_app_payment(
    app_id: uuid.UUID,
    db: DBSession,
    reference: str | None = Query(None),
    data: BoothConfirmRequest | None = None,
):
    app = await vsvc.get_booth_application(db, app_id)
    if not app:
        raise HTTPException(404, "Application not found.")
    if app.status == "paid":
        return {"success": True, "data": _booth_application_dict(app)}

    ref = reference or (data.payment_reference if data else None)
    app = await vsvc.confirm_booth_payment(db, app, payment_reference=ref)

    try:
        from app.tasks.email import send_booth_application_confirmed

        send_booth_application_confirmed.delay(str(app.id))
    except Exception as exc:
        logger.warning("booth.confirmed_email_failed", app_id=str(app.id), error=str(exc))

    return {
        "success": True,
        "data": _booth_application_dict(app),
        "message": "Payment confirmed! Your exhibitor booth is now reserved.",
    }

