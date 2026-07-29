"""Security headers middleware."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Alpine.js requires 'unsafe-eval'; HTMX + inline handlers require 'unsafe-inline'.
# Both are acceptable trade-offs when the alternative is no CSP at all.
# frame-ancestors and form-action still provide meaningful protection.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
    "https://cdn.jsdelivr.net https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: blob: https://media.heelo.io https://lh3.googleusercontent.com; "
    "connect-src 'self' wss: https://api.paystack.co https://api.flutterwave.com; "
    "worker-src 'self'; "
    "manifest-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self';"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security-relevant response headers not set by Nginx (e.g., CSP)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        # CSP is not set by nginx because it is content-specific
        response.headers.setdefault("Content-Security-Policy", _CSP)
        # Belt-and-suspenders: nginx already sets these, but set them here too
        # so they are present in direct-uvicorn deployments
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response
