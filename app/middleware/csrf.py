"""CSRF protection for cookie-authenticated browser requests.

The dashboard is a server-rendered app where nearly all mutating requests
are issued by the browser as fetch()/HTMX calls authenticating purely via
the httpOnly `heelo_access` session cookie (see app/dependencies.py's
_resolve_token - browser clients never send an explicit Authorization
header, the cookie is auto-attached). That's protected today only by
SameSite=Lax, which is a real but single layer of defense. This adds a
standard double-submit token on top of it:

  - A non-httpOnly `csrf_token` cookie is issued on first visit (JS needs
    to read it to echo it back).
  - app/static/js/main.js wraps fetch() and hooks htmx:configRequest to
    attach it as the X-CSRF-Token header on every non-GET call.
  - This middleware rejects any state-changing request that relies on the
    session cookie for auth (no explicit Authorization header - a
    cross-site attacker can forge neither that header nor this token) and
    doesn't echo a matching token.

Genuine API clients (Authorization: Bearer / X-API-Key) and provider
webhooks are unaffected - they don't carry our cookies at all, so the
"only checked when auth would come from the cookie" rule exempts them
without needing a hardcoded path allowlist.
"""

from __future__ import annotations

import secrets
from http.cookies import SimpleCookie

from starlette.datastructures import Headers, MutableHeaders
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
_COOKIE_NAME = "csrf_token"
_HEADER_NAME = "x-csrf-token"
_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def _cookie_header(value: str) -> str:
    cookie: SimpleCookie = SimpleCookie()
    cookie[_COOKIE_NAME] = value
    morsel = cookie[_COOKIE_NAME]
    morsel["path"] = "/"
    morsel["samesite"] = "Lax"
    morsel["max-age"] = _COOKIE_MAX_AGE
    if settings.is_production:
        morsel["secure"] = True
    return morsel.OutputString()


class CSRFMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware) - see SecurityHeadersMiddleware's
    docstring for why: BaseHTTPMiddleware runs the downstream app in a
    separate anyio task, which breaks request-scoped async context sharing
    that this test suite relies on."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        existing_token = request.cookies.get(_COOKIE_NAME)
        method = scope["method"].upper()

        session_cookie_present = bool(request.cookies.get("heelo_access"))
        has_explicit_bearer = bool(Headers(scope=scope).get("authorization"))

        if method not in _SAFE_METHODS and session_cookie_present and not has_explicit_bearer:
            sent_token = Headers(scope=scope).get(_HEADER_NAME)
            if (
                not existing_token
                or not sent_token
                or not secrets.compare_digest(sent_token, existing_token)
            ):
                response = JSONResponse(
                    status_code=403,
                    content={
                        "success": False,
                        "error": {"message": "CSRF token missing or invalid."},
                    },
                )
                await response(scope, receive, send)
                return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start" and not existing_token:
                headers = MutableHeaders(scope=message)
                headers.append("set-cookie", _cookie_header(secrets.token_urlsafe(32)))
            await send(message)

        await self.app(scope, receive, send_wrapper)
