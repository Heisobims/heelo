"""
Shared test fixtures for Heelo.

Database strategy:
  - Session-scoped engine connects to `heelo_test` PostgreSQL DB.
  - All tables are created once per session and truncated between each test.
  - `db` fixture: direct async session for fixtures that insert test data.
  - `client` fixture: httpx.AsyncClient with overridden get_db dependency.

External services (Celery, email, WhatsApp, Anthropic) are all mocked globally
so no real network calls happen during tests.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Import all models to register them on Base before create_all ──────────────
import app.models.api  # noqa: F401
import app.models.campaign  # noqa: F401
import app.models.community  # noqa: F401
import app.models.event  # noqa: F401
import app.models.notification  # noqa: F401
import app.models.organization  # noqa: F401
import app.models.payment  # noqa: F401
import app.models.speaker  # noqa: F401
import app.models.ticketing  # noqa: F401
import app.models.user  # noqa: F401
from app.database import Base, get_db
from app.main import app

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/heelo_test",
)


# ── Engine (session-scoped) ───────────────────────────────────────────────────

@pytest.fixture(scope="session")
async def engine():
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


# ── Direct DB session (per test) ──────────────────────────────────────────────

@pytest.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    SessionLocal = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
        autocommit=False, autoflush=False,
    )
    async with SessionLocal() as session:
        yield session


# ── HTTP client (per test) ─────────────────────────────────────────────────────

@pytest.fixture
async def client(engine, db) -> AsyncGenerator[AsyncClient, None]:
    """
    Client uses the same session as `db` so fixture-inserted data is
    immediately visible to route handlers without a separate commit.
    """
    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_db, None)

    # Truncate all tables in dependency order
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


# ── Mock all external side-effects ────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_celery_tasks():
    """Prevent any Celery task from actually being enqueued."""
    with patch("celery.app.task.Task.delay", return_value=MagicMock(id="fake-task-id")):
        yield


@pytest.fixture(autouse=True)
def mock_email():
    with patch("resend.Emails.send", return_value={"id": "fake-email-id"}):
        yield


@pytest.fixture(autouse=True)
def mock_whatsapp():
    with patch("app.services.whatsapp_service.send_text_message", new_callable=AsyncMock):
        yield


# ── User fixtures ─────────────────────────────────────────────────────────────

async def _make_user(db: AsyncSession, *, email: str, role: str = "organizer",
                     full_name: str = "Test User") -> app.models.user.User:
    from app.models.user import User

    u = User(
        full_name=full_name,
        email=email,
        password_hash=_pwd.hash("password123"),
        role=role,
        is_verified=True,
    )
    db.add(u)
    await db.flush()
    return u


@pytest.fixture
async def user(db):
    return await _make_user(db, email="organizer@example.com")


@pytest.fixture
async def admin_user(db):
    return await _make_user(db, email="admin@example.com", role="admin", full_name="Admin User")


@pytest.fixture
async def other_user(db):
    return await _make_user(db, email="other@example.com", full_name="Other User")


# ── Token helpers ─────────────────────────────────────────────────────────────

def _make_token(user_id: str) -> str:
    from app.config import settings
    from jose import jwt
    payload = {
        "sub": user_id,
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "type": "access",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


@pytest.fixture
def user_headers(user):
    return {"Authorization": f"Bearer {_make_token(str(user.id))}"}


@pytest.fixture
def admin_headers(admin_user):
    return {"Authorization": f"Bearer {_make_token(str(admin_user.id))}"}


@pytest.fixture
def other_headers(other_user):
    return {"Authorization": f"Bearer {_make_token(str(other_user.id))}"}


# ── Org / event / ticket fixtures ─────────────────────────────────────────────

@pytest.fixture
async def org(db, user):
    from app.models.organization import Organization

    o = Organization(
        owner_id=user.id,
        name="Test Org",
        slug="test-org",
        plan="starter",
        currency="NGN",
    )
    db.add(o)
    await db.flush()
    return o


@pytest.fixture
async def event(db, org):
    from app.models.event import Event

    e = Event(
        org_id=org.id,
        title="Test Event",
        slug="test-event",
        status="draft",
        format="in_person",
        is_free=False,
        currency="NGN",
    )
    db.add(e)
    await db.flush()
    return e


@pytest.fixture
async def published_event(db, org):
    from app.models.event import Event
    from datetime import timezone

    e = Event(
        org_id=org.id,
        title="Published Event",
        slug="published-event",
        status="published",
        format="in_person",
        is_free=False,
        currency="NGN",
        start_datetime=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(e)
    await db.flush()
    return e


@pytest.fixture
async def ticket_type(db, published_event):
    from app.models.ticketing import TicketType

    tt = TicketType(
        event_id=published_event.id,
        name="General Admission",
        price=5000.0,
        currency="NGN",
        quantity_total=100,
        quantity_sold=0,
    )
    db.add(tt)
    await db.flush()
    return tt


@pytest.fixture
async def registration(db, published_event, ticket_type):
    from app.models.ticketing import Registration

    r = Registration(
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        attendee_name="Jane Doe",
        attendee_email="jane@example.com",
        status="confirmed",
    )
    db.add(r)
    await db.flush()
    return r


@pytest.fixture
async def api_key(db, org, user):
    from app.services.api_key_service import create_api_key

    raw, key = await create_api_key(db, org_id=org.id, created_by=user.id, name="test-key")
    await db.flush()
    return raw, key
