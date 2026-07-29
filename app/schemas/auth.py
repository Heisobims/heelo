from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Shared ────────────────────────────────────────────────────────────────────
class UserOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    role: str
    is_verified: bool
    avatar_url: str | None
    username: str | None
    onboarding_completed: bool
    whatsapp_number: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


# ── Registration ──────────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=255, description="Your full name")
    email: EmailStr = Field(..., description="Work or personal email address")
    password: str = Field(..., min_length=8, max_length=128, description="At least 8 characters")

    @field_validator("full_name")
    @classmethod
    def name_no_special_chars(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be blank.")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        has_letter = any(c.isalpha() for c in v)
        has_digit = any(c.isdigit() for c in v)
        if not (has_letter and has_digit):
            raise ValueError("Password must contain at least one letter and one number.")
        return v


class RegisterResponse(BaseModel):
    message: str
    email: str


# ── OTP verification ──────────────────────────────────────────────────────────
class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class ResendOTPRequest(BaseModel):
    email: EmailStr


# ── Role selection (onboarding step 3) ───────────────────────────────────────
class SelectRoleRequest(BaseModel):
    role: Literal["organizer", "attendee", "both"]


# ── Login ─────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)
    remember_me: bool = False


# ── Token refresh ─────────────────────────────────────────────────────────────
class RefreshRequest(BaseModel):
    refresh_token: str


# ── Password reset ────────────────────────────────────────────────────────────
class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        has_letter = any(c.isalpha() for c in v)
        has_digit = any(c.isdigit() for c in v)
        if not (has_letter and has_digit):
            raise ValueError("Password must contain at least one letter and one number.")
        return v


# ── OAuth ─────────────────────────────────────────────────────────────────────
class OAuthUserInfo(BaseModel):
    provider: str
    provider_id: str
    email: str
    full_name: str
    avatar_url: str | None = None


# ── Me endpoint ───────────────────────────────────────────────────────────────
class MeResponse(BaseModel):
    user: UserOut
    orgs: list[dict] = []


class UpdateProfileRequest(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=255)
    username: str | None = Field(None, min_length=2, max_length=50, pattern=r"^[a-z0-9_]+$")
    whatsapp_number: str | None = Field(None, max_length=30)

    @field_validator("full_name")
    @classmethod
    def strip_name(cls, v: str | None) -> str | None:
        return v.strip() if v else v


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        has_letter = any(c.isalpha() for c in v)
        has_digit = any(c.isdigit() for c in v)
        if not (has_letter and has_digit):
            raise ValueError("Password must contain at least one letter and one number.")
        return v
