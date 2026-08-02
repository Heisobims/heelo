"""
Admin HTML pages — all routes under /admin/, require user.role == 'admin'.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.dependencies import DBSession
from app.services import admin_service as adm_svc

router_admin_pages = APIRouter(prefix="/admin", tags=["admin-pages"])
templates = Jinja2Templates(directory="app/templates")


async def _require_admin_ctx(request: Request, db):
    """Return admin user or redirect to login."""
    from jose import JWTError, jwt

    from app.config import settings
    from app.models.user import User

    token = request.cookies.get("heelo_access")
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        uid = payload.get("sub")
    except JWTError:
        return None
    if not uid:
        return None
    user = await db.scalar(select(User).where(User.id == uuid.UUID(uid)))
    if not user or user.role != "admin":
        return None
    return user


def _ctx(request, admin_user, active_page: str, **kwargs):
    return {"request": request, "admin_user": admin_user, "active_page": active_page, **kwargs}


# ── Overview ──────────────────────────────────────────────────────────────────


@router_admin_pages.get("", response_class=HTMLResponse)
@router_admin_pages.get("/", response_class=HTMLResponse)
async def admin_overview(request: Request, db: DBSession):
    admin_user = await _require_admin_ctx(request, db)
    if not admin_user:
        return RedirectResponse("/login?next=/admin", status_code=302)

    stats = await adm_svc.platform_stats(db)
    recent_orgs, _ = await adm_svc.list_orgs(db, page=1, per_page=5)
    recent_users, _ = await adm_svc.list_users(db, page=1, per_page=5)

    return templates.TemplateResponse(
        "admin/overview.html",
        _ctx(
            request,
            admin_user,
            "overview",
            stats=stats,
            recent_orgs=recent_orgs,
            recent_users=recent_users,
        ),
    )


# ── Organizations ─────────────────────────────────────────────────────────────


@router_admin_pages.get("/organizations", response_class=HTMLResponse)
async def admin_orgs(request: Request, db: DBSession):
    admin_user = await _require_admin_ctx(request, db)
    if not admin_user:
        return RedirectResponse("/login?next=/admin/organizations", status_code=302)

    q = request.query_params.get("q", "").strip() or None
    selected_plan = request.query_params.get("plan", "").strip() or None
    selected_status = request.query_params.get("status", "").strip() or None
    page = max(1, int(request.query_params.get("page", 1)))

    is_active = None
    if selected_status == "active":
        is_active = True
    elif selected_status == "suspended":
        is_active = False

    orgs, total = await adm_svc.list_orgs(
        db, search=q, is_active=is_active, plan=selected_plan, page=page, per_page=30
    )

    return templates.TemplateResponse(
        "admin/organizations.html",
        _ctx(
            request,
            admin_user,
            "organizations",
            orgs=orgs,
            total=total,
            page=page,
            per_page=30,
            q=q or "",
            selected_plan=selected_plan or "",
            selected_status=selected_status or "",
        ),
    )


@router_admin_pages.get("/organizations/{org_id}", response_class=HTMLResponse)
async def admin_org_detail(org_id: str, request: Request, db: DBSession):
    admin_user = await _require_admin_ctx(request, db)
    if not admin_user:
        return RedirectResponse(f"/login?next=/admin/organizations/{org_id}", status_code=302)

    try:
        oid = uuid.UUID(org_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid org ID.") from err

    detail = await adm_svc.get_org_detail(db, oid)
    if not detail:
        raise HTTPException(404, "Organization not found.")

    return templates.TemplateResponse(
        "admin/organization_detail.html",
        _ctx(request, admin_user, "organizations", detail=detail),
    )


# ── Vendors / venues ──────────────────────────────────────────────────────────


@router_admin_pages.get("/vendors", response_class=HTMLResponse)
async def admin_vendors(request: Request, db: DBSession):
    admin_user = await _require_admin_ctx(request, db)
    if not admin_user:
        return RedirectResponse("/login?next=/admin/vendors", status_code=302)

    from app.models.vendor import VENDOR_CATEGORIES

    q = request.query_params.get("q", "").strip() or None
    selected_category = request.query_params.get("category", "").strip() or None
    selected_status = request.query_params.get("status", "").strip() or None
    page = max(1, int(request.query_params.get("page", 1)))

    vendors, total = await adm_svc.list_vendors(
        db, search=q, category=selected_category, status=selected_status, page=page, per_page=30
    )

    return templates.TemplateResponse(
        "admin/vendors.html",
        _ctx(
            request,
            admin_user,
            "vendors",
            vendors=vendors,
            total=total,
            page=page,
            per_page=30,
            q=q or "",
            categories=VENDOR_CATEGORIES,
            selected_category=selected_category or "",
            selected_status=selected_status or "",
        ),
    )


# ── Users ─────────────────────────────────────────────────────────────────────


@router_admin_pages.get("/users", response_class=HTMLResponse)
async def admin_users(request: Request, db: DBSession):
    admin_user = await _require_admin_ctx(request, db)
    if not admin_user:
        return RedirectResponse("/login?next=/admin/users", status_code=302)

    q = request.query_params.get("q", "").strip() or None
    selected_category = request.query_params.get("category", "").strip() or None
    selected_country = request.query_params.get("country", "").strip() or None
    selected_age_bracket = request.query_params.get("age_bracket", "").strip() or None
    selected_interest = request.query_params.get("interest", "").strip() or None
    selected_vibe = request.query_params.get("vibe", "").strip() or None
    page = max(1, int(request.query_params.get("page", 1)))

    users, total = await adm_svc.list_users(
        db,
        search=q,
        category=selected_category,
        country=selected_country,
        age_bracket=selected_age_bracket,
        interest=selected_interest,
        vibe=selected_vibe,
        page=page,
        per_page=30,
    )
    counts = await adm_svc.get_user_category_counts(db)
    vendor_user_ids = await adm_svc.batch_vendor_user_ids(db, [u.id for u in users])
    insights = await adm_svc.audience_insights(db)

    return templates.TemplateResponse(
        "admin/users.html",
        _ctx(
            request,
            admin_user,
            "users",
            users=users,
            total=total,
            page=page,
            per_page=30,
            q=q or "",
            selected_category=selected_category or "all",
            selected_country=selected_country or "",
            selected_age_bracket=selected_age_bracket or "",
            selected_interest=selected_interest or "",
            selected_vibe=selected_vibe or "",
            counts=counts,
            vendor_user_ids=vendor_user_ids,
            country_names=adm_svc.COUNTRY_NAMES,
            age_brackets=[label for label, _, _ in adm_svc.AGE_BRACKETS],
            filter_interests=[row["interest"] for row in insights["top_interests"]],
            filter_vibes=[row["vibe"] for row in insights["top_vibes"]],
        ),
    )


@router_admin_pages.get("/users/{user_id}", response_class=HTMLResponse)
async def admin_user_detail(user_id: str, request: Request, db: DBSession):
    admin_user = await _require_admin_ctx(request, db)
    if not admin_user:
        return RedirectResponse(f"/login?next=/admin/users/{user_id}", status_code=302)

    try:
        uid = uuid.UUID(user_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid user ID.") from err

    detail = await adm_svc.get_user_detail(db, uid)
    if not detail:
        raise HTTPException(404, "User not found.")

    return templates.TemplateResponse(
        "admin/user_detail.html",
        _ctx(request, admin_user, "users", detail=detail),
    )


# ── Audience insights ─────────────────────────────────────────────────────────


@router_admin_pages.get("/insights", response_class=HTMLResponse)
async def admin_insights(request: Request, db: DBSession):
    admin_user = await _require_admin_ctx(request, db)
    if not admin_user:
        return RedirectResponse("/login?next=/admin/insights", status_code=302)

    insights = await adm_svc.audience_insights(db)

    return templates.TemplateResponse(
        "admin/insights.html",
        _ctx(request, admin_user, "insights", insights=insights),
    )


# ── Events ────────────────────────────────────────────────────────────────────


@router_admin_pages.get("/events", response_class=HTMLResponse)
async def admin_events(request: Request, db: DBSession):
    admin_user = await _require_admin_ctx(request, db)
    if not admin_user:
        return RedirectResponse("/login?next=/admin/events", status_code=302)

    from sqlalchemy import func

    from app.models.event import Event

    q_str = request.query_params.get("q", "").strip() or None
    selected_status = request.query_params.get("status", "").strip() or None
    page = max(1, int(request.query_params.get("page", 1)))
    per_page = 30

    q = select(Event).options(selectinload(Event.organization))
    if q_str:
        q = q.where(or_(Event.title.ilike(f"%{q_str}%"), Event.slug.ilike(f"%{q_str}%")))
    if selected_status:
        q = q.where(Event.status == selected_status)

    total = await db.scalar(select(func.count()).select_from(q.subquery()))
    rows = await db.scalars(
        q.order_by(Event.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    events = list(rows.all())

    # Attach org for display (loaded via selectinload)
    for ev in events:
        ev._org = ev.organization if hasattr(ev, "organization") else None

    return templates.TemplateResponse(
        "admin/events.html",
        _ctx(
            request,
            admin_user,
            "events",
            events=events,
            total=total or 0,
            page=page,
            per_page=per_page,
            q=q_str or "",
            selected_status=selected_status or "",
        ),
    )


# ── Broadcasts (platform-wide promotional email) ──────────────────────────────


@router_admin_pages.get("/broadcasts", response_class=HTMLResponse)
async def admin_broadcasts(request: Request, db: DBSession):
    admin_user = await _require_admin_ctx(request, db)
    if not admin_user:
        return RedirectResponse("/login?next=/admin/broadcasts", status_code=302)

    from app.services import admin_broadcast_service as bc_svc

    page = max(1, int(request.query_params.get("page", 1)))
    broadcasts, total = await bc_svc.list_broadcasts(db, page=page, per_page=20)
    counts = await adm_svc.get_user_category_counts(db)

    return templates.TemplateResponse(
        "admin/broadcasts.html",
        _ctx(
            request,
            admin_user,
            "broadcasts",
            broadcasts=broadcasts,
            total=total,
            page=page,
            per_page=20,
            counts=counts,
            gmail_daily_limit=bc_svc.GMAIL_DAILY_SOFT_LIMIT,
        ),
    )
