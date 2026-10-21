"""Security headers middleware."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Alpine.js requires 'unsafe-eval'; HTMX + inline handlers require 'unsafe-inline'.
# Both are acceptable trade-offs when the alternative is no CSP at all.
# frame-ancestors and form-action still provide meaningful protection.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
    "https://cdn.jsdelivr.net https://unpkg.com https://www.googletagmanager.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
    "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
    "img-src 'self' data: blob: https://media.heelo.io https://lh3.googleusercontent.com "
    "https://images.unsplash.com https://unsplash.com https://*.unsplash.com "
    "https://www.google-analytics.com https://*.google-analytics.com; "
    "connect-src 'self' wss: https://api.paystack.co https://api.flutterwave.com "
    "https://www.google-analytics.com https://*.google-analytics.com https://*.analytics.google.com; "
    "worker-src 'self'; "
    "manifest-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self';"
)


class SecurityHeadersMiddleware:
    """
    Adds security-relevant response headers not set by Nginx (e.g., CSP).

    Pure ASGI (not BaseHTTPMiddleware) - BaseHTTPMiddleware runs the downstream
    app in a separate anyio task, which breaks anything that depends on
    request-scoped async context being on the same task (e.g. a test suite
    sharing one AsyncSession/event-loop context across the request).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        is_embeddable = path.endswith("/widget")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("Content-Security-Policy", _CSP)
                # Belt-and-suspenders: nginx already sets these, but set them here
                # too so they are present in direct-uvicorn deployments
                headers.setdefault("X-Content-Type-Options", "nosniff")
                if not is_embeddable:
                    headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            await send(message)

        await self.app(scope, receive, send_wrapper)
