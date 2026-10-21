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
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# ── Import all models to register them on Base before create_all ──────────────
import app.models.api  # noqa: F401
import app.models.campaign  # noqa: F401
import app.models.checkin  # noqa: F401
import app.models.community  # noqa: F401
import app.models.crm  # noqa: F401
import app.models.event  # noqa: F401
import app.models.feedback  # noqa: F401
import app.models.live  # noqa: F401
import app.models.notification  # noqa: F401
import app.models.organization  # noqa: F401
import app.models.payment  # noqa: F401
import app.models.speaker  # noqa: F401
import app.models.ticketing  # noqa: F401
import app.models.user  # noqa: F401
import app.models.vendor  # noqa: F401
from app.database import Base, get_db
from app.main import app
from app.utils.auth import hash_password

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/heelo_test",
)


# ── Schema setup (one-time) + Engine (function-scoped) ────────────────────────
#
# The engine (and the asyncpg connections it hands out) must be function-
# scoped, matching pytest-asyncio's default per-test event loop. A
# session-scoped engine gets its connections bound to whichever loop was
# running the first time it was used - reusing it from a later test's
# (different) loop raises asyncpg's "attached to a different loop"
# RuntimeError. Schema create/drop is safe as session-scoped autouse work
# because it opens and fully disposes its own engine within a single fixture
# call, never handing a connection across a task/loop boundary.


@pytest_asyncio.fixture(scope="session", autouse=True, loop_scope="session")
async def _schema():
    eng = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await eng.dispose()
    yield
    eng = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def engine(_schema):
    eng = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    yield eng
    await eng.dispose()


# ── Direct DB session (per test) ──────────────────────────────────────────────


@pytest.fixture
async def db(engine) -> AsyncGenerator[AsyncSession, None]:
    SessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with SessionLocal() as session:
        yield session


# ── HTTP client (per test) ─────────────────────────────────────────────────────


async def _attach_csrf_header(request) -> None:
    """Mirrors what app/static/js/main.js's fetch()/HTMX wrapper does in a
    real browser (app/middleware/csrf.py) - echo the csrf_token cookie the
    server issued back as a header on every non-GET request. Without this,
    every existing authenticated POST/PUT/PATCH/DELETE test would 403."""
    if request.method not in ("GET", "HEAD", "OPTIONS", "TRACE"):
        token = request.headers.get("cookie", "")
        for part in token.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "csrf_token" and value:
                request.headers["X-CSRF-Token"] = value
                break


@pytest.fixture
async def client(db) -> AsyncGenerator[AsyncClient, None]:
    """
    Client uses the same session as `db` so fixture-inserted data is
    immediately visible to route handlers without a separate commit.
    """

    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        event_hooks={"request": [_attach_csrf_header]},
    ) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
async def _truncate_after_test(engine):
    """
    Runs for every test regardless of which fixtures it actually requests.
    Application service functions frequently call `db.commit()` directly
    (not just the `client` fixture's request cycle), so relying on the
    `client` fixture alone to clean up left data behind for any test that
    only used `db` - causing UNIQUE-constraint collisions in later tests.
    """
    yield
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
    """
    email_service.py calls the Resend REST API directly via httpx (no `resend`
    SDK package is used or installed) - patch the actual send functions.

    app.utils.email.send_smtp (OTP/welcome/password-reset/team-invite/vendor-
    lead emails) is a *separate* sender using real smtplib against whatever
    SMTP_HOST is in .env - patched here too, otherwise these tests silently
    make real outbound SMTP connections instead of the documented "no real
    network calls" guarantee above.
    """
    with (
        patch("app.services.email_service.send_sync"),
        patch("app.services.email_service.send_async", new_callable=AsyncMock),
        patch("app.utils.email.send_smtp"),
    ):
        yield


@pytest.fixture(autouse=True)
def mock_whatsapp():
    with (
        patch("app.services.whatsapp_service.send_text_sync"),
        patch("app.services.whatsapp_service.send_image_sync"),
        patch("app.services.whatsapp_service.send_text_async", new_callable=AsyncMock),
        patch("app.services.whatsapp_service.send_image_async", new_callable=AsyncMock),
    ):
        yield


class _FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = str(value)

    def incr(self, key: str) -> int:
        val = int(self.data.get(key, 0)) + 1
        self.data[key] = str(val)
        return val

    def expire(self, key: str, seconds: int) -> None:
        pass

    def delete(self, *keys: str) -> None:
        for k in keys:
            self.data.pop(k, None)
            self.sets.pop(k, None)

    def smembers(self, key: str) -> set[str]:
        return self.sets.get(key, set())

    def sadd(self, key: str, *members: str) -> None:
        s = self.sets.setdefault(key, set())
        for m in members:
            s.add(m)


@pytest.fixture(autouse=True)
def mock_redis():
    """Ensure test rate limits and cache keys never pollute or read from live Redis."""
    fake = _FakeRedis()
    with (
        patch("app.services.auth_service._login_redis", return_value=fake),
        patch("app.utils.rate_limit._redis", return_value=fake),
        patch("app.utils.cache._redis", return_value=fake),
    ):
        yield fake


# ── User fixtures ─────────────────────────────────────────────────────────────


async def _make_user(
    db: AsyncSession, *, email: str, role: str = "organizer", full_name: str = "Test User"
) -> app.models.user.User:
    from app.models.user import User

    u = User(
        full_name=full_name,
        email=email,
        password_hash=hash_password("password123"),
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
    from jose import jwt

    from app.config import settings

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
        # Enterprise so existing feature-behavior tests aren't incidentally
        # blocked by plan gates - plan-gating itself has its own dedicated
        # tests (test_plan_enforcement.py) using fixtures that set a
        # specific lower plan on purpose.
        plan="enterprise",
        currency="NGN",
    )
    db.add(o)
    await db.flush()
    return o


async def _make_member(db, org, user, role: str):
    """Add `user` to `org` as an active team member with the given role - for
    testing the per-org permission matrix (owner/admin is covered by `org` +
    `user` already, since the owner always resolves to role="admin")."""
    from app.models.organization import OrganizationMember

    now = datetime.now(UTC)
    m = OrganizationMember(
        org_id=org.id,
        user_id=user.id,
        role=role,
        invited_at=now,
        accepted_at=now,
        status="active",
    )
    db.add(m)
    await db.flush()
    return m


@pytest.fixture
async def organizer_member(db, org, other_user):
    """A non-owner team member with role="organizer" - distinct from the
    owner (always role="admin") and from `other_user` alone (not a member)."""
    return await _make_member(db, org, other_user, "organizer")


@pytest.fixture
def organizer_member_headers(organizer_member, other_user):
    return {"Authorization": f"Bearer {_make_token(str(other_user.id))}"}


@pytest.fixture
async def finance_member(db, org, other_user):
    return await _make_member(db, org, other_user, "finance")


@pytest.fixture
def finance_headers(finance_member, other_user):
    return {"Authorization": f"Bearer {_make_token(str(other_user.id))}"}


@pytest.fixture
async def checkin_staff_member(db, org, other_user):
    return await _make_member(db, org, other_user, "checkin_staff")


@pytest.fixture
def checkin_staff_headers(checkin_staff_member, other_user):
    return {"Authorization": f"Bearer {_make_token(str(other_user.id))}"}


@pytest.fixture
async def event(db, org):
    from app.models.event import Event

    e = Event(
        org_id=org.id,
        title="Test Event",
        slug="test-event",
        status="draft",
        format="in_person",
        venue_city="Lagos",
        start_datetime=datetime.now(UTC) + timedelta(days=7),
        end_datetime=datetime.now(UTC) + timedelta(days=7, hours=3),
    )
    db.add(e)
    await db.flush()
    return e


@pytest.fixture
async def published_event(db, org):
    from app.models.event import Event

    e = Event(
        org_id=org.id,
        title="Published Event",
        slug="published-event",
        status="published",
        format="in_person",
        venue_name="Landmark Centre",
        venue_city="Lagos",
        start_datetime=datetime.now(UTC) + timedelta(days=7),
        end_datetime=datetime.now(UTC) + timedelta(days=7, hours=3),
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
        quantity=100,
        quantity_sold=0,
    )
    db.add(tt)
    await db.flush()
    return tt


@pytest.fixture
async def registration(db, published_event, ticket_type):
    import uuid as _uuid

    from app.models.ticketing import Registration

    r = Registration(
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        attendee_name="Jane Doe",
        attendee_email="jane@example.com",
        attendee_phone="+2348012345678",
        qr_code=f"test-qr-{_uuid.uuid4()}",
        status="confirmed",
        referral_token=f"test-ref-{_uuid.uuid4().hex[:12]}",
    )
    db.add(r)
    await db.flush()
    return r


@pytest.fixture
async def order(db, published_event, ticket_type, user):
    import uuid as _uuid

    from app.models.ticketing import Order
    from app.services import payment_service as pay_svc

    fee_rate = float(pay_svc.PLATFORM_FEE_PERCENT)
    o = Order(
        user_id=user.id,
        event_id=published_event.id,
        buyer_name="Jane Doe",
        buyer_email="jane@example.com",
        total_amount=float(ticket_type.price),
        net_amount=float(ticket_type.price) * (1 - fee_rate),
        platform_fee=float(ticket_type.price) * fee_rate,
        currency=ticket_type.currency,
        payment_provider="paystack",
        payment_reference=f"test-ref-{_uuid.uuid4()}",
        payment_status="paid",
    )
    db.add(o)
    await db.flush()
    return o


@pytest.fixture
async def paid_registration(db, published_event, ticket_type, order):
    import uuid as _uuid

    from app.models.ticketing import Registration

    r = Registration(
        event_id=published_event.id,
        ticket_type_id=ticket_type.id,
        order_id=order.id,
        attendee_name="Jane Doe",
        attendee_email="jane@example.com",
        attendee_phone="+2348012345678",
        qr_code=f"test-qr-{_uuid.uuid4()}",
        status="confirmed",
    )
    db.add(r)
    await db.flush()
    return r


@pytest.fixture
async def vendor(db, other_user):
    from app.models.vendor import Vendor

    v = Vendor(
        user_id=other_user.id,
        business_name="Landmark Hall",
        slug="landmark-hall",
        category="venue",
        location_city="Lagos",
        location_country="NG",
        status="active",
    )
    db.add(v)
    await db.flush()
    return v


@pytest.fixture
async def api_key(db, org, user):
    from app.services.api_key_service import create_api_key

    raw, key = await create_api_key(db, org_id=org.id, created_by=user.id, name="test-key")
    await db.flush()
    return raw, key
