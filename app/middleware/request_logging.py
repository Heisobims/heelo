"""Structured request/response logging middleware."""

from __future__ import annotations

import time

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger()

# Don't spam logs with health check noise
_SKIP_PATHS = {"/health", "/favicon.ico"}


class RequestLoggingMiddleware:
    """
    Pure ASGI (not BaseHTTPMiddleware) - BaseHTTPMiddleware runs the downstream
    app in a separate anyio task, which breaks anything that depends on
    request-scoped async context being on the same task (e.g. a test suite
    sharing one AsyncSession/event-loop context across the request).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in _SKIP_PATHS:
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        await self.app(scope, receive, send_wrapper)

        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        request_headers = dict(scope.get("headers") or [])
        forwarded_for = request_headers.get(b"x-forwarded-for")
        client = scope.get("client")
        ip = forwarded_for.decode("latin-1") if forwarded_for else (client[0] if client else "-")

        log = logger.bind(
            method=scope["method"],
            path=scope["path"],
            status=status_code,
            duration_ms=duration_ms,
            ip=ip,
        )

        if status_code >= 500:
            log.error("http.request")
        elif status_code >= 400:
            log.warning("http.request")
        else:
            log.info("http.request")
