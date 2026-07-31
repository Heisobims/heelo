from __future__ import annotations

import hashlib
import hmac
import secrets
import string
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt as _bcrypt
from jose import jwt

from app.config import settings

# ── Password hashing ──────────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── JWT ───────────────────────────────────────────────────────────────────────
def create_access_token(user_id: str, role: str, extra: dict[str, Any] | None = None) -> str:
    """Create a short-lived JWT access token."""
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises JWTError on failure."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def create_raw_refresh_token() -> str:
    """Return a cryptographically secure 64-byte hex token (stored hashed in DB)."""
    return secrets.token_hex(64)


def hash_token(raw: str) -> str:
    """SHA-256 hash of any raw token string — used for refresh & reset tokens."""
    return hashlib.sha256(raw.encode()).hexdigest()


# ── OTP ───────────────────────────────────────────────────────────────────────
def generate_otp() -> str:
    """6-digit numeric OTP."""
    return "".join(secrets.choice(string.digits) for _ in range(6))


def hash_otp(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()


def verify_otp_hash(plain: str, stored_hash: str) -> bool:
    return hmac.compare_digest(
        hashlib.sha256(plain.encode()).hexdigest(),
        stored_hash,
    )


# ── API key generation ────────────────────────────────────────────────────────
def generate_api_key() -> tuple[str, str, str]:
    """
    Returns (raw_key, key_hash, key_prefix).
    raw_key is shown once. key_hash is stored. key_prefix shown in UI.
    """
    raw = f"hlo_live_{secrets.token_urlsafe(32)}"
    prefix = raw[:16] + "..."
    return raw, hash_token(raw), prefix


# ── Ticket QR JWT ─────────────────────────────────────────────────────────────
def create_ticket_qr_token(registration_id: str, event_id: str) -> str:
    """Signed JWT embedded in QR codes — verified at check-in."""
    payload = {
        "type": "ticket",
        "rid": registration_id,
        "eid": event_id,
        "iat": datetime.now(tz=UTC),
    }
    # No expiry — tickets are valid until the event ends (enforced at check-in)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_ticket_qr_token(token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
        options={"verify_exp": False},
    )


def create_unsubscribe_token(org_id: str, email: str) -> str:
    """Signed, no-login-required link embedded in campaign email footers."""
    payload = {
        "type": "unsubscribe",
        "org_id": org_id,
        "email": email.lower(),
        "iat": datetime.now(tz=UTC),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_unsubscribe_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
        options={"verify_exp": False},
    )
    if payload.get("type") != "unsubscribe":
        raise ValueError("Invalid unsubscribe token.")
    return payload
