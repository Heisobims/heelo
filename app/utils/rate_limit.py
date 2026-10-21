"""Generic Redis-backed rate limiter for public, unauthenticated endpoints
(registration, OTP resend, vendor contact forms) that can be spammed to
mass-trigger outbound email/SMS or flood a table. Same fail-open convention
as the login limiter in app/services/auth_service.py: if Redis isn't
reachable, requests pass through rather than breaking the endpoint."""

from __future__ import annotations

import structlog
from fastapi import HTTPException, Request, status

from app.config import settings

logger = structlog.get_logger()

_DEFAULT_MESSAGE = "Too many requests. Please try again later."


def _redis():
    try:
        from redis import Redis as _Redis

        return _Redis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception:
        return None


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_and_record(
    key: str,
    *,
    max_attempts: int,
    window_seconds: int,
    error_message: str = _DEFAULT_MESSAGE,
) -> None:
    """Increment `key`'s counter and raise 429 once it exceeds max_attempts
    within the window. Unlike the login limiter (which only records failed
    attempts), this records every call - the thing being throttled here is
    volume of outbound sends/submissions, not failed auth."""
    redis = _redis()
    if not redis:
        return
    try:
        count = redis.incr(key)
        if count == 1:
            redis.expire(key, window_seconds)
        if count > max_attempts:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=error_message)
    except HTTPException:
        raise
    except Exception as err:
        logger.warning("rate_limit.check_failed", key=key, error=str(err))
