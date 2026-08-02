from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import sentry_sdk
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.config import settings
from app.database import engine
from app.logging_config import configure_logging

# Importing this here (not used directly) ensures the properly-configured
# Celery app — broker=settings.CELERY_BROKER_URL — becomes Celery's "current
# app" for this process. Without it, @shared_task-decorated tasks resolve
# against Celery's bare default app (AMQP, localhost) instead, so every
# `.delay()` call from a request handler fails with a connection error even
# though a Redis broker is configured and the worker itself is fine.
from app.tasks import celery_app as _celery_app  # noqa: F401

# Configure structured logging before anything else logs
configure_logging(log_level=settings.LOG_LEVEL, production=settings.is_production)

logger = structlog.get_logger()


# ── Sentry ────────────────────────────────────────────────────────────────────
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.APP_ENV,
        integrations=[FastApiIntegration(), SqlalchemyIntegration()],
        traces_sample_rate=0.1 if settings.is_production else 1.0,
        send_default_pii=False,
    )


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("heelo.startup", env=settings.APP_ENV)
    yield
    await engine.dispose()
    logger.info("heelo.shutdown")


# ── App factory ───────────────────────────────────────────────────────────────
def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description="Every great event starts with heelo.",
        version="1.0.0",
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url="/api/redoc" if not settings.is_production else None,
        openapi_url="/api/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Middleware ────────────────────────────────────────────────────────────
    # Applied in reverse order: last registered = outermost (runs first).
    from app.middleware.request_logging import RequestLoggingMiddleware
    from app.middleware.security import SecurityHeadersMiddleware

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=(
            settings.ALLOWED_HOSTS + ["*"] if settings.is_development else settings.ALLOWED_HOSTS
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_URL],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Static files ──────────────────────────────────────────────────────────
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    # ── Routers ───────────────────────────────────────────────────────────────
    _register_routers(app)

    # ── Exception handlers ────────────────────────────────────────────────────
    _register_exception_handlers(app)

    return app


def _register_routers(app: FastAPI) -> None:
    from app.routers import health
    from app.routers.auth import router_api as auth_api
    from app.routers.auth import router_pages as auth_pages
    from app.routers.organization import router_api as org_api
    from app.routers.pages import router_pages as page_routes

    app.include_router(health.router)
    app.include_router(auth_api)  # /api/v1/auth/...
    app.include_router(auth_pages)  # /login, /register, etc.
    app.include_router(org_api)  # /api/v1/organizations/...
    app.include_router(
        page_routes
    )  # /dashboard, /org/{slug}, /home, /accept-invite/{token}, /e/{slug}

    from app.routers.event import router_org as event_org_api
    from app.routers.event import router_public as event_public_api

    app.include_router(event_org_api)  # /api/v1/organizations/{slug}/events/...
    app.include_router(event_public_api)  # /api/v1/events/...

    from app.routers.ticketing import router_org as ticketing_org_api
    from app.routers.ticketing import router_public as ticketing_public_api
    from app.routers.ticketing import router_registrations

    app.include_router(
        ticketing_org_api
    )  # /api/v1/organizations/{slug}/events/{id}/ticket-types/...
    app.include_router(
        ticketing_public_api
    )  # /api/v1/events/{slug}/register, /ticket-types, /promo-codes
    app.include_router(router_registrations)  # /api/v1/registrations/{id}/qr.png

    from app.routers.badges import router_org as badge_org_api
    from app.routers.badges import router_registrations as badge_registrations_api

    app.include_router(badge_registrations_api)  # /api/v1/registrations/{id}/badge.pdf
    app.include_router(badge_org_api)  # /api/v1/organizations/{slug}/events/{id}/badges.pdf

    from app.routers.certificates import router_org as certificate_org_api
    from app.routers.certificates import router_registrations as certificate_registrations_api

    app.include_router(certificate_registrations_api)  # /api/v1/registrations/{id}/certificate.pdf
    app.include_router(certificate_org_api)  # /api/v1/orgs/{slug}/events/{id}/certificates/...

    from app.routers.live import router_org as live_org_api
    from app.routers.live import router_public as live_public_api

    app.include_router(live_org_api)  # /api/v1/organizations/{slug}/events/{id}/live/...
    app.include_router(live_public_api)  # /api/v1/events/{slug}/live/...

    from app.routers.payment import router_payment_accounts, router_webhooks

    app.include_router(router_webhooks)  # /api/v1/webhooks/{paystack,flutterwave,stripe}
    app.include_router(router_payment_accounts)  # /api/v1/organizations/{slug}/payment-accounts/...

    from app.routers.checkin import router_checkin

    app.include_router(router_checkin)  # /api/v1/organizations/{slug}/events/{id}/check-in/...

    from app.routers.speaker import router_event as speaker_event_api
    from app.routers.speaker import router_org as speaker_org_api
    from app.routers.speaker import router_public as speaker_public_api

    app.include_router(speaker_org_api)  # /api/v1/organizations/{slug}/speakers/...
    app.include_router(speaker_event_api)  # /api/v1/organizations/{slug}/events/{id}/speakers/...
    app.include_router(speaker_public_api)  # /api/v1/events/{slug}/speakers

    from app.routers.sponsor import router_event as sponsor_event_api
    from app.routers.sponsor import router_portal as sponsor_portal_api
    from app.routers.sponsor import router_public as sponsor_public_api

    app.include_router(sponsor_event_api)  # /api/v1/organizations/{slug}/events/{id}/sponsors/...
    app.include_router(sponsor_public_api)  # /api/v1/events/{slug}/sponsors
    app.include_router(sponsor_portal_api)  # /api/v1/sponsor-portal/...

    from app.routers.agenda import router_event as agenda_event_api
    from app.routers.agenda import router_public as agenda_public_api

    app.include_router(agenda_event_api)  # /api/v1/organizations/{slug}/events/{id}/sessions/...
    app.include_router(agenda_public_api)  # /api/v1/events/{slug}/sessions

    from app.routers.feedback import router_feedback_org, router_feedback_public

    app.include_router(router_feedback_public)  # /api/v1/registrations/{id}/feedback
    app.include_router(router_feedback_org)  # /api/v1/organizations/{slug}/events/{id}/feedback

    from app.routers.whatsapp import router_whatsapp

    app.include_router(router_whatsapp)  # GET+POST /api/v1/webhooks/whatsapp

    from app.routers.analytics import router_analytics

    app.include_router(router_analytics)  # /api/v1/organizations/{slug}/events/{id}/analytics/...

    from app.routers.campaign import router_campaigns

    app.include_router(router_campaigns)  # /api/v1/organizations/{slug}/campaigns/...

    from app.routers.vendor import router_vendor

    app.include_router(router_vendor)  # /api/v1/vendors/...

    from app.routers.crm import router_crm

    app.include_router(router_crm)  # /api/v1/organizations/{slug}/registrations/export.csv

    from app.routers.ai import router_ai

    app.include_router(router_ai)  # /api/v1/organizations/{slug}/ai/...

    from app.routers.community import router_community

    app.include_router(router_community)  # /api/v1/organizations/{slug}/inbox/... + /follow

    from app.routers.community import router_comments

    app.include_router(router_comments)  # /api/v1/events/{slug}/comments

    from app.routers.connections import router_connections

    app.include_router(router_connections)  # /api/v1/connections/...

    from app.routers.messages import router_messages

    app.include_router(router_messages)  # /api/v1/messages/...

    from app.routers.api_keys import router_api_keys

    app.include_router(router_api_keys)  # /api/v1/organizations/{slug}/api-keys/...

    from app.routers.webhooks_api import router_webhooks_api

    app.include_router(router_webhooks_api)  # /api/v1/organizations/{slug}/webhooks/...

    from app.routers.public_api import router_public_api

    app.include_router(router_public_api)  # /api/public/v1/...

    from app.routers.admin import router_admin

    app.include_router(router_admin)  # /api/v1/admin/...

    from app.routers.admin_pages import router_admin_pages

    app.include_router(router_admin_pages)  # /admin/...


def _register_exception_handlers(app: FastAPI) -> None:
    from fastapi import HTTPException
    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {
                    "code": _status_to_code(exc.status_code),
                    "message": exc.detail,
                    "details": {},
                },
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        field_errors: dict[str, list[str]] = {}
        for err in exc.errors():
            loc = ".".join(str(l) for l in err["loc"] if l != "body")
            field_errors.setdefault(loc, []).append(err["msg"])

        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Please check the highlighted fields.",
                    "details": field_errors,
                },
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        import traceback as _tb

        tb = _tb.format_exc()
        logger.error(
            "unhandled_exception",
            exc=str(exc),
            exc_type=type(exc).__name__,
            path=str(request.url),
            traceback=tb,
        )
        detail = (
            {"exc_type": type(exc).__name__, "exc": str(exc), "traceback": tb}
            if settings.is_development
            else {}
        )
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Something went wrong. We've been notified.",
                    "details": detail,
                },
            },
        )


def _status_to_code(status: int) -> str:
    mapping = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "TOO_MANY_REQUESTS",
        500: "INTERNAL_ERROR",
    }
    return mapping.get(status, "ERROR")


app = create_app()
