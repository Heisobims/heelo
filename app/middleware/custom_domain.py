"""
Custom-domain routing (Pro+ feature).

Every existing route already works identically regardless of which
hostname reached the server - FastAPI/Starlette route on *path*, not
*Host*. The one thing that genuinely differs by domain is the root path
"/": on heelo.io it's the marketing landing page, but on an organizer's
own verified domain it should land straight on their event instead.

This middleware only ever touches that one case. It looks up the
requesting Host against verified Organization.custom_domain values and,
on a match at "/", redirects to that org's most relevant event page -
everything else passes through completely untouched.

IMPORTANT - deployment requirement this middleware does NOT solve:
FastAPI's TrustedHostMiddleware (see app/main.py) rejects requests whose
Host header isn't in `settings.ALLOWED_HOSTS`. In production that means a
verified custom domain must be added to ALLOWED_HOSTS (or TrustedHostMiddleware
relaxed for verified domains) before traffic from it ever reaches this
middleware at all - that's an operator/config decision, not something safe
to bypass silently in code. Likewise, this only handles *application
routing*; making the domain actually resolve to this server (CNAME/A
record) and terminating TLS for it is real DNS/CDN infrastructure work
outside this codebase.
"""

from __future__ import annotations

import ipaddress
import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

logger = structlog.get_logger()


def _is_local_or_ip(host: str) -> bool:
    if host in ("localhost", "127.0.0.1", "testserver"):
        return True
    if any(host.endswith(sfx) for sfx in (".local", ".lhr.life", ".localhost.run", ".pinggy.link", ".ngrok-free.app", ".loca.lt")):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


class CustomDomainMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != "/":
            await self.app(scope, receive, send)
            return

        host = _host_from_scope(scope)
        if not host or _is_local_or_ip(host):
            await self.app(scope, receive, send)
            return

        redirect_path = await _resolve_custom_domain_redirect(host)
        if not redirect_path:
            await self.app(scope, receive, send)
            return

        await send(
            {
                "type": "http.response.start",
                "status": 302,
                "headers": [(b"location", redirect_path.encode())],
            }
        )
        await send({"type": "http.response.body", "body": b""})


def _host_from_scope(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"host":
            return value.decode("latin-1").split(":")[0].lower()
    return None


async def _resolve_custom_domain_redirect(host: str) -> str | None:
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.event import Event
    from app.models.organization import Organization

    try:
        async with AsyncSessionLocal() as db:
            org = await db.scalar(
                select(Organization).where(
                    Organization.custom_domain == host,
                    Organization.custom_domain_verified.is_(True),
                    Organization.is_active.is_(True),
                )
            )
            if not org:
                return None

            event = await db.scalar(
                select(Event)
                .where(Event.org_id == org.id, Event.status == "live")
                .order_by(Event.start_datetime.desc())
                .limit(1)
            )
            if not event:
                event = await db.scalar(
                    select(Event)
                    .where(Event.org_id == org.id, Event.status == "published")
                    .order_by(Event.start_datetime.asc())
                    .limit(1)
                )
            return f"/e/{event.slug}" if event else None
    except Exception as err:
        # Never let a DNS/DB hiccup take down the whole app's homepage.
        logger.warning("custom_domain.resolve_failed", host=host, error=str(err))
        return None
