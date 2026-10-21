"""Minimal Redis cache-aside helper for hot, public read paths (the landing
page's event showcase, dashboard analytics summaries). Same fail-open
convention as app/utils/rate_limit.py - a cache miss (including "Redis is
unreachable") just means the caller falls through to the real query, never
a hard failure."""

from __future__ import annotations

import structlog

from app.config import settings

logger = structlog.get_logger()


def _redis():
    try:
        from redis import Redis as _Redis

        return _Redis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception:
        return None


def cache_get(key: str) -> str | None:
    redis = _redis()
    if not redis:
        return None
    try:
        return redis.get(key)
    except Exception as err:
        logger.warning("cache.get_failed", key=key, error=str(err))
        return None


def cache_set(key: str, value: str, *, ttl_seconds: int) -> None:
    redis = _redis()
    if not redis:
        return
    try:
        redis.set(key, value, ex=ttl_seconds)
    except Exception as err:
        logger.warning("cache.set_failed", key=key, error=str(err))
