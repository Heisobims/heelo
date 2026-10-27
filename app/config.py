from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────────
    APP_NAME: str = "Tixdoo"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    SECRET_KEY: str
    FRONTEND_URL: str = "http://localhost:8000"
    # Typed as a union (not plain list[str]) so that a non-JSON env value (e.g.
    # "localhost,127.0.0.1,testserver") doesn't make pydantic-settings' own
    # complex-type JSON pre-parse raise before this validator ever runs - see
    # EnvSettingsSource._field_is_complex()'s allow_parse_failure branch.
    ALLOWED_HOSTS: str | list[str] = ["localhost", "127.0.0.1"]

    @field_validator("ALLOWED_HOSTS", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                import json

                return json.loads(v)
            return [h.strip() for h in v.split(",")]
        return v

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str  # postgresql+asyncpg://...
    DATABASE_URL_SYNC: str  # postgresql+psycopg2://... (for Alembic)

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── Auth ──────────────────────────────────────────────────────────────────
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    OTP_EXPIRE_MINUTES: int = 10
    ALGORITHM: str = "HS256"

    # ── OAuth ─────────────────────────────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    FACEBOOK_CLIENT_ID: str = ""
    FACEBOOK_CLIENT_SECRET: str = ""

    # ── Email - Resend ────────────────────────────────────────────────────────
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = "hello@tixdoo.com"
    RESEND_FROM_NAME: str = "Tixdoo"

    # ── Email - SMTP ─────────────────────────────────────────────────────────
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "hello@tixdoo.com"
    SMTP_FROM_NAME: str = "Tixdoo"
    SMTP_TLS: bool = True  # STARTTLS (port 587)
    SMTP_SSL: bool = False  # Direct SSL (port 465)

    # ── SMS ───────────────────────────────────────────────────────────────────
    TERMII_API_KEY: str = ""
    TERMII_SENDER_ID: str = "Tixdoo"
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""

    # ── WhatsApp ─────────────────────────────────────────────────────────────
    WHATSAPP_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_VERIFY_TOKEN: str = ""
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = ""
    WHATSAPP_APP_SECRET: str = ""

    # ── Payments ─────────────────────────────────────────────────────────────
    PAYSTACK_SECRET_KEY: str = ""
    PAYSTACK_PUBLIC_KEY: str = ""
    FLUTTERWAVE_SECRET_KEY: str = ""
    FLUTTERWAVE_PUBLIC_KEY: str = ""
    FLUTTERWAVE_WEBHOOK_SECRET: str = ""
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLIC_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    # Internal ops address for the weekly pending-manual-payouts digest
    # (app/tasks/billing.py) - blank by default, digest send is skipped
    # entirely until set.
    OPS_ALERT_EMAIL: str = ""

    # ── AI ────────────────────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"

    # ── SEO / analytics ───────────────────────────────────────────────────────
    # Both blank by default - base.html only renders the corresponding tag/
    # script when set, so nothing ships until real IDs from your own GA4/
    # Search Console properties are configured.
    GA_MEASUREMENT_ID: str = ""
    GOOGLE_SITE_VERIFICATION: str = ""

    # ── Storage - Cloudflare R2 ───────────────────────────────────────────────
    CLOUDFLARE_R2_ACCOUNT_ID: str = ""
    CLOUDFLARE_R2_ACCESS_KEY_ID: str = ""
    CLOUDFLARE_R2_SECRET_ACCESS_KEY: str = ""
    CLOUDFLARE_R2_BUCKET: str = "tixdoo-media"
    CLOUDFLARE_R2_PUBLIC_URL: str = "https://media.tixdoo.com"

    # ── Database pool ─────────────────────────────────────────────────────────
    # Every gunicorn worker (gunicorn.conf.py: cpu_count()*2+1 by default) and
    # every Celery worker opens its own pool of this size - size it so
    # web_workers * (DB_POOL_SIZE + DB_MAX_OVERFLOW) + celery_workers * (...)
    # stays comfortably under Postgres's max_connections (100 by default; a
    # managed Postgres plan may differ). At the old defaults (10 + 20 = 30
    # per process) a handful of gunicorn workers alone could approach that
    # ceiling - these are set lower so a typical single-box deployment has
    # headroom by default; raise them deliberately for a larger Postgres plan.
    DB_POOL_SIZE: int = 5  # connections per worker
    DB_MAX_OVERFLOW: int = 5  # burst headroom
    DB_POOL_TIMEOUT: int = 30  # seconds to wait for a connection
    DB_POOL_RECYCLE: int = 1800  # recycle idle connections after 30 min

    # ── Monitoring ────────────────────────────────────────────────────────────
    SENTRY_DSN: str = ""
    LOG_LEVEL: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
