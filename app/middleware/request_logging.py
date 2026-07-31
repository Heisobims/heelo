"""Structured request/response logging middleware."""

from __future__ import annotations

import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger()

# Don't spam logs with health check noise
_SKIP_PATHS = {"/health", "/favicon.ico"}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)

        log = logger.bind(
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
            ip=request.headers.get(
                "X-Forwarded-For", request.client.host if request.client else "-"
            ),
        )

        if response.status_code >= 500:
            log.error("http.request")
        elif response.status_code >= 400:
            log.warning("http.request")
        else:
            log.info("http.request")

        return response
