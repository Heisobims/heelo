"""
Top-level HTML page routes — dashboard redirect, attendee home, accept-invite.
Org-specific pages (overview, team, settings) live in routers/organization_pages.py.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import DBSession
from app.permissions import Permission, require_page_permission
from app.services import organization_service as org_svc
from app.utils.color import contrasting_text_color

router_pages = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")
templates.env.filters["contrast_text"] = contrasting_text_color


# ── Legal ─────────────────────────────────────────────────────────────────────


@router_pages.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    return templates.TemplateResponse(
        "legal/terms.html", {"request": request, "updated_date": "July 31, 2026"}
    )


@router_pages.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    return templates.TemplateResponse(
        "legal/privacy.html", {"request": request, "updated_date": "July 31, 2026"}
    )


@router_pages.get("/pricing", response_class=HTMLResponse)
async def pricing_page(request: Request):
    from app.services import payment_service as pay_svc

    token = request.cookies.get("heelo_access")
    is_logged_in = False
    if token:
        try:
            jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            is_logged_in = True
        except JWTError:
            pass

    return templates.TemplateResponse(
        "marketing/pricing.html",
        {
            "request": request,
            "is_logged_in": is_logged_in,
            "platform_fee_percent": f"{float(pay_svc.PLATFORM_FEE_PERCENT) * 100:g}",
        },
    )


@router_pages.get("/unsubscribe/{token}", response_class=HTMLResponse)
async def unsubscribe_page(token: str, request: Request, db: DBSession):
    import uuid as _uuid

    from app.services import crm_service as crm_svc
    from app.utils.auth import decode_unsubscribe_token

    org_name = None
    error = None
    try:
        payload = decode_unsubscribe_token(token)
        org_id = _uuid.UUID(payload["org_id"])
        email = payload["email"]
    except Exception:
        error = "This unsubscribe link is invalid or has expired."
    else:
        org = await org_svc.get_organization_by_id(db, org_id)
        if not org:
            error = "This unsubscribe link is invalid or has expired."
        else:
            await crm_svc.unsubscribe_contact(db, org_id, email)
            org_name = org.name

    return templates.TemplateResponse(
        "legal/unsubscribed.html",
        {"request": request, "org_name": org_name, "error": error},
    )


@router_pages.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    token = request.cookies.get("heelo_access")
    is_logged_in = False
    if token:
        try:
            jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            is_logged_in = True
        except JWTError:
            pass
    return templates.TemplateResponse(
        "home/landing.html",
        {"request": request, "is_logged_in": is_logged_in},
    )


@router_pages.get("/offline", response_class=HTMLResponse)
async def offline_page(request: Request):
    return templates.TemplateResponse("pwa/offline.html", {"request": request})


@router_pages.get("/feedback/{registration_id}", response_class=HTMLResponse)
async def feedback_page(registration_id: str, request: Request, db: DBSession):
    import uuid as _uuid

    from app.services import ticketing_service as tk_svc

    try:
        reg_id = _uuid.UUID(registration_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid registration ID.") from err

    reg = await tk_svc.get_registration_by_id(db, reg_id)
    if not reg or not reg.event:
        raise HTTPException(404, "Registration not found.")

    return templates.TemplateResponse(
        "events/feedback.html",
        {"request": request, "reg": reg, "event": reg.event},
    )


def _current_user_or_none(request: Request):
    """Return user from cookie without raising — used for soft auth on public pages."""
    return None


async def _get_auth_context(request: Request, db: AsyncSession):
    """Return (user, user_orgs) from cookie, or redirect to login if not authed."""
    token = request.cookies.get("heelo_access")
    if not token:
        return None, []
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            return None, []
    except JWTError:
        return None, []

    import uuid

    from sqlalchemy import select

    from app.models.user import User

    user = await db.scalar(select(User).where(User.id == uuid.UUID(user_id)))
    if not user or user.deleted_at is not None:
        return None, []

    orgs = await org_svc.get_user_organizations(db, user.id)
    return user, orgs


# ── Dashboard redirect ────────────────────────────────────────────────────────


@router_pages.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: DBSession):
    user, orgs = await _get_auth_context(request, db)

    if not user:
        return RedirectResponse("/login?next=/dashboard", status_code=302)

    # Attendees without org: go to their home feed
    if user.role == "attendee" and not orgs:
        return RedirectResponse("/home", status_code=302)

    # Single org owner/member: go straight to that org
    if len(orgs) == 1:
        return RedirectResponse(f"/org/{orgs[0]['org'].slug}", status_code=302)

    # No orgs yet: show org creation wizard
    if not orgs:
        return templates.TemplateResponse(
            "dashboard/org_create.html",
            {"request": request, "user": user},
        )

    # Multiple orgs: show picker
    return templates.TemplateResponse(
        "dashboard/org_picker.html",
        {"request": request, "user": user, "orgs": orgs},
    )


# ── Org overview page ─────────────────────────────────────────────────────────


@router_pages.get("/org/new", response_class=HTMLResponse)
async def org_new(request: Request, db: DBSession):
    user, _ = await _get_auth_context(request, db)
    if not user:
        return RedirectResponse("/login?next=/org/new", status_code=302)
    return templates.TemplateResponse(
        "dashboard/org_create.html",
        {"request": request, "user": user},
    )


@router_pages.get("/org/{slug}", response_class=HTMLResponse)
async def org_overview(slug: str, request: Request, db: DBSession):
    user, orgs = await _get_auth_context(request, db)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}", status_code=302)

    org = await org_svc.get_organization_by_slug(db, slug)
    if not org:
        raise HTTPException(404, "Organization not found.")

    # Determine user's role
    user_role = None
    is_owner = str(org.owner_id) == str(user.id)
    if is_owner:
        user_role = "admin"
    else:
        from sqlalchemy import select

        from app.models.organization import OrganizationMember

        member = await db.scalar(
            select(OrganizationMember).where(
                OrganizationMember.org_id == org.id,
                OrganizationMember.user_id == user.id,
                OrganizationMember.status == "active",
            )
        )
        if member:
            user_role = member.role

    if not user_role:
        raise HTTPException(403, "You are not a member of this organization.")

    onboarding = await org_svc.get_onboarding_state(db, org.id)
    metrics = await org_svc.get_org_metrics(db, org.id)
    recent_events = await org_svc.get_recent_events(db, org.id)

    import json
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    orgs_json = json.dumps(
        [
            {
                "slug": entry["org"].slug,
                "name": entry["org"].name,
                "logo_url": entry["org"].logo_url or "",
                "role": entry["role"],
            }
            for entry in orgs
        ]
    )

    sidebar_state = {
        "has_events": onboarding.has_event,
        "has_revenue": metrics["total_revenue"] > 0,
        "has_registrations": metrics["total_registrations"] > 0,
        "whatsapp_connected": onboarding.has_whatsapp,
    }

    return templates.TemplateResponse(
        "dashboard/org_dashboard.html",
        {
            "request": request,
            "user": user,
            "org": org,
            "user_role": user_role,
            "is_owner": is_owner,
            "orgs": orgs,
            "orgs_json": orgs_json,
            "onboarding": onboarding,
            "metrics": metrics,
            "recent_events": recent_events,
            "sidebar_state": sidebar_state,
            "now_hour": now.hour,
        },
    )


# ── Accept invite page ────────────────────────────────────────────────────────


@router_pages.get("/accept-invite/{token}", response_class=HTMLResponse)
async def accept_invite_page(token: str, request: Request, db: DBSession):
    user, _ = await _get_auth_context(request, db)
    if not user:
        return RedirectResponse(f"/login?next=/accept-invite/{token}", status_code=302)

    try:
        org = await org_svc.accept_invite(db, token, user)
        return RedirectResponse(f"/org/{org.slug}?invited=1", status_code=302)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ── Attendee home ─────────────────────────────────────────────────────────────


@router_pages.get("/home", response_class=HTMLResponse)
async def attendee_home(request: Request, db: DBSession):
    user, orgs = await _get_auth_context(request, db)
    if not user:
        return RedirectResponse("/login?next=/home", status_code=302)

    # If user is an organizer, redirect to dashboard
    if user.role in ("organizer", "both") and orgs:
        return RedirectResponse("/dashboard", status_code=302)

    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.models.event import Event

    upcoming = await db.scalars(
        select(Event)
        .where(
            Event.status == "published",
            Event.deleted_at.is_(None),
            Event.end_datetime >= datetime.now(UTC),
        )
        .order_by(Event.start_datetime.asc())
        .limit(12)
    )

    return templates.TemplateResponse(
        "home/index.html",
        {
            "request": request,
            "user": user,
            "upcoming_events": list(upcoming.all()),
        },
    )


# ── Event pages (organizer) ───────────────────────────────────────────────────


async def _org_page_ctx(request: Request, db, slug: str) -> tuple:
    """Shared auth + org resolution for org-scoped pages. Returns (user, orgs, org, role, is_owner)."""
    from sqlalchemy import select

    from app.models.organization import OrganizationMember

    user, orgs = await _get_auth_context(request, db)
    if not user:
        return None, None, None, None, None

    org = await org_svc.get_organization_by_slug(db, slug)
    if not org:
        return user, orgs, None, None, None

    is_owner = str(org.owner_id) == str(user.id)
    if is_owner:
        return user, orgs, org, "admin", True

    member = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.org_id == org.id,
            OrganizationMember.user_id == user.id,
            OrganizationMember.status == "active",
        )
    )
    role = member.role if member else None
    return user, orgs, org, role, False


def _dash_ctx(request, user, org, orgs, onboarding, sidebar_state, **extra):
    """Build the standard dashboard template context."""
    import json

    orgs_json = json.dumps(
        [
            {
                "slug": e["org"].slug,
                "name": e["org"].name,
                "logo_url": e["org"].logo_url or "",
                "role": e["role"],
            }
            for e in orgs
        ]
    )
    return {
        "request": request,
        "user": user,
        "org": org,
        "orgs": orgs,
        "orgs_json": orgs_json,
        "onboarding": onboarding,
        "sidebar_state": sidebar_state,
        **extra,
    }


# ── Finance ───────────────────────────────────────────────────────────────────


@router_pages.get("/org/{slug}/finance", response_class=HTMLResponse)
async def org_finance(slug: str, request: Request, db: DBSession):
    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/finance", status_code=302)
    require_page_permission(Permission.FINANCE_VIEW, role, org)

    onboarding = await org_svc.get_onboarding_state(db, org.id)
    finance = await org_svc.get_org_finance_summary(db, org.id)
    sidebar_state = {
        "has_events": onboarding.has_event,
        "has_revenue": finance["net_amount"] > 0,
        "has_registrations": True,
        "whatsapp_connected": onboarding.has_whatsapp,
    }

    return templates.TemplateResponse(
        "dashboard/finance.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            finance=finance,
            active_page="finance",
        ),
    )


@router_pages.get("/org/{slug}/events", response_class=HTMLResponse)
async def org_events_list(slug: str, request: Request, db: DBSession):
    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/events", status_code=302)
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    from app.services import event_service as ev_svc

    status_filter = request.query_params.get("status")
    page = int(request.query_params.get("page", 1))
    items, total = await ev_svc.list_org_events(db, org.id, status=status_filter, page=page)
    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": onboarding.has_event,
        "has_revenue": False,
        "has_registrations": False,
        "whatsapp_connected": False,
    }

    return templates.TemplateResponse(
        "events/list.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            events=items,
            total=total,
            page=page,
            per_page=20,
            status_filter=status_filter,
            active_page="events",
        ),
    )


@router_pages.get("/org/{slug}/events/new", response_class=HTMLResponse)
async def org_event_new(slug: str, request: Request, db: DBSession):
    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/events/new", status_code=302)
    require_page_permission(Permission.EVENTS_MANAGE, role, org)

    from app.services import event_service as ev_svc

    categories = await ev_svc.get_all_categories(db)
    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": onboarding.has_event,
        "has_revenue": False,
        "has_registrations": False,
        "whatsapp_connected": False,
    }

    return templates.TemplateResponse(
        "events/create_edit.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            event=None,
            categories=categories,
            mode="create",
            active_page="events",
        ),
    )


@router_pages.get("/org/{slug}/events/{event_id}", response_class=HTMLResponse)
async def org_event_detail(slug: str, event_id: str, request: Request, db: DBSession):
    import uuid as _uuid

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/events/{event_id}", status_code=302)
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    from app.services import event_service as ev_svc
    from app.services import payment_service as pay_svc
    from app.services import ticketing_service as tk_svc

    event = await ev_svc.get_event_by_id(db, _uuid.UUID(event_id))
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")

    stats = await ev_svc.get_event_stats(db, event.id)
    ticket_types = await tk_svc.get_ticket_types(db, event.id)
    promo_codes = await tk_svc.get_promo_codes(db, event.id)
    onboarding = await org_svc.get_onboarding_state(db, org.id)
    recurring_children = (
        await ev_svc.list_recurring_children(db, event.id) if event.is_recurring else []
    )
    sidebar_state = {
        "has_events": True,
        "has_revenue": stats["total_revenue"] > 0,
        "has_registrations": stats["registration_count"] > 0,
        "whatsapp_connected": False,
    }

    return templates.TemplateResponse(
        "events/organizer_detail.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            event=event,
            stats=stats,
            user_role=role,
            ticket_types=ticket_types,
            promo_codes=promo_codes,
            platform_fee_percent=f"{float(pay_svc.PLATFORM_FEE_PERCENT) * 100:g}",
            recurring_children=recurring_children,
            active_page="events",
        ),
    )


@router_pages.get("/org/{slug}/events/{event_id}/live", response_class=HTMLResponse)
async def org_event_live(slug: str, event_id: str, request: Request, db: DBSession):
    import uuid as _uuid

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/events/{event_id}/live", status_code=302)
    require_page_permission(Permission.LIVE_ENGAGEMENT_MANAGE, role, org)

    from app.services import event_service as ev_svc

    event = await ev_svc.get_event_by_id(db, _uuid.UUID(event_id))
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")

    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": True,
        "has_revenue": False,
        "has_registrations": False,
        "whatsapp_connected": False,
    }

    return templates.TemplateResponse(
        "events/live_organizer.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            event=event,
            active_page="events",
        ),
    )


@router_pages.get("/org/{slug}/events/{event_id}/edit", response_class=HTMLResponse)
async def org_event_edit(slug: str, event_id: str, request: Request, db: DBSession):
    import uuid as _uuid

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/events/{event_id}/edit", status_code=302)
    require_page_permission(Permission.EVENTS_MANAGE, role, org)

    from app.services import agenda_service as ag_svc
    from app.services import event_service as ev_svc
    from app.services import speaker_service as sp_svc
    from app.services import sponsor_service as spn_svc
    from app.services import ticketing_service as tk_svc

    event = await ev_svc.get_event_by_id(db, _uuid.UUID(event_id))
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")

    if event.status == "cancelled":
        raise HTTPException(400, "Cannot edit a cancelled event.")

    from app.schemas.agenda import SessionOut
    from app.schemas.event import EventOut
    from app.schemas.sponsor import SponsorOut
    from app.schemas.ticketing import FormFieldOut, TicketTypeOut

    categories = await ev_svc.get_all_categories(db)
    ticket_types = await tk_svc.get_ticket_types(db, event.id)
    speaker_links = await sp_svc.list_event_speakers(db, event.id)
    sponsors = await spn_svc.list_sponsors(db, event.id)
    sessions = await ag_svc.list_sessions(db, event.id)
    form_fields = await tk_svc.get_form_fields(db, event.id)
    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": True,
        "has_revenue": False,
        "has_registrations": False,
        "whatsapp_connected": False,
    }
    event_dict = EventOut.model_validate(event).model_dump(mode="json")
    existing_tickets = [
        TicketTypeOut.model_validate(tt).model_dump(mode="json") for tt in ticket_types
    ]
    existing_speakers = [sp_svc.event_speaker_to_dict(link) for link in speaker_links]
    existing_sponsors = [SponsorOut.model_validate(s).model_dump(mode="json") for s in sponsors]
    existing_sessions = [SessionOut.model_validate(s).model_dump(mode="json") for s in sessions]
    existing_form_fields = [
        FormFieldOut.model_validate(f).model_dump(mode="json") for f in form_fields
    ]
    existing_section_order = ev_svc.get_effective_section_order(event)

    return templates.TemplateResponse(
        "events/create_edit.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            event=event,
            event_dict=event_dict,
            categories=categories,
            existing_tickets=existing_tickets,
            existing_speakers=existing_speakers,
            existing_sponsors=existing_sponsors,
            existing_sessions=existing_sessions,
            existing_form_fields=existing_form_fields,
            existing_section_order=existing_section_order,
            mode="edit",
            active_page="events",
        ),
    )


# ── Public event page ─────────────────────────────────────────────────────────


@router_pages.get("/e/{event_slug}", response_class=HTMLResponse)
async def public_event_page(event_slug: str, request: Request, db: DBSession):
    from app.services import event_service as ev_svc
    from app.services import ticketing_service as tk_svc
    from app.utils.calendar_file import google_calendar_url

    event = await ev_svc.get_event_by_slug(db, event_slug)
    if not event or event.deleted_at is not None or event.status == "draft":
        raise HTTPException(404, "Event not found.")

    from sqlalchemy import select

    from app.models.organization import Organization

    org = await db.scalar(select(Organization).where(Organization.id == event.org_id))
    user, _ = await _get_auth_context(request, db)

    if event.is_private:
        password_param = request.query_params.get("p")
        if not password_param or password_param != event.password:
            if not user:
                return RedirectResponse(f"/login?next=/e/{event_slug}", status_code=302)
            from app.models.ticketing import Registration

            has_ticket = await db.scalar(
                select(Registration).where(
                    Registration.event_id == event.id,
                    Registration.attendee_email == user.email,
                    Registration.status.in_(["confirmed", "checked_in"]),
                )
            )
            if not has_ticket:
                raise HTTPException(403, "This event is private. Contact the organizer for access.")

    ticket_types = await tk_svc.get_ticket_types(db, event.id, public_only=True)

    from app.schemas.agenda import SessionOut
    from app.schemas.sponsor import SponsorOut
    from app.services import agenda_service as ag_svc
    from app.services import inbox_service as inbox_svc
    from app.services import speaker_service as sp_svc
    from app.services import sponsor_service as spn_svc

    speaker_links = await sp_svc.list_event_speakers(db, event.id)
    speakers = [sp_svc.event_speaker_to_dict(link) for link in speaker_links]
    sponsor_rows = await spn_svc.list_sponsors(db, event.id)
    sponsors = [SponsorOut.model_validate(s).model_dump(mode="json") for s in sponsor_rows]
    session_rows = await ag_svc.list_sessions(db, event.id)
    sessions = [SessionOut.model_validate(s).model_dump(mode="json") for s in session_rows]
    speaker_id_to_name = {s["speaker_id"]: s["name"] for s in speakers}
    for sess, row in zip(sessions, session_rows, strict=True):
        sess["speaker_names"] = [
            speaker_id_to_name[sid] for sid in sess["speaker_ids"] if sid in speaker_id_to_name
        ]
        sess["time"] = row.start_datetime.strftime("%H:%M")
        sess["end_time"] = row.end_datetime.strftime("%H:%M")

    follower_count = await inbox_svc.get_follower_count(db, event.org_id)
    is_following = False
    is_interested = False
    connectable_attendees = []
    mutuals_going_count = 0
    if user and org:
        is_following = await inbox_svc.is_following(db, org_id=org.id, user_id=user.id)
    if user:
        from app.services import connection_service as conn_svc
        from app.services import interest_service as int_svc

        is_interested = await int_svc.is_interested(db, user.id, event.id)
        connectable_attendees = await conn_svc.list_connectable_attendees(
            db, event.id, exclude_user_id=user.id
        )

        accepted_ids = await conn_svc.accepted_connection_user_ids(db, user.id)
        if accepted_ids:
            from sqlalchemy import func

            from app.models.ticketing import Registration as _Reg

            mutuals_going_count = await db.scalar(
                select(func.count(func.distinct(_Reg.user_id))).where(
                    _Reg.event_id == event.id,
                    _Reg.status.in_(["confirmed", "checked_in"]),
                    _Reg.user_id.in_(accepted_ids),
                )
            )

    return templates.TemplateResponse(
        "events/public.html",
        {
            "request": request,
            "user": user,
            "event": event,
            "org": org,
            "ticket_types": ticket_types,
            "speakers": speakers,
            "sponsors": sponsors,
            "sessions": sessions,
            "follower_count": follower_count,
            "is_following": is_following,
            "is_interested": is_interested,
            "connectable_attendees": connectable_attendees,
            "mutuals_going_count": mutuals_going_count or 0,
            "sections": ev_svc.get_effective_section_order(event),
            "gcal_url": google_calendar_url(event) if event.start_datetime else None,
        },
    )


@router_pages.get("/e/{event_slug}/live", response_class=HTMLResponse)
async def event_live_page(event_slug: str, request: Request, db: DBSession):
    """Public — no login required, matching the anonymous-Q&A product
    decision. Anyone with the event link can vote and ask questions."""
    from sqlalchemy import select

    from app.services import event_service as ev_svc

    event = await ev_svc.get_event_by_slug(db, event_slug)
    if not event or event.deleted_at is not None or event.status == "draft":
        raise HTTPException(404, "Event not found.")

    from app.models.organization import Organization
    from app.utils.livestream import resolve_embed

    org = await db.scalar(select(Organization).where(Organization.id == event.org_id))
    livestream = resolve_embed(event.livestream_url)

    return templates.TemplateResponse(
        "events/live_attendee.html",
        {"request": request, "event": event, "org": org, "livestream": livestream},
    )


# ── Registration pages ────────────────────────────────────────────────────────


@router_pages.get("/e/{event_slug}/register", response_class=HTMLResponse)
async def register_page(event_slug: str, request: Request, db: DBSession):
    import json as _json

    from sqlalchemy import select

    from app.models.organization import Organization
    from app.services import event_service as ev_svc
    from app.services import ticketing_service as tk_svc

    event = await ev_svc.get_event_by_slug(db, event_slug)
    if not event or event.deleted_at is not None or event.status == "draft":
        raise HTTPException(404, "Event not found.")

    if event.status not in ("published", "live"):
        return RedirectResponse(f"/e/{event_slug}", status_code=302)

    org = await db.scalar(select(Organization).where(Organization.id == event.org_id))
    user, _ = await _get_auth_context(request, db)

    ticket_types = await tk_svc.get_ticket_types(db, event.id, public_only=True)
    if not ticket_types:
        return RedirectResponse(f"/e/{event_slug}?no_tickets=1", status_code=302)

    form_fields = await tk_svc.get_form_fields(db, event.id)

    ticket_types_json = _json.dumps(
        [
            {
                "id": str(tt.id),
                "name": tt.name,
                "description": tt.description,
                "price": str(tt.price),
                "currency": tt.currency,
                "tier": tt.tier,
                "quantity": tt.quantity,
                "quantity_sold": tt.quantity_sold,
                "quantity_reserved": tt.quantity_reserved,
                "quantity_available": (
                    max(0, tt.quantity - tt.quantity_sold - tt.quantity_reserved)
                    if tt.quantity is not None
                    else None
                ),
                "is_sold_out": (
                    tt.quantity is not None
                    and tt.quantity_sold + tt.quantity_reserved >= tt.quantity
                ),
                "min_per_order": tt.min_per_order,
                "max_per_order": tt.max_per_order,
            }
            for tt in ticket_types
        ]
    )

    form_fields_json = _json.dumps(
        [
            {
                "id": str(ff.id),
                "label": ff.label,
                "field_type": ff.field_type,
                "is_required": ff.is_required,
                "options": ff.options or [],
                "applies_to_ticket_type_ids": ff.applies_to_ticket_type_ids or None,
            }
            for ff in form_fields
        ]
    )

    return templates.TemplateResponse(
        "events/register.html",
        {
            "request": request,
            "user": user,
            "event": event,
            "org": org,
            "ticket_types": ticket_types,
            "form_fields": form_fields,
            "ticket_types_json": ticket_types_json,
            "form_fields_json": form_fields_json,
        },
    )


@router_pages.get("/e/{event_slug}/widget", response_class=HTMLResponse)
async def event_widget(event_slug: str, request: Request, db: DBSession):
    import json as _json

    from app.services import event_service as ev_svc
    from app.services import ticketing_service as tk_svc

    event = await ev_svc.get_event_by_slug(db, event_slug)
    if not event or event.deleted_at is not None or event.status not in ("published", "live"):
        raise HTTPException(404, "Event not found or not accepting registrations.")

    ticket_types = await tk_svc.get_ticket_types(db, event.id, public_only=True)
    form_fields = await tk_svc.get_form_fields(db, event.id)

    ticket_types_json = _json.dumps(
        [
            {
                "id": str(tt.id),
                "name": tt.name,
                "description": tt.description,
                "price": str(tt.price),
                "currency": tt.currency,
                "tier": tt.tier,
                "quantity": tt.quantity,
                "quantity_sold": tt.quantity_sold,
                "quantity_reserved": tt.quantity_reserved,
                "is_sold_out": (
                    tt.quantity is not None
                    and tt.quantity_sold + tt.quantity_reserved >= tt.quantity
                ),
                "min_per_order": tt.min_per_order,
                "max_per_order": tt.max_per_order,
            }
            for tt in ticket_types
        ]
    )

    form_fields_json = _json.dumps(
        [
            {
                "id": str(ff.id),
                "label": ff.label,
                "field_type": ff.field_type,
                "is_required": ff.is_required,
                "options": ff.options or [],
            }
            for ff in form_fields
        ]
    )

    response = templates.TemplateResponse(
        "events/widget.html",
        {
            "request": request,
            "event": event,
            "ticket_types": ticket_types,
            "form_fields": form_fields,
            "ticket_types_json": ticket_types_json,
            "form_fields_json": form_fields_json,
        },
    )
    response.headers["Content-Security-Policy"] = "frame-ancestors *"
    return response


# ── Payment callbacks (browser redirect after gateway) ────────────────────────


@router_pages.get("/payments/callback", response_class=HTMLResponse)
async def paystack_callback(request: Request, db: DBSession, reference: str = ""):
    from fastapi.responses import RedirectResponse

    from app.services import payment_service as pay_svc

    if not reference.startswith("heelo_"):
        return RedirectResponse("/?error=invalid_reference", status_code=302)

    order = await pay_svc.verify_paystack(db, reference)
    if not order:
        return RedirectResponse("/?error=payment_failed", status_code=302)

    if order.payment_status == "paid":
        return RedirectResponse(f"/orders/{order.id}/confirmation", status_code=302)
    return RedirectResponse(f"/orders/{order.id}/confirmation?pending=1", status_code=302)


@router_pages.get("/payments/flutterwave/callback", response_class=HTMLResponse)
async def flutterwave_callback(
    request: Request,
    db: DBSession,
    status: str = "",
    tx_ref: str = "",
    transaction_id: str = "",
):
    from fastapi.responses import RedirectResponse

    from app.services import payment_service as pay_svc

    if status == "successful" and transaction_id:
        try:
            order = await pay_svc.verify_flutterwave(db, int(transaction_id))
        except (ValueError, Exception):
            order = None

        if order and order.payment_status == "paid":
            return RedirectResponse(f"/orders/{order.id}/confirmation", status_code=302)

    return RedirectResponse("/?error=payment_failed", status_code=302)


@router_pages.get("/payments/stripe/return", response_class=HTMLResponse)
async def stripe_return(request: Request, db: DBSession, session_id: str = ""):
    from fastapi.responses import RedirectResponse

    from app.services import payment_service as pay_svc

    if not session_id:
        return RedirectResponse("/?error=missing_session", status_code=302)

    order = await pay_svc.verify_stripe_session(db, session_id)
    if order and order.payment_status == "paid":
        return RedirectResponse(f"/orders/{order.id}/confirmation", status_code=302)

    return RedirectResponse("/?error=payment_failed", status_code=302)


# ── Payment settings page ─────────────────────────────────────────────────────


@router_pages.get("/org/{slug}/events/{event_id}/kiosk", response_class=HTMLResponse)
async def kiosk_page(slug: str, event_id: str, request: Request, db: DBSession):
    import uuid as _uuid

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/events/{event_id}/kiosk", status_code=302)
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    from app.services import event_service as ev_svc

    event = await ev_svc.get_event_by_id(db, _uuid.UUID(event_id))
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")

    return templates.TemplateResponse(
        "events/kiosk.html",
        {"request": request, "user": user, "org": org, "event": event},
    )


@router_pages.get("/org/{slug}/events/{event_id}/pulse", response_class=HTMLResponse)
async def pulse_page(slug: str, event_id: str, request: Request, db: DBSession):
    """Glanceable mid-event dashboard — check-in rate, capacity fill, ticket tiers, live via SSE."""
    import uuid as _uuid

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/events/{event_id}/pulse", status_code=302)
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    from app.services import checkin_service as ci_svc
    from app.services import event_service as ev_svc

    event = await ev_svc.get_event_by_id(db, _uuid.UUID(event_id))
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")

    initial_stats = await ci_svc.get_live_pulse(db, event)

    return templates.TemplateResponse(
        "events/pulse.html",
        {"request": request, "user": user, "org": org, "event": event, "stats": initial_stats},
    )


@router_pages.get("/org/{slug}/events/{event_id}/check-in", response_class=HTMLResponse)
async def checkin_dashboard_page(slug: str, event_id: str, request: Request, db: DBSession):
    import uuid as _uuid

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(
            f"/login?next=/org/{slug}/events/{event_id}/check-in", status_code=302
        )
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    from app.services import event_service as ev_svc

    event = await ev_svc.get_event_by_id(db, _uuid.UUID(event_id))
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")

    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": True,
        "has_revenue": False,
        "has_registrations": True,
        "whatsapp_connected": onboarding.has_whatsapp,
    }

    return templates.TemplateResponse(
        "events/checkin_dashboard.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            event=event,
            user_role=role,
            is_owner=is_owner,
            active_page="events",
        ),
    )


@router_pages.get("/org/{slug}/settings/payments", response_class=HTMLResponse)
async def payment_settings(slug: str, request: Request, db: DBSession):
    import json as _json

    from app.services import payment_account_service as acc_svc

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/settings/payments", status_code=302)
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    accounts = await acc_svc.list_payment_accounts(db, org.id)
    banks = await acc_svc.list_paystack_banks()
    banks_json = _json.dumps(banks)

    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": onboarding.has_event,
        "has_revenue": False,
        "has_registrations": False,
        "whatsapp_connected": onboarding.has_whatsapp,
    }

    return templates.TemplateResponse(
        "dashboard/payment_settings.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            accounts=accounts,
            banks_json=banks_json,
            is_owner=is_owner,
            user_role=role,
            active_page="settings",
        ),
    )


@router_pages.get("/org/{slug}/campaigns", response_class=HTMLResponse)
async def campaigns_list(slug: str, request: Request, db: DBSession):
    from sqlalchemy import select

    from app.models.event import Event
    from app.services import campaign_service as camp_svc

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/campaigns", status_code=302)
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    page = int(request.query_params.get("page", 1))
    campaigns, total = await camp_svc.list_campaigns(db, org.id, page=page, per_page=20)

    # Attach event name for display
    event_ids = {c.event_id for c in campaigns if c.event_id}
    events_by_id = {}
    if event_ids:
        ev_rows = await db.scalars(select(Event).where(Event.id.in_(event_ids)))
        events_by_id = {ev.id: ev for ev in ev_rows.all()}

    for c in campaigns:
        c._event_name = (
            events_by_id[c.event_id].title if c.event_id and c.event_id in events_by_id else None
        )
    camps_with_event = campaigns

    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": onboarding.has_event,
        "has_revenue": False,
        "has_registrations": False,
        "whatsapp_connected": onboarding.has_whatsapp,
    }
    return templates.TemplateResponse(
        "campaigns/list.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            campaigns=camps_with_event,
            total=total,
            page=page,
            per_page=20,
            active_page="campaigns",
        ),
    )


@router_pages.get("/org/{slug}/campaigns/new", response_class=HTMLResponse)
async def campaign_new(slug: str, request: Request, db: DBSession):
    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/campaigns/new", status_code=302)
    require_page_permission(Permission.CAMPAIGNS_MANAGE, role, org)

    import json as _json

    from app.services import event_service as ev_svc

    event_rows, _ = await ev_svc.list_org_events(db, org.id, page=1, per_page=100)
    events = [row["event"] for row in event_rows]
    events_json = _json.dumps(
        [
            {
                "id": str(e.id),
                "title": e.title,
                "start_datetime": e.start_datetime.isoformat() if e.start_datetime else "",
                "description": e.description or "",
            }
            for e in events
        ]
    )
    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": onboarding.has_event,
        "has_revenue": False,
        "has_registrations": False,
        "whatsapp_connected": onboarding.has_whatsapp,
    }

    return templates.TemplateResponse(
        "campaigns/builder.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            campaign=None,
            events=events,
            events_json=events_json,
            active_page="campaigns",
        ),
    )


@router_pages.get("/org/{slug}/campaigns/{campaign_id}", response_class=HTMLResponse)
async def campaign_detail(slug: str, campaign_id: str, request: Request, db: DBSession):
    import uuid as _uuid

    from sqlalchemy import select

    from app.models.event import Event
    from app.services import campaign_service as camp_svc

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/campaigns/{campaign_id}", status_code=302)
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    try:
        cid = _uuid.UUID(campaign_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid campaign ID.") from err

    campaign = await camp_svc.get_campaign(db, cid)
    if not campaign or campaign.org_id != org.id:
        raise HTTPException(404, "Campaign not found.")

    event = None
    if campaign.event_id:
        event = await db.scalar(select(Event).where(Event.id == campaign.event_id))

    recipient_stats = await camp_svc.get_recipient_stats(db, campaign.id)
    recipients = await camp_svc.get_recent_recipients(db, campaign.id, limit=100)

    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": True,
        "has_revenue": False,
        "has_registrations": False,
        "whatsapp_connected": onboarding.has_whatsapp,
    }

    return templates.TemplateResponse(
        "campaigns/detail.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            campaign=campaign,
            event=event,
            recipient_stats=recipient_stats,
            recipients=recipients,
            user_role=role,
            is_owner=is_owner,
            active_page="campaigns",
        ),
    )


@router_pages.get("/org/{slug}/campaigns/{campaign_id}/edit", response_class=HTMLResponse)
async def campaign_edit(slug: str, campaign_id: str, request: Request, db: DBSession):
    import uuid as _uuid

    from app.services import campaign_service as camp_svc
    from app.services import event_service as ev_svc

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(
            f"/login?next=/org/{slug}/campaigns/{campaign_id}/edit", status_code=302
        )
    require_page_permission(Permission.CAMPAIGNS_MANAGE, role, org)

    try:
        cid = _uuid.UUID(campaign_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid campaign ID.") from err

    campaign = await camp_svc.get_campaign(db, cid)
    if not campaign or campaign.org_id != org.id:
        raise HTTPException(404, "Campaign not found.")
    if campaign.status not in ("draft", "scheduled"):
        raise HTTPException(400, "Only draft or scheduled campaigns can be edited.")

    import json as _json

    event_rows, _ = await ev_svc.list_org_events(db, org.id, page=1, per_page=100)
    events = [row["event"] for row in event_rows]
    events_json = _json.dumps(
        [
            {
                "id": str(e.id),
                "title": e.title,
                "start_datetime": e.start_datetime.isoformat() if e.start_datetime else "",
                "description": e.description or "",
            }
            for e in events
        ]
    )
    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": True,
        "has_revenue": False,
        "has_registrations": False,
        "whatsapp_connected": onboarding.has_whatsapp,
    }

    return templates.TemplateResponse(
        "campaigns/builder.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            campaign=campaign,
            events=events,
            events_json=events_json,
            active_page="campaigns",
        ),
    )


@router_pages.get("/org/{slug}/events/{event_id}/analytics", response_class=HTMLResponse)
async def analytics_page(slug: str, event_id: str, request: Request, db: DBSession):
    import json as _json
    import uuid as _uuid

    from app.services import analytics_service as an_svc
    from app.services import event_service as ev_svc

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(
            f"/login?next=/org/{slug}/events/{event_id}/analytics", status_code=302
        )
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    event = await ev_svc.get_event_by_id(db, _uuid.UUID(event_id))
    if not event or str(event.org_id) != str(org.id):
        raise HTTPException(404, "Event not found.")

    eid = event.id
    summary = await an_svc.get_event_summary(db, eid)
    ticket_breakdown = await an_svc.get_ticket_breakdown(db, eid)
    sales = await an_svc.get_sales_over_time(db, eid)
    reg_over_time = await an_svc.get_registration_over_time(db, eid)
    utm_breakdown = await an_svc.get_utm_breakdown(db, eid)
    promos = await an_svc.get_promo_breakdown(db, eid)

    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": True,
        "has_revenue": summary["net_revenue"] > 0,
        "has_registrations": summary["total_registrations"] > 0,
        "whatsapp_connected": onboarding.has_whatsapp,
    }
    currency = ticket_breakdown[0]["currency"] if ticket_breakdown else (org.currency or "NGN")

    return templates.TemplateResponse(
        "dashboard/analytics.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            event=event,
            user_role=role,
            is_owner=is_owner,
            summary=summary,
            ticket_breakdown=ticket_breakdown,
            ticket_breakdown_json=_json.dumps(ticket_breakdown),
            sales_json=_json.dumps(sales),
            reg_over_time_json=_json.dumps(reg_over_time),
            utm_breakdown=utm_breakdown,
            promos=promos,
            currency=currency,
            active_page="events",
        ),
    )


# ── WhatsApp Inbox ───────────────────────────────────────────────────────────


@router_pages.get("/org/{slug}/inbox", response_class=HTMLResponse)
async def inbox_list(slug: str, request: Request, db: DBSession):
    from app.services import inbox_service as inbox_svc

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/inbox", status_code=302)
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    threads = await inbox_svc.list_threads(db, org.id)
    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": onboarding.has_event,
        "has_revenue": False,
        "has_registrations": False,
        "whatsapp_connected": True,
    }
    return templates.TemplateResponse(
        "inbox/list.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            threads=threads,
            active_page="inbox",
        ),
    )


@router_pages.get("/org/{slug}/inbox/{phone}", response_class=HTMLResponse)
async def inbox_thread(slug: str, phone: str, request: Request, db: DBSession):
    from app.services import inbox_service as inbox_svc

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/inbox/{phone}", status_code=302)
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    threads = await inbox_svc.list_threads(db, org.id)
    messages = await inbox_svc.get_thread_messages(db, org.id, phone)
    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": onboarding.has_event,
        "has_revenue": False,
        "has_registrations": False,
        "whatsapp_connected": True,
    }
    return templates.TemplateResponse(
        "inbox/thread.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            threads=threads,
            messages=messages,
            active_phone=phone,
            active_page="inbox",
        ),
    )


# ── Attendee CRM ─────────────────────────────────────────────────────────────


@router_pages.get("/org/{slug}/registrations", response_class=HTMLResponse)
async def crm_list(slug: str, request: Request, db: DBSession):
    import uuid as _uuid

    from app.services import crm_service as crm_svc

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/registrations", status_code=302)
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    q = request.query_params.get("q", "").strip() or None
    event_id_str = request.query_params.get("event_id", "").strip() or None
    status_filter = request.query_params.get("status", "").strip() or None
    page = max(1, int(request.query_params.get("page", 1)))

    eid: _uuid.UUID | None = None
    if event_id_str:
        try:
            eid = _uuid.UUID(event_id_str)
        except ValueError:
            pass

    regs, total = await crm_svc.list_registrations(
        db,
        org.id,
        event_id=eid,
        status=status_filter,
        search=q,
        page=page,
        per_page=50,
    )
    events = await crm_svc.get_events_for_org(db, org.id)
    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": onboarding.has_event,
        "has_revenue": False,
        "has_registrations": True,
        "whatsapp_connected": onboarding.has_whatsapp,
    }

    ctx = _dash_ctx(
        request,
        user,
        org,
        orgs,
        onboarding,
        sidebar_state,
        registrations=regs,
        total=total,
        page=page,
        per_page=50,
        events=events,
        q=q or "",
        selected_event=event_id_str or "",
        selected_status=status_filter or "",
        active_page="registrations",
    )

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("crm/_table.html", ctx)
    return templates.TemplateResponse("crm/list.html", ctx)


@router_pages.get("/org/{slug}/checkin", response_class=HTMLResponse)
async def checkin_hub(slug: str, request: Request, db: DBSession):
    """
    Org-wide check-in hub — Kiosk and the check-in dashboard are event-scoped
    (need to know which event), but the sidebar is org-scoped, so this page
    is the jumping-off point: pick the event, then open Kiosk or the dashboard.
    """
    from sqlalchemy import select

    from app.models.event import Event
    from app.services import checkin_service as ci_svc

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/checkin", status_code=302)
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    live_and_upcoming = list(
        (
            await db.scalars(
                select(Event)
                .where(
                    Event.org_id == org.id,
                    Event.deleted_at.is_(None),
                    Event.status.in_(["live", "published"]),
                )
                .order_by(Event.status.desc(), Event.start_datetime.asc())
            )
        ).all()
    )
    ended = list(
        (
            await db.scalars(
                select(Event)
                .where(
                    Event.org_id == org.id,
                    Event.deleted_at.is_(None),
                    Event.status == "ended",
                )
                .order_by(Event.start_datetime.desc())
                .limit(10)
            )
        ).all()
    )

    stats_by_event = {}
    for event in live_and_upcoming:
        stats_by_event[event.id] = await ci_svc.get_checkin_stats(db, event.id)

    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": onboarding.has_event,
        "has_revenue": False,
        "has_registrations": True,
        "whatsapp_connected": onboarding.has_whatsapp,
    }

    ctx = _dash_ctx(
        request,
        user,
        org,
        orgs,
        onboarding,
        sidebar_state,
        live_and_upcoming=live_and_upcoming,
        ended=ended,
        stats_by_event=stats_by_event,
        active_page="checkin",
    )
    return templates.TemplateResponse("events/checkin_hub.html", ctx)


@router_pages.get("/org/{slug}/registrations/attendee/{email:path}", response_class=HTMLResponse)
async def crm_attendee(slug: str, email: str, request: Request, db: DBSession):
    from app.services import crm_service as crm_svc

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(
            f"/login?next=/org/{slug}/registrations/attendee/{email}", status_code=302
        )
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    regs, summary = await crm_svc.get_attendee_history(db, org.id, email)
    if not regs:
        raise HTTPException(404, "No registrations found for this attendee.")

    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": onboarding.has_event,
        "has_revenue": False,
        "has_registrations": True,
        "whatsapp_connected": onboarding.has_whatsapp,
    }
    return templates.TemplateResponse(
        "crm/attendee.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            registrations=regs,
            summary=summary,
            active_page="registrations",
        ),
    )


@router_pages.get("/orders/{order_id}/confirmation", response_class=HTMLResponse)
async def order_confirmation(order_id: str, request: Request, db: DBSession):
    import uuid as _uuid

    from sqlalchemy import select

    from app.models.event import Event
    from app.models.organization import Organization
    from app.services import ticketing_service as tk_svc

    try:
        oid = _uuid.UUID(order_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid order ID.") from err

    order = await tk_svc.get_order(db, oid)
    if not order:
        raise HTTPException(404, "Order not found.")

    event = await db.scalar(select(Event).where(Event.id == order.event_id))
    org = await db.scalar(select(Organization).where(Organization.id == event.org_id))
    user, _ = await _get_auth_context(request, db)
    pending = request.query_params.get("pending") == "1"
    cancelled = request.query_params.get("cancelled") == "1"

    return templates.TemplateResponse(
        "events/order_confirmation.html",
        {
            "request": request,
            "user": user,
            "order": order,
            "event": event,
            "org": org,
            "pending": pending,
            "cancelled": cancelled,
        },
    )


@router_pages.get("/orders/{order_id}/pay")
async def order_pay(order_id: str, request: Request, db: DBSession):
    import uuid as _uuid

    from sqlalchemy import select

    from app.models.event import Event
    from app.models.organization import Organization
    from app.services import payment_service as pay_svc
    from app.services import ticketing_service as tk_svc

    try:
        oid = _uuid.UUID(order_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid order ID.") from err

    order = await tk_svc.get_order(db, oid)
    if not order:
        raise HTTPException(404, "Order not found.")

    if order.payment_status != "pending":
        return RedirectResponse(f"/orders/{order_id}/confirmation", status_code=302)

    event = await db.scalar(select(Event).where(Event.id == order.event_id))
    org = await db.scalar(select(Organization).where(Organization.id == event.org_id))

    try:
        payment_url = await pay_svc.initialize_payment(db, order, event, org)
        return RedirectResponse(payment_url, status_code=302)
    except HTTPException:
        return RedirectResponse(
            f"/orders/{order_id}/confirmation?pending=1&error=1", status_code=302
        )


# ── My Tickets ───────────────────────────────────────────────────────────────


@router_pages.get("/my-tickets", response_class=HTMLResponse)
async def my_tickets(request: Request, db: DBSession, page: int = 1):
    from datetime import UTC, datetime

    from app.services import ticketing_service as tk_svc

    user, orgs = await _get_auth_context(request, db)
    if not user:
        return RedirectResponse("/login?next=/my-tickets", status_code=302)

    registrations, total = await tk_svc.get_user_registrations(
        db,
        user_id=user.id,
        email=user.email,
        page=page,
        per_page=20,
    )

    now = datetime.now(UTC)
    upcoming = [r for r in registrations if r.event and r.event.start_datetime >= now]
    past = [r for r in registrations if r.event and r.event.start_datetime < now]

    primary_org = orgs[0]["org"] if orgs else None
    onboarding = await org_svc.get_onboarding_state(db, primary_org.id) if primary_org else None
    sidebar_state = {
        "has_events": onboarding.has_event if onboarding else False,
        "has_revenue": False,
        "has_registrations": bool(registrations),
        "whatsapp_connected": onboarding.has_whatsapp if onboarding else False,
    }

    import math

    total_pages = math.ceil(total / 20) if total else 1

    return templates.TemplateResponse(
        "dashboard/my_tickets.html",
        {
            "request": request,
            "user": user,
            "org": primary_org,
            "orgs": orgs,
            "onboarding": onboarding,
            "sidebar_state": sidebar_state,
            "active_page": "my_tickets",
            "upcoming": upcoming,
            "past": past,
            "total": total,
            "page": page,
            "total_pages": total_pages,
        },
    )


@router_pages.get("/my-tickets/{registration_id}", response_class=HTMLResponse)
async def ticket_view(registration_id: str, request: Request, db: DBSession):
    """A single printable ticket — branded, self-hosted QR, print-optimized."""
    import uuid as _uuid

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.event import Event
    from app.models.ticketing import Registration

    user, _orgs = await _get_auth_context(request, db)
    if not user:
        return RedirectResponse(f"/login?next=/my-tickets/{registration_id}", status_code=302)

    try:
        reg_uuid = _uuid.UUID(registration_id)
    except ValueError as err:
        raise HTTPException(404, "Ticket not found.") from err

    reg = await db.scalar(
        select(Registration)
        .where(Registration.id == reg_uuid)
        .options(
            selectinload(Registration.event).selectinload(Event.organization),
            selectinload(Registration.ticket_type),
        )
    )
    if not reg or not reg.event:
        raise HTTPException(404, "Ticket not found.")

    owns_ticket = str(reg.user_id) == str(user.id) or (
        reg.attendee_email and reg.attendee_email.lower() == user.email.lower()
    )
    if not owns_ticket:
        raise HTTPException(403, "This isn't your ticket.")

    from app.services.email_service import gcal_url

    return templates.TemplateResponse(
        "dashboard/ticket_view.html",
        {
            "request": request,
            "user": user,
            "reg": reg,
            "event": reg.event,
            "org": reg.event.organization,
            "gcal_url": gcal_url(reg.event),
        },
    )


# ── User profile ─────────────────────────────────────────────────────────────


@router_pages.get("/profile", response_class=HTMLResponse)
async def user_profile(request: Request, db: DBSession):
    user, orgs = await _get_auth_context(request, db)
    if not user:
        return RedirectResponse("/login?next=/profile", status_code=302)

    primary_org = orgs[0]["org"] if orgs else None
    onboarding = await org_svc.get_onboarding_state(db, primary_org.id) if primary_org else None
    sidebar_state = {
        "has_events": onboarding.has_event if onboarding else False,
        "has_revenue": False,
        "has_registrations": False,
        "whatsapp_connected": onboarding.has_whatsapp if onboarding else False,
    }
    import json

    orgs_json = json.dumps(
        [
            {
                "slug": e["org"].slug,
                "name": e["org"].name,
                "logo_url": e["org"].logo_url or "",
                "role": e["role"],
            }
            for e in orgs
        ]
    )
    return templates.TemplateResponse(
        "dashboard/profile.html",
        {
            "request": request,
            "user": user,
            "org": primary_org,
            "orgs": orgs,
            "orgs_json": orgs_json,
            "onboarding": onboarding,
            "sidebar_state": sidebar_state,
            "active_page": "profile",
            "has_password": bool(user.password_hash),
        },
    )


# ── Org settings ──────────────────────────────────────────────────────────────


@router_pages.get("/org/{slug}/settings", response_class=HTMLResponse)
async def org_settings(slug: str, request: Request, db: DBSession):
    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/settings", status_code=302)
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": onboarding.has_event,
        "has_revenue": False,
        "has_registrations": False,
        "whatsapp_connected": onboarding.has_whatsapp,
    }
    return templates.TemplateResponse(
        "dashboard/org_settings.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            is_owner=is_owner,
            user_role=role,
            active_page="settings",
        ),
    )


# ── Team ─────────────────────────────────────────────────────────────────────


@router_pages.get("/org/{slug}/team", response_class=HTMLResponse)
async def org_team(slug: str, request: Request, db: DBSession):
    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/team", status_code=302)
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    members = await org_svc.get_org_members(db, org.id)
    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": onboarding.has_event,
        "has_revenue": False,
        "has_registrations": False,
        "whatsapp_connected": onboarding.has_whatsapp,
    }

    import json

    members_json = json.dumps(
        [
            {
                "id": str(m["member"].id),
                "user_id": str(m["member"].user_id) if m["member"].user_id else None,
                "role": m["member"].role,
                "status": m["member"].status,
                "name": m["display_name"],
                "email": m["display_email"],
                "avatar": m["display_avatar"],
                "invited_at": m["member"].invited_at.isoformat(),
                "accepted_at": (
                    m["member"].accepted_at.isoformat() if m["member"].accepted_at else None
                ),
            }
            for m in members
        ]
    )
    return templates.TemplateResponse(
        "dashboard/team.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            members=members,
            members_json=members_json,
            is_owner=is_owner,
            user_role=role,
            current_user_id=str(user.id),
            active_page="team",
        ),
    )


# ── Plan ─────────────────────────────────────────────────────────────────────


@router_pages.get("/org/{slug}/plan", response_class=HTMLResponse)
async def org_plan(slug: str, request: Request, db: DBSession):
    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/plan", status_code=302)
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": onboarding.has_event,
        "has_revenue": False,
        "has_registrations": False,
        "whatsapp_connected": onboarding.has_whatsapp,
    }
    return templates.TemplateResponse(
        "dashboard/plan.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            is_owner=is_owner,
            user_role=role,
            active_page="plan",
        ),
    )


# ── Developer settings ────────────────────────────────────────────────────────


@router_pages.get("/org/{slug}/settings/developer", response_class=HTMLResponse)
async def developer_settings(slug: str, request: Request, db: DBSession):
    import json as _json

    from app.services import api_key_service as ak_svc
    from app.services import webhook_service as wh_svc

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/settings/developer", status_code=302)
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    api_keys = await ak_svc.list_api_keys(db, org.id)
    webhook_subs = await wh_svc.list_subscriptions(db, org.id)

    api_keys_json = _json.dumps(
        [
            {
                "id": str(k.id),
                "name": k.name,
                "key_prefix": k.key_prefix,
                "is_active": k.is_active,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "created_at": k.created_at.isoformat(),
            }
            for k in api_keys
        ]
    )
    webhooks_json = _json.dumps(
        [
            {
                "id": str(s.id),
                "url": s.url,
                "events": s.events,
                "description": s.description or "",
                "is_active": s.is_active,
                "created_at": s.created_at.isoformat(),
            }
            for s in webhook_subs
        ]
    )

    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": onboarding.has_event,
        "has_revenue": False,
        "has_registrations": False,
        "whatsapp_connected": onboarding.has_whatsapp,
    }
    from app.services.webhook_service import WEBHOOK_EVENTS

    return templates.TemplateResponse(
        "dashboard/developer_settings.html",
        _dash_ctx(
            request,
            user,
            org,
            orgs,
            onboarding,
            sidebar_state,
            api_keys=api_keys,
            webhook_subs=webhook_subs,
            api_keys_json=api_keys_json,
            webhooks_json=webhooks_json,
            webhook_events=WEBHOOK_EVENTS,
            is_owner=is_owner,
            user_role=role,
            active_page="developer",
        ),
    )


# ── Public events discovery ───────────────────────────────────────────────────


@router_pages.get("/events", response_class=HTMLResponse)
async def public_events_list(
    request: Request,
    db: DBSession,
    q: str | None = None,
    city: str | None = None,
    format: str | None = None,
    page: int = 1,
):
    from sqlalchemy import distinct
    from sqlalchemy import select as _select

    from app.models.event import Event
    from app.services import event_service as ev_svc

    user, orgs = await _get_auth_context(request, db)

    per_page = 24
    events, total = await ev_svc.search_public_events(
        db, q=q, city=city, format=format, page=page, per_page=per_page
    )
    total_pages = (total + per_page - 1) // per_page

    city_rows = await db.scalars(
        _select(distinct(Event.venue_city))
        .where(Event.venue_city.isnot(None), Event.status.in_(["published", "live"]))
        .order_by(Event.venue_city)
        .limit(50)
    )
    cities = [c for c in city_rows.all() if c]

    def qs_without(param: str) -> str:
        params = dict(request.query_params)
        params.pop(param, None)
        return "&".join(f"{k}={v}" for k, v in params.items())

    def qs_with_page(p: int) -> str:
        params = dict(request.query_params)
        params["page"] = str(p)
        return "&".join(f"{k}={v}" for k, v in params.items())

    return templates.TemplateResponse(
        "home/events.html",
        {
            "request": request,
            "user": user,
            "events": events,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "q": q,
            "city": city,
            "format": format,
            "cities": cities,
            "query_string_without": qs_without,
            "query_string_with_page": qs_with_page,
        },
    )


@router_pages.get("/discover", response_class=HTMLResponse)
async def discover_feed(request: Request, db: DBSession, page: int = 1):
    """
    Feed-style event discovery — vertical scroll, one card at a time.
    Additive alongside /events; does not replace the existing listing page.
    """
    from app.services import connection_service as conn_svc
    from app.services import event_service as ev_svc
    from app.services import interest_service as int_svc

    user, _orgs = await _get_auth_context(request, db)

    per_page = 10
    ranked, total = await ev_svc.get_discovery_feed(db, page=page, per_page=per_page)
    has_more = page * per_page < total

    interested_ids: set = set()
    mutuals_going: dict = {}
    if user:
        event_ids = [e.id for e, _ in ranked]
        interested_ids = await int_svc.interested_event_ids_for_user(db, user.id, event_ids)
        mutuals_going = await conn_svc.batch_mutuals_going(db, user.id, event_ids)

    ctx = {
        "request": request,
        "user": user,
        "items": ranked,  # list of (event, registration_count) tuples
        "interested_ids": interested_ids,
        "mutuals_going": mutuals_going,
        "page": page,
        "has_more": has_more,
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("home/_discover_cards.html", ctx)
    return templates.TemplateResponse("home/discover.html", ctx)


# ── Vendor marketplace ────────────────────────────────────────────────────────


@router_pages.get("/vendors", response_class=HTMLResponse)
async def vendor_list(
    request: Request,
    db: DBSession,
    q: str | None = None,
    category: str | None = None,
    city: str | None = None,
    price_range: str | None = None,
    page: int = 1,
):
    from sqlalchemy import distinct
    from sqlalchemy import select as _select

    from app.models.vendor import Vendor
    from app.services import vendor_service as vsvc

    user, orgs = await _get_auth_context(request, db)

    vendors, total = await vsvc.list_vendors(
        db, q=q, category=category, city=city, price_range=price_range, page=page
    )

    city_rows = await db.scalars(
        _select(distinct(Vendor.location_city))
        .where(Vendor.location_city.isnot(None), Vendor.status == "active")
        .order_by(Vendor.location_city)
        .limit(50)
    )
    cities = [c for c in city_rows.all() if c]

    def qs_without_cat() -> str:
        params = dict(request.query_params)
        params.pop("category", None)
        return "&".join(f"{k}={v}" for k, v in params.items())

    def qs_with_cat(cat: str) -> str:
        params = dict(request.query_params)
        params["category"] = cat
        return "&".join(f"{k}={v}" for k, v in params.items())

    return templates.TemplateResponse(
        "vendors/list.html",
        {
            "request": request,
            "user": user,
            "vendors": vendors,
            "total": total,
            "q": q,
            "category": category,
            "city": city,
            "price_range": price_range,
            "cities": cities,
            "query_without_cat": qs_without_cat(),
            "query_with_cat": qs_with_cat,
            "venue_mode": False,
        },
    )


@router_pages.get("/venues", response_class=HTMLResponse)
async def venue_list(
    request: Request,
    db: DBSession,
    q: str | None = None,
    city: str | None = None,
    min_capacity: int | None = None,
    page: int = 1,
):
    """Venue discovery — a pre-filtered, location-first view of vendors in the
    "venue" category, so event planners can find a hall near their proposed
    event location without wading through the general vendor marketplace."""
    from sqlalchemy import distinct
    from sqlalchemy import select as _select

    from app.models.vendor import Vendor
    from app.services import vendor_service as vsvc

    user, orgs = await _get_auth_context(request, db)

    vendors, total = await vsvc.list_vendors(
        db, q=q, category="venue", city=city, min_capacity=min_capacity, page=page
    )

    city_rows = await db.scalars(
        _select(distinct(Vendor.location_city))
        .where(
            Vendor.location_city.isnot(None), Vendor.status == "active", Vendor.category == "venue"
        )
        .order_by(Vendor.location_city)
        .limit(50)
    )
    cities = [c for c in city_rows.all() if c]

    return templates.TemplateResponse(
        "vendors/list.html",
        {
            "request": request,
            "user": user,
            "vendors": vendors,
            "total": total,
            "q": q,
            "category": "venue",
            "city": city,
            "min_capacity": min_capacity,
            "price_range": None,
            "cities": cities,
            "query_without_cat": "",
            "query_with_cat": lambda cat: "",
            "venue_mode": True,
        },
    )


@router_pages.get("/vendors/{vendor_slug}", response_class=HTMLResponse)
async def vendor_detail(vendor_slug: str, request: Request, db: DBSession):
    from app.services import vendor_service as vsvc

    user, orgs = await _get_auth_context(request, db)
    vendor = await vsvc.get_vendor_by_slug(db, vendor_slug)
    if not vendor or vendor.status != "active":
        raise HTTPException(404, "Vendor not found.")

    primary_org = orgs[0]["org"] if orgs else None

    return templates.TemplateResponse(
        "vendors/detail.html",
        {
            "request": request,
            "user": user,
            "vendor": vendor,
            "org": primary_org,
        },
    )


@router_pages.get("/vendor-signup", response_class=HTMLResponse)
async def vendor_signup_page(request: Request, db: DBSession):
    from app.services import vendor_service as vsvc

    user, orgs = await _get_auth_context(request, db)

    if user:
        existing = await vsvc.get_vendor_by_user(db, user.id)
        if existing:
            return RedirectResponse(f"/vendors/{existing.slug}", status_code=302)

    return templates.TemplateResponse(
        "vendors/signup.html",
        {"request": request, "user": user},
    )


@router_pages.get("/org/{slug}/contacts", response_class=HTMLResponse)
async def org_contacts(
    slug: str,
    request: Request,
    db: DBSession,
    q: str = "",
    tag: str = "",
    page: int = 1,
):
    from sqlalchemy import func, or_, select

    from app.models.crm import Contact

    user, orgs, org, role, is_owner = await _org_page_ctx(request, db, slug)
    if not user:
        return RedirectResponse(f"/login?next=/org/{slug}/contacts", status_code=302)
    if not org or not role:
        raise HTTPException(403, "Access denied.")

    per_page = 50
    stmt = select(Contact).where(Contact.org_id == org.id)
    if q:
        stmt = stmt.where(
            or_(
                Contact.name.ilike(f"%{q}%"),
                Contact.email.ilike(f"%{q}%"),
            )
        )
    if tag:
        stmt = stmt.where(Contact.tags.contains([tag]))

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await db.scalars(
        stmt.order_by(Contact.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    contacts = list(rows.all())
    total_pages = max(1, (total + per_page - 1) // per_page)

    all_tags_rows = await db.scalars(
        select(Contact.tags).where(Contact.org_id == org.id, Contact.tags.isnot(None))
    )
    all_tags = sorted(set(t for tags in all_tags_rows.all() if tags for t in tags))

    onboarding = await org_svc.get_onboarding_state(db, org.id)
    sidebar_state = {
        "has_events": onboarding.has_event,
        "has_revenue": False,
        "has_registrations": False,
        "whatsapp_connected": onboarding.has_whatsapp,
    }
    import json

    orgs_json = json.dumps(
        [
            {
                "slug": e["org"].slug,
                "name": e["org"].name,
                "logo_url": e["org"].logo_url or "",
                "role": e["role"],
            }
            for e in orgs
        ]
    )
    return templates.TemplateResponse(
        "crm/contacts.html",
        {
            "request": request,
            "user": user,
            "org": org,
            "orgs": orgs,
            "orgs_json": orgs_json,
            "onboarding": onboarding,
            "sidebar_state": sidebar_state,
            "active_page": "contacts",
            "contacts": contacts,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "per_page": per_page,
            "q": q,
            "tag": tag,
            "all_tags": all_tags,
        },
    )


@router_pages.get("/speakers/{slug}", response_class=HTMLResponse)
async def public_speaker_profile(slug: str, request: Request, db: DBSession):
    from app.services import speaker_service as sp_svc

    user, _ = await _get_auth_context(request, db)

    speaker = await sp_svc.get_speaker_by_slug(db, slug)
    if not speaker:
        raise HTTPException(404, "Speaker not found.")

    events = await sp_svc.list_public_events_for_speaker(db, speaker.id)

    return templates.TemplateResponse(
        "speakers/profile.html",
        {
            "request": request,
            "user": user,
            "speaker": speaker,
            "events": events,
        },
    )


@router_pages.get("/sponsor-invite/{token}", response_class=HTMLResponse)
async def sponsor_invite_claim(token: str, request: Request, db: DBSession):
    import uuid as _uuid

    from app.services import sponsor_service as sp_svc

    user, _ = await _get_auth_context(request, db)

    payload = sp_svc.decode_sponsor_invite_token(token)
    sponsor = await sp_svc.get_sponsor_by_id(db, _uuid.UUID(payload["sponsor_id"]))
    if not sponsor:
        raise HTTPException(404, "Sponsor not found.")

    from app.models.event import Event

    event = await db.get(Event, sponsor.event_id)

    return templates.TemplateResponse(
        "sponsors/invite_claim.html",
        {
            "request": request,
            "user": user,
            "token": token,
            "sponsor": sponsor,
            "event": event,
        },
    )


@router_pages.get("/my-sponsorships", response_class=HTMLResponse)
async def my_sponsorships(request: Request, db: DBSession):
    from app.services import sponsor_service as sp_svc

    user, _ = await _get_auth_context(request, db)
    if not user:
        return RedirectResponse("/login?next=/my-sponsorships", status_code=302)

    sponsors = await sp_svc.list_my_sponsorships(db, user.id)

    from app.models.event import Event

    event_ids = {s.event_id for s in sponsors}
    events = {}
    if event_ids:
        from sqlalchemy import select

        rows = await db.scalars(select(Event).where(Event.id.in_(event_ids)))
        events = {e.id: e for e in rows.all()}

    return templates.TemplateResponse(
        "sponsors/my_sponsorships.html",
        {
            "request": request,
            "user": user,
            "sponsors": sponsors,
            "events": events,
        },
    )


@router_pages.get("/p/{username}", response_class=HTMLResponse)
async def public_user_profile(username: str, request: Request, db: DBSession):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.ticketing import Registration
    from app.models.user import User

    viewer, _ = await _get_auth_context(request, db)

    profile_user = await db.scalar(select(User).where(User.username == username))
    if not profile_user or profile_user.deleted_at is not None:
        raise HTTPException(404, "Profile not found.")

    regs = await db.scalars(
        select(Registration)
        .where(
            Registration.user_id == profile_user.id,
            Registration.status.in_(["confirmed", "checked_in"]),
        )
        .options(selectinload(Registration.event))
        .order_by(Registration.created_at.desc())
        .limit(12)
    )
    attended_regs = [r for r in regs.all() if r.event is not None]

    connection_status = None
    if viewer and viewer.id != profile_user.id:
        from app.services import connection_service as conn_svc

        connection_status = await conn_svc.connection_status(db, viewer.id, profile_user.id)

    return templates.TemplateResponse(
        "user/public_profile.html",
        {
            "request": request,
            "profile_user": profile_user,
            "user": viewer,
            "attended_regs": attended_regs,
            "connection_status": connection_status,
        },
    )


@router_pages.get("/messages", response_class=HTMLResponse)
async def messages_list(request: Request, db: DBSession):
    from app.services import message_service as msg_svc

    user, _ = await _get_auth_context(request, db)
    if not user:
        return RedirectResponse("/login?next=/messages", status_code=302)

    threads = await msg_svc.list_threads(db, user.id)

    from sqlalchemy import select

    from app.models.user import User

    enriched = []
    for t in threads:
        other = await db.scalar(select(User).where(User.id == t["other_user_id"]))
        if not other:
            continue
        enriched.append({**t, "other_user": other})

    return templates.TemplateResponse(
        "messages/list.html",
        {"request": request, "user": user, "threads": enriched},
    )


@router_pages.get("/messages/{other_user_id}", response_class=HTMLResponse)
async def messages_thread(other_user_id: str, request: Request, db: DBSession):
    import uuid as _uuid

    from sqlalchemy import select

    from app.models.user import User
    from app.services import connection_service as conn_svc
    from app.services import message_service as msg_svc

    user, _ = await _get_auth_context(request, db)
    if not user:
        return RedirectResponse(f"/login?next=/messages/{other_user_id}", status_code=302)

    try:
        other_id = _uuid.UUID(other_user_id)
    except ValueError as err:
        raise HTTPException(404, "User not found.") from err

    other_user = await db.scalar(select(User).where(User.id == other_id))
    if not other_user or other_user.deleted_at is not None:
        raise HTTPException(404, "User not found.")

    status = await conn_svc.connection_status(db, user.id, other_id)
    if status != "accepted":
        raise HTTPException(403, "You can only message people you're connected with.")

    threads = await msg_svc.list_threads(db, user.id)
    thread_users = {}
    for t in threads:
        u = await db.scalar(select(User).where(User.id == t["other_user_id"]))
        if u:
            thread_users[t["other_user_id"]] = u

    messages = await msg_svc.get_thread_messages(db, user.id, other_id)
    await msg_svc.mark_thread_read(db, user.id, other_id)

    return templates.TemplateResponse(
        "messages/thread.html",
        {
            "request": request,
            "user": user,
            "other_user": other_user,
            "messages": messages,
            "threads": threads,
            "thread_users": thread_users,
        },
    )


@router_pages.get("/my-vendor-profile", response_class=HTMLResponse)
async def my_vendor_profile(request: Request, db: DBSession):
    from app.services import vendor_service as vsvc

    user, orgs = await _get_auth_context(request, db)
    if not user:
        return RedirectResponse("/login?next=/my-vendor-profile", status_code=302)

    vendor = await vsvc.get_vendor_by_user(db, user.id)
    if not vendor:
        return RedirectResponse("/vendor-signup", status_code=302)

    return RedirectResponse(f"/vendors/{vendor.slug}", status_code=302)


@router_pages.get("/my-vendor-profile/leads", response_class=HTMLResponse)
async def my_vendor_leads(request: Request, db: DBSession):
    from app.services import vendor_service as vsvc

    user, orgs = await _get_auth_context(request, db)
    if not user:
        return RedirectResponse("/login?next=/my-vendor-profile/leads", status_code=302)

    vendor = await vsvc.get_vendor_by_user(db, user.id)
    if not vendor:
        return RedirectResponse("/vendor-signup", status_code=302)

    page = max(1, int(request.query_params.get("page", 1)))
    leads, total = await vsvc.get_vendor_leads(db, vendor.id, page=page)

    return templates.TemplateResponse(
        "vendors/leads.html",
        {
            "request": request,
            "user": user,
            "vendor": vendor,
            "leads": leads,
            "total": total,
            "page": page,
            "per_page": 20,
        },
    )
