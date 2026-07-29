from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import OTPCode, PasswordResetToken, RefreshToken, User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    OAuthUserInfo,
    RegisterRequest,
    ResetPasswordRequest,
    SelectRoleRequest,
    TokenResponse,
    UserOut,
    VerifyOTPRequest,
)
from app.utils.auth import (
    create_access_token,
    create_raw_refresh_token,
    generate_otp,
    hash_otp,
    hash_token,
    hash_password,
    verify_otp_hash,
    verify_password,
)
from app.utils.email import (
    send_otp_email,
    send_password_reset_email,
    send_welcome_email,
)

logger = structlog.get_logger()

_MAX_OTP_ATTEMPTS = 5


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Registration ──────────────────────────────────────────────────────────
    async def register(self, data: RegisterRequest) -> dict:
        """Create an unverified user and send an OTP to their email."""
        existing = await self.db.scalar(
            select(User).where(User.email == data.email.lower(), User.deleted_at.is_(None))
        )
        if existing and existing.is_verified:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            )

        if existing and not existing.is_verified:
            # Re-send OTP for unverified account instead of creating a duplicate
            user = existing
            user.full_name = data.full_name
            user.password_hash = hash_password(data.password)
        else:
            user = User(
                full_name=data.full_name,
                email=data.email.lower(),
                password_hash=hash_password(data.password),
                role="attendee",
                is_verified=False,
            )
            self.db.add(user)

        await self.db.flush()
        await self._create_and_send_otp(data.email.lower(), data.full_name)
        logger.info("auth.register", email=data.email)
        return {"message": "Check your inbox for a 6-digit code.", "email": data.email.lower()}

    # ── OTP ───────────────────────────────────────────────────────────────────
    async def _create_and_send_otp(self, email: str, name: str) -> None:
        otp = generate_otp()
        # Invalidate any previous unused OTPs for this email+purpose
        await self.db.execute(
            update(OTPCode)
            .where(OTPCode.email == email, OTPCode.purpose == "email_verification", OTPCode.used_at.is_(None))
            .values(used_at=datetime.now(tz=timezone.utc))
        )
        record = OTPCode(
            email=email,
            code_hash=hash_otp(otp),
            purpose="email_verification",
            expires_at=datetime.now(tz=timezone.utc) + timedelta(minutes=settings.OTP_EXPIRE_MINUTES),
        )
        self.db.add(record)
        await self.db.flush()
        send_otp_email(email, name, otp)

    async def verify_otp(self, data: VerifyOTPRequest) -> TokenResponse:
        """Verify the 6-digit OTP, mark user as verified, return tokens."""
        otp_record = await self.db.scalar(
            select(OTPCode)
            .where(
                OTPCode.email == data.email.lower(),
                OTPCode.purpose == "email_verification",
                OTPCode.used_at.is_(None),
                OTPCode.expires_at > datetime.now(tz=timezone.utc),
            )
            .order_by(OTPCode.created_at.desc())
        )
        if not otp_record:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Code expired or already used. Request a new one.",
            )

        otp_record.attempts += 1
        if otp_record.attempts > _MAX_OTP_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Please request a new code.",
            )

        if not verify_otp_hash(data.otp, otp_record.code_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Incorrect code. Check your inbox and try again.",
            )

        otp_record.used_at = datetime.now(tz=timezone.utc)

        user = await self.db.scalar(
            select(User).where(User.email == data.email.lower(), User.deleted_at.is_(None))
        )
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")

        user.is_verified = True
        await self.db.flush()

        send_welcome_email(user.email, user.full_name)
        logger.info("auth.verified", user_id=str(user.id))
        return await self._issue_tokens(user)

    async def resend_otp(self, email: str) -> None:
        user = await self.db.scalar(
            select(User).where(User.email == email.lower(), User.deleted_at.is_(None))
        )
        if not user:
            return  # Silent — don't reveal whether account exists
        await self._create_and_send_otp(email.lower(), user.full_name)
        logger.info("auth.otp_resent", email=email)

    # ── Role selection ────────────────────────────────────────────────────────
    async def select_role(self, user_id: str, data: SelectRoleRequest) -> UserOut:
        user = await self._get_user_or_404(user_id)
        user.role = data.role
        await self.db.flush()
        logger.info("auth.role_selected", user_id=user_id, role=data.role)
        return UserOut.model_validate(user)

    # ── Login ─────────────────────────────────────────────────────────────────
    async def login(self, data: LoginRequest) -> TokenResponse:
        user = await self.db.scalar(
            select(User).where(User.email == data.email.lower(), User.deleted_at.is_(None))
        )
        invalid_exc = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
        if not user or not user.password_hash:
            raise invalid_exc
        if not verify_password(data.password, user.password_hash):
            raise invalid_exc
        if not user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Please verify your email first.",
            )

        user.last_seen_at = datetime.now(tz=timezone.utc)
        logger.info("auth.login", user_id=str(user.id))
        return await self._issue_tokens(user, long_lived=data.remember_me)

    # ── Token refresh ─────────────────────────────────────────────────────────
    async def refresh_tokens(self, raw_refresh_token: str) -> TokenResponse:
        token_hash = hash_token(raw_refresh_token)
        record = await self.db.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > datetime.now(tz=timezone.utc),
            )
        )
        if not record:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token invalid or expired. Please log in again.",
            )

        # Rotate: revoke old, issue new
        record.revoked_at = datetime.now(tz=timezone.utc)
        user = await self._get_user_or_404(str(record.user_id))
        return await self._issue_tokens(user)

    # ── Logout ────────────────────────────────────────────────────────────────
    async def logout(self, raw_refresh_token: str) -> None:
        token_hash = hash_token(raw_refresh_token)
        record = await self.db.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        if record:
            record.revoked_at = datetime.now(tz=timezone.utc)

    # ── Password reset ────────────────────────────────────────────────────────
    async def forgot_password(self, data: ForgotPasswordRequest) -> None:
        user = await self.db.scalar(
            select(User).where(User.email == data.email.lower(), User.deleted_at.is_(None))
        )
        if not user:
            return  # Silent — don't reveal existence

        raw_token = secrets.token_urlsafe(48)
        record = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(tz=timezone.utc) + timedelta(hours=1),
        )
        self.db.add(record)
        await self.db.flush()

        reset_url = f"{settings.FRONTEND_URL}/reset-password/{raw_token}"
        send_password_reset_email(user.email, user.full_name, reset_url)
        logger.info("auth.password_reset_requested", user_id=str(user.id))

    async def reset_password(self, data: ResetPasswordRequest) -> None:
        token_hash = hash_token(data.token)
        record = await self.db.scalar(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > datetime.now(tz=timezone.utc),
            )
        )
        if not record:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This reset link is invalid or has expired.",
            )

        user = await self._get_user_or_404(str(record.user_id))
        user.password_hash = hash_password(data.new_password)
        record.used_at = datetime.now(tz=timezone.utc)

        # Revoke all refresh tokens for security
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(tz=timezone.utc))
        )
        logger.info("auth.password_reset", user_id=str(user.id))

    # ── OAuth ─────────────────────────────────────────────────────────────────
    async def handle_oauth(self, info: OAuthUserInfo) -> TokenResponse:
        """Find or create a user from OAuth provider data, return tokens."""
        # Try by provider ID first (most reliable)
        user = await self.db.scalar(
            select(User).where(
                User.oauth_provider == info.provider,
                User.oauth_id == info.provider_id,
                User.deleted_at.is_(None),
            )
        )
        if not user:
            # Fall back to matching by email — links OAuth to existing account
            user = await self.db.scalar(
                select(User).where(User.email == info.email.lower(), User.deleted_at.is_(None))
            )

        if user:
            # Update OAuth linkage if this is a new provider for existing account
            if not user.oauth_provider:
                user.oauth_provider = info.provider
                user.oauth_id = info.provider_id
            if not user.avatar_url and info.avatar_url:
                user.avatar_url = info.avatar_url
            user.is_verified = True
        else:
            user = User(
                full_name=info.full_name,
                email=info.email.lower(),
                avatar_url=info.avatar_url,
                oauth_provider=info.provider,
                oauth_id=info.provider_id,
                is_verified=True,
                role="attendee",
            )
            self.db.add(user)
            await self.db.flush()
            send_welcome_email(user.email, user.full_name)

        user.last_seen_at = datetime.now(tz=timezone.utc)
        logger.info("auth.oauth", provider=info.provider, user_id=str(user.id))
        return await self._issue_tokens(user)

    async def exchange_google_code(self, code: str, redirect_uri: str) -> OAuthUserInfo:
        async with httpx.AsyncClient() as client:
            token_res = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            token_res.raise_for_status()
            access_token = token_res.json()["access_token"]

            user_res = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            user_res.raise_for_status()
            data = user_res.json()

        return OAuthUserInfo(
            provider="google",
            provider_id=data["id"],
            email=data["email"],
            full_name=data.get("name", ""),
            avatar_url=data.get("picture"),
        )

    async def exchange_facebook_code(self, code: str, redirect_uri: str) -> OAuthUserInfo:
        async with httpx.AsyncClient() as client:
            token_res = await client.get(
                "https://graph.facebook.com/v18.0/oauth/access_token",
                params={
                    "client_id": settings.FACEBOOK_CLIENT_ID,
                    "client_secret": settings.FACEBOOK_CLIENT_SECRET,
                    "redirect_uri": redirect_uri,
                    "code": code,
                },
            )
            token_res.raise_for_status()
            access_token = token_res.json()["access_token"]

            user_res = await client.get(
                "https://graph.facebook.com/me",
                params={"fields": "id,name,email,picture", "access_token": access_token},
            )
            user_res.raise_for_status()
            data = user_res.json()

        return OAuthUserInfo(
            provider="facebook",
            provider_id=data["id"],
            email=data.get("email", ""),
            full_name=data.get("name", ""),
            avatar_url=data.get("picture", {}).get("data", {}).get("url"),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────
    async def _issue_tokens(self, user: User, long_lived: bool = False) -> TokenResponse:
        access_token = create_access_token(str(user.id), user.role)
        raw_refresh = create_raw_refresh_token()

        days = settings.REFRESH_TOKEN_EXPIRE_DAYS * 3 if long_lived else settings.REFRESH_TOKEN_EXPIRE_DAYS
        record = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=datetime.now(tz=timezone.utc) + timedelta(days=days),
        )
        self.db.add(record)
        await self.db.flush()

        return TokenResponse(
            access_token=access_token,
            refresh_token=raw_refresh,
            user=UserOut.model_validate(user),
        )

    async def _get_user_or_404(self, user_id: str) -> User:
        user = await self.db.scalar(
            select(User).where(User.id == uuid.UUID(user_id), User.deleted_at.is_(None))
        )
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        return user
