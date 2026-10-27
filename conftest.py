"""
Root conftest.py - sets required environment variables before app import.
Override TEST_DATABASE_URL env var to point to your test PostgreSQL instance.
"""
import os

# Set minimal env vars required by app.config.Settings before anything imports app
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only-not-for-production")
os.environ.setdefault("DATABASE_URL", os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/tixdoo_test",
))
os.environ.setdefault("DATABASE_URL_SYNC", os.environ.get(
    "TEST_DATABASE_URL_SYNC",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/tixdoo_test",
))
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("FRONTEND_URL", "http://localhost:8000")
os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
# Ensure Celery doesn't connect to Redis
os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")
