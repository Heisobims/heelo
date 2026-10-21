from __future__ import annotations

import urllib.parse
from datetime import UTC
from typing import Annotated

import structlog
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import CurrentUserID
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResendOTPRequest,
    ResetPasswordRequest,
    SelectRoleRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserOut,
    VerifyOTPRequest,
)
from app.services.auth_service import AuthService
from app.utils.rate_limit import check_and_record, get_client_ip

logger = structlog.get_logger()

# Registration/OTP-resend can be spammed to mass-trigger email/SMS at an
# arbitrary target address - throttle both per-email (targeted abuse) and
# per-IP (volume abuse), same defense-in-depth convention as login.
_REGISTER_MAX_PER_EMAIL = 5
_REGISTER_MAX_PER_IP = 20
_REGISTER_WINDOW_SECONDS = 60 * 60

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["settings"] = settings

# ── Two routers: API (JSON) + Pages (HTML) ────────────────────────────────────
router_api = APIRouter(prefix="/api/v1/auth", tags=["Auth"])
router_pages = APIRouter(tags=["Auth Pages"])

_COOKIE_ACCESS = "heelo_access"
_COOKIE_REFRESH = "heelo_refresh"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def _set_auth_cookies(response: Response, tokens: TokenResponse) -> None:
    response.set_cookie(
        _COOKIE_ACCESS,
        tokens.access_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=60 * settings.ACCESS_TOKEN_EXPIRE_MINUTES,
    )
    response.set_cookie(
        _COOKIE_REFRESH,
        tokens.refresh_token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=_COOKIE_MAX_AGE,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(_COOKIE_ACCESS)
    response.delete_cookie(_COOKIE_REFRESH)


# ── HTML page routes ──────────────────────────────────────────────────────────
@router_pages.get("/register", response_class=HTMLResponse, include_in_schema=False)
async def page_register(request: Request, next: str | None = None):
    """Registration Step 1 - name, email, password.
    If already logged in, redirect to next (or /dashboard) to prevent loop.
    """
    token = request.cookies.get(_COOKIE_ACCESS)
    if token:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            if payload.get("sub"):
                target = next if (next and next.startswith("/") and not next.startswith("//")) else "/dashboard"
                return RedirectResponse(target, status_code=302)
        except Exception:
            pass
    return templates.TemplateResponse(request, "auth/register.html")


@router_pages.get("/verify", response_class=HTMLResponse, include_in_schema=False)
async def page_verify(request: Request, email: str = ""):
    """Registration Step 2 - 6-digit OTP input."""
    return templates.TemplateResponse(request, "auth/verify.html", {"email": email})


@router_pages.get("/onboarding/role", response_class=HTMLResponse, include_in_schema=False)
async def page_role(request: Request):
    """Registration Step 3 - role selection."""
    return templates.TemplateResponse(request, "auth/role.html")


@router_pages.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def page_login(request: Request, next: str | None = None):
    """Login page.
    If already logged in, redirect to next (or /dashboard).
    """
    token = request.cookies.get(_COOKIE_ACCESS)
    if token:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            if payload.get("sub"):
                target = next if (next and next.startswith("/") and not next.startswith("//")) else "/dashboard"
                return RedirectResponse(target, status_code=302)
        except Exception:
            pass
    return templates.TemplateResponse(request, "auth/login.html")


@router_pages.get("/forgot-password", response_class=HTMLResponse, include_in_schema=False)
async def page_forgot_password(request: Request):
    return templates.TemplateResponse(request, "auth/forgot_password.html")


@router_pages.get("/reset-password/{token}", response_class=HTMLResponse, include_in_schema=False)
async def page_reset_password(request: Request, token: str):
    return templates.TemplateResponse(request, "auth/reset_password.html", {"token": token})


# ── API: Registration ─────────────────────────────────────────────────────────
@router_api.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
)
async def register(
    request: Request,
    data: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new unverified user and send a 6-digit OTP to their email.
    The user must verify the OTP via `/auth/verify-otp` before they can log in.
    """
    check_and_record(
        f"register_attempts:email:{data.email.lower()}",
        max_attempts=_REGISTER_MAX_PER_EMAIL,
        window_seconds=_REGISTER_WINDOW_SECONDS,
        error_message="Too many attempts for this email. Please try again in an hour.",
    )
    check_and_record(
        f"register_attempts:ip:{get_client_ip(request)}",
        max_attempts=_REGISTER_MAX_PER_IP,
        window_seconds=_REGISTER_WINDOW_SECONDS,
        error_message="Too many attempts. Please try again in an hour.",
    )
    svc = AuthService(db)
    result = await svc.register(data)
    return result


@router_api.post(
    "/verify-otp",
    response_model=TokenResponse,
    summary="Verify email with OTP",
)
async def verify_otp(
    data: VerifyOTPRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Verify the 6-digit OTP sent to the user's email.
    On success, marks the account as verified and returns JWT tokens.
    Tokens are also set as httpOnly cookies for browser clients.
    """
    svc = AuthService(db)
    tokens = await svc.verify_otp(data)
    _set_auth_cookies(response, tokens)
    return tokens


@router_api.post("/resend-otp", status_code=status.HTTP_204_NO_CONTENT, summary="Resend OTP")
async def resend_otp(request: Request, data: ResendOTPRequest, db: AsyncSession = Depends(get_db)):
    """Invalidate the previous OTP and send a fresh one."""
    check_and_record(
        f"register_attempts:email:{data.email.lower()}",
        max_attempts=_REGISTER_MAX_PER_EMAIL,
        window_seconds=_REGISTER_WINDOW_SECONDS,
        error_message="Too many attempts for this email. Please try again in an hour.",
    )
    check_and_record(
        f"register_attempts:ip:{get_client_ip(request)}",
        max_attempts=_REGISTER_MAX_PER_IP,
        window_seconds=_REGISTER_WINDOW_SECONDS,
        error_message="Too many attempts. Please try again in an hour.",
    )
    await AuthService(db).resend_otp(data.email)


@router_api.post("/select-role", response_model=UserOut, summary="Set account role (onboarding)")
async def select_role(
    data: SelectRoleRequest,
    current_user_id: CurrentUserID,
    db: AsyncSession = Depends(get_db),
):
    """Set the user's primary role after OTP verification. Step 3 of onboarding."""
    return await AuthService(db).select_role(current_user_id, data)


# ── API: Login / Logout ───────────────────────────────────────────────────────
@router_api.post("/login", response_model=TokenResponse, summary="Log in with email & password")
async def login(
    data: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate with email and password. Returns JWT access + refresh tokens."""
    svc = AuthService(db)
    tokens = await svc.login(data)
    _set_auth_cookies(response, tokens)
    return tokens


@router_api.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Log out")
async def logout(
    response: Response,
    db: AsyncSession = Depends(get_db),
    heelo_refresh: Annotated[str | None, Cookie()] = None,
):
    """Revoke the refresh token and clear auth cookies."""
    if heelo_refresh:
        await AuthService(db).logout(heelo_refresh)
    _clear_auth_cookies(response)


@router_api.post("/refresh", response_model=TokenResponse, summary="Refresh access token")
async def refresh_tokens(
    response: Response,
    db: AsyncSession = Depends(get_db),
    heelo_refresh: Annotated[str | None, Cookie()] = None,
    body: RefreshRequest | None = None,
):
    """
    Issue a new access token using the refresh token.
    Accepts the token from the `heelo_refresh` cookie (browser) or the request body (API clients).
    Implements token rotation - the old refresh token is revoked and a new one is issued.
    """
    raw = (heelo_refresh or "") if heelo_refresh else (body.refresh_token if body else "")
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token provided."
        )
    svc = AuthService(db)
    tokens = await svc.refresh_tokens(raw)
    _set_auth_cookies(response, tokens)
    return tokens


# ── API: OAuth ────────────────────────────────────────────────────────────────
@router_api.get("/google", include_in_schema=False)
async def google_redirect():
    """Redirect browser to Google OAuth consent screen."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Google OAuth not configured.")
    redirect_uri = f"{settings.FRONTEND_URL}/api/v1/auth/google/callback"
    params = urllib.parse.urlencode(
        {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
        }
    )
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@router_api.get("/google/callback", include_in_schema=False)
async def google_callback(
    code: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Handle Google OAuth callback, find or create user, set cookies, redirect."""
    redirect_uri = f"{settings.FRONTEND_URL}/api/v1/auth/google/callback"
    svc = AuthService(db)
    info = await svc.exchange_google_code(code, redirect_uri)
    tokens = await svc.handle_oauth(info)
    redirect = RedirectResponse(
        url=(
            "/onboarding/role"
            if not tokens.user.role or tokens.user.role == "attendee"
            else "/dashboard"
        )
    )
    _set_auth_cookies(redirect, tokens)
    return redirect


@router_api.get("/facebook", include_in_schema=False)
async def facebook_redirect():
    """Redirect browser to Facebook OAuth dialog."""
    if not settings.FACEBOOK_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Facebook OAuth not configured.")
    redirect_uri = f"{settings.FRONTEND_URL}/api/v1/auth/facebook/callback"
    params = urllib.parse.urlencode(
        {
            "client_id": settings.FACEBOOK_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": "email,public_profile",
        }
    )
    return RedirectResponse(f"https://www.facebook.com/v18.0/dialog/oauth?{params}")


@router_api.get("/facebook/callback", include_in_schema=False)
async def facebook_callback(
    code: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    redirect_uri = f"{settings.FRONTEND_URL}/api/v1/auth/facebook/callback"
    svc = AuthService(db)
    info = await svc.exchange_facebook_code(code, redirect_uri)
    tokens = await svc.handle_oauth(info)
    redirect = RedirectResponse(url="/onboarding/role")
    _set_auth_cookies(redirect, tokens)
    return redirect


# ── API: Password reset ───────────────────────────────────────────────────────
@router_api.post(
    "/forgot-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Request password reset email",
)
async def forgot_password(data: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """
    Send a password reset link. Always returns 204 regardless of whether the
    email exists - prevents email enumeration.
    """
    await AuthService(db).forgot_password(data)


@router_api.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Reset password with token",
)
async def reset_password(data: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Validate the reset token and update the user's password."""
    await AuthService(db).reset_password(data)


# ── API: Me ───────────────────────────────────────────────────────────────────
@router_api.get("/me", response_model=UserOut, summary="Get current user")
async def me(
    current_user_id: CurrentUserID,
    db: AsyncSession = Depends(get_db),
    heelo_access: Annotated[str | None, Cookie()] = None,
):
    """Return the authenticated user's profile."""
    from sqlalchemy import select

    from app.models.user import User

    user = await db.scalar(select(User).where(User.id == current_user_id))  # type: ignore[arg-type]
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return UserOut.model_validate(user)


@router_api.patch("/me", response_model=UserOut, summary="Update profile")
async def update_me(
    body: UpdateProfileRequest,
    current_user_id: CurrentUserID,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select

    from app.models.user import User

    user = await db.scalar(select(User).where(User.id == current_user_id))
    if not user:
        raise HTTPException(404, "User not found.")

    if body.full_name is not None:
        user.full_name = body.full_name
    if body.username is not None:
        taken = await db.scalar(
            select(User.id).where(User.username == body.username, User.id != user.id)
        )
        if taken:
            raise HTTPException(409, "That username is already taken.")
        user.username = body.username or None
    if body.whatsapp_number is not None:
        user.whatsapp_number = body.whatsapp_number or None
    if body.avatar_url is not None:
        user.avatar_url = body.avatar_url or None
    if body.country is not None:
        user.country = body.country or None
    if body.birth_year is not None:
        user.birth_year = body.birth_year

    return UserOut.model_validate(user)


@router_api.post("/me/password", status_code=204, summary="Change password")
async def change_password(
    body: ChangePasswordRequest,
    current_user_id: CurrentUserID,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select

    from app.models.user import User
    from app.utils.auth import hash_password, verify_password

    user = await db.scalar(select(User).where(User.id == current_user_id))
    if not user:
        raise HTTPException(404, "User not found.")
    if not user.password_hash:
        raise HTTPException(400, "Password change is not available for social login accounts.")
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect.")

    user.password_hash = hash_password(body.new_password)


@router_api.post("/me/avatar", summary="Upload profile photo")
async def upload_avatar(
    current_user_id: CurrentUserID,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    from sqlalchemy import select

    from app.models.user import User
    from app.utils import storage

    user = await db.scalar(select(User).where(User.id == current_user_id))
    if not user:
        raise HTTPException(404, "User not found.")

    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "Avatar must be under 5 MB.")
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(422, "Only JPEG, PNG, or WebP images are supported.")

    url = await storage.upload_image(
        data,
        folder=f"users/{user.id}/avatar",
        filename=None,
        max_width=400,
        quality=85,
    )
    user.avatar_url = url
    await db.commit()
    return {"success": True, "avatar_url": url}


# ── API: Notifications (activity feed) ───────────────────────────────────────
@router_api.get("/me/notifications", summary="Recent activity notifications")
async def get_notifications(
    current_user_id: CurrentUserID,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the 20 most recent activity items relevant to this user:
    - New registrations on their org events (for organizers)
    - Their own confirmed registrations (for attendees)
    Keyed by type so the client can render appropriate icons.
    """
    import uuid as _uuid

    from sqlalchemy import desc, select

    from app.models.event import Event
    from app.models.organization import OrganizationMember
    from app.models.ticketing import Registration
    from app.models.user import User

    uid = _uuid.UUID(str(current_user_id))
    user = await db.scalar(select(User).where(User.id == uid))
    if not user:
        raise HTTPException(404, "User not found.")

    items: list[dict] = []

    # Org events: show new registrations for events this user organizes
    member_rows = await db.scalars(
        select(OrganizationMember).where(
            OrganizationMember.user_id == uid,
            OrganizationMember.status == "active",
        )
    )
    org_ids = [m.org_id for m in member_rows.all()]

    if org_ids:
        event_ids_rows = await db.scalars(select(Event.id).where(Event.org_id.in_(org_ids)))
        event_ids = list(event_ids_rows.all())

        if event_ids:
            regs = await db.scalars(
                select(Registration)
                .where(
                    Registration.event_id.in_(event_ids),
                    Registration.status == "confirmed",
                )
                .order_by(desc(Registration.created_at))
                .limit(10)
            )
            for r in regs.all():
                items.append(
                    {
                        "type": "registration",
                        "icon": "how_to_reg",
                        "title": f"{r.attendee_name} registered",
                        "body": r.attendee_email,
                        "ts": (
                            r.created_at.replace(tzinfo=UTC).isoformat() if r.created_at else None
                        ),
                        "url": None,
                    }
                )

    # Attendee: show their own confirmed registrations
    my_regs = await db.scalars(
        select(Registration)
        .where(
            Registration.user_id == uid,
            Registration.status == "confirmed",
        )
        .order_by(desc(Registration.created_at))
        .limit(10)
    )
    for r in my_regs.all():
        items.append(
            {
                "type": "ticket",
                "icon": "confirmation_number",
                "title": "Ticket confirmed",
                "body": r.attendee_name,
                "ts": (r.created_at.replace(tzinfo=UTC).isoformat() if r.created_at else None),
                "url": "/my-tickets",
            }
        )

    # Real notification rows (e.g. connection requests/accepts) - unread first
    from app.models.notification import Notification

    notif_rows = await db.scalars(
        select(Notification)
        .where(Notification.user_id == uid, Notification.is_read == False)
        .order_by(desc(Notification.created_at))
        .limit(10)
    )
    for n in notif_rows.all():
        items.append(
            {
                "type": n.type,
                "icon": n.icon or "notifications",
                "title": n.title,
                "body": n.body,
                "ts": n.created_at.replace(tzinfo=UTC).isoformat() if n.created_at else None,
                "url": n.action_url,
            }
        )

    # Sort all items by ts desc, take top 20
    items.sort(key=lambda x: x["ts"] or "", reverse=True)
    return {"notifications": items[:20]}
