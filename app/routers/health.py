from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db

logger = structlog.get_logger()
router = APIRouter(tags=["Health"])


async def _ping_redis() -> bool:
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
        return True
    except Exception as exc:
        logger.warning("health.redis_error", error=str(exc), url=settings.REDIS_URL)
        return False


@router.get("/health", summary="Health check")
async def health_check(db: AsyncSession = Depends(get_db)) -> dict:
    checks: dict[str, str] = {}

    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        logger.warning("health.db_error", error=str(exc))
        checks["database"] = "error"

    checks["redis"] = "ok" if await _ping_redis() else "error"

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "service": "heelo",
        "checks": checks,
    }


