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
    APP_NAME: str = "Heelo"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    SECRET_KEY: str
    FRONTEND_URL: str = "http://localhost:8000"
    ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1"]

    @field_validator("ALLOWED_HOSTS", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
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

    # ── Email — Resend ────────────────────────────────────────────────────────
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = "hello@heelo.io"
    RESEND_FROM_NAME: str = "Heelo"

    # ── Email — SMTP ─────────────────────────────────────────────────────────
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "hello@heelo.io"
    SMTP_FROM_NAME: str = "Heelo"
    SMTP_TLS: bool = True  # STARTTLS (port 587)
    SMTP_SSL: bool = False  # Direct SSL (port 465)

    # ── SMS ───────────────────────────────────────────────────────────────────
    TERMII_API_KEY: str = ""
    TERMII_SENDER_ID: str = "Heelo"
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""

    # ── WhatsApp ─────────────────────────────────────────────────────────────
    WHATSAPP_TOKEN: str = ""
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_VERIFY_TOKEN: str = ""
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = ""

    # ── Payments ─────────────────────────────────────────────────────────────
    PAYSTACK_SECRET_KEY: str = ""
    PAYSTACK_PUBLIC_KEY: str = ""
    FLUTTERWAVE_SECRET_KEY: str = ""
    FLUTTERWAVE_PUBLIC_KEY: str = ""
    FLUTTERWAVE_WEBHOOK_SECRET: str = ""
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLIC_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # ── AI ────────────────────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"

    # ── Storage — Cloudflare R2 ───────────────────────────────────────────────
    CLOUDFLARE_R2_ACCOUNT_ID: str = ""
    CLOUDFLARE_R2_ACCESS_KEY_ID: str = ""
    CLOUDFLARE_R2_SECRET_ACCESS_KEY: str = ""
    CLOUDFLARE_R2_BUCKET: str = "heelo-media"
    CLOUDFLARE_R2_PUBLIC_URL: str = "https://media.heelo.io"

    # ── Database pool ─────────────────────────────────────────────────────────
    DB_POOL_SIZE: int = 10  # connections per worker
    DB_MAX_OVERFLOW: int = 20  # burst headroom
    DB_POOL_TIMEOUT: int = 30  # seconds to wait for a connection
    DB_POOL_RECYCLE: int = 1800  # recycle idle connections after 30 min

    # ── Monitoring ────────────────────────────────────────────────────────────
    SENTRY_DSN: str = ""
    LOG_LEVEL: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
