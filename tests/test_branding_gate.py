"""Plan-gated branding - custom logo/brand color is a Growth+ feature; the
"Powered by Heelo" mark shows on every tier except Enterprise. Covers the
Organization model properties, the public event page, outbound email
branding, and the certificate/badge PDF generators."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from app.plans import get_limits  # noqa: F401  (imported for parity with other plan test files)


async def _make_user(db, *, email: str):
    from app.models.user import User
    from app.utils.auth import hash_password

    u = User(
        full_name="Branding Test User",
        email=email,
        password_hash=hash_password("password123"),
        role="organizer",
        is_verified=True,
    )
    db.add(u)
    await db.flush()
    return u


async def _make_org(db, owner, *, plan: str, slug: str):
    from app.models.organization import Organization

    o = Organization(
        owner_id=owner.id,
        name=f"{plan.capitalize()} Branding Org",
        slug=slug,
        plan=plan,
        brand_color="#6C2BD9",
        logo_url="https://example.com/logo.png",
        currency="NGN",
    )
    db.add(o)
    await db.flush()
    return o


async def _make_published_event(db, org, *, slug: str):
    from app.models.event import Event

    e = Event(
        org_id=org.id,
        title="Branding Test Event",
        slug=slug,
        status="published",
        format="in_person",
        venue_city="Lagos",
        start_datetime=datetime.now(UTC) + timedelta(days=7),
        end_datetime=datetime.now(UTC) + timedelta(days=7, hours=3),
    )
    db.add(e)
    await db.flush()
    return e


# ── Organization model properties ───────────────────────────────────────────


async def test_free_org_display_properties_suppress_custom_branding(db):
    owner = await _make_user(db, email="free-brand@example.com")
    org = await _make_org(db, owner, plan="free", slug="free-brand-org")
    assert org.display_brand_color is None
    assert org.display_logo_url is None
    assert org.show_powered_by is True
    # Raw values are still there - just not surfaced to display contexts.
    assert org.brand_color == "#6C2BD9"
    assert org.logo_url == "https://example.com/logo.png"


async def test_growth_org_display_properties_show_custom_branding(db):
    owner = await _make_user(db, email="growth-brand@example.com")
    org = await _make_org(db, owner, plan="growth", slug="growth-brand-org")
    assert org.display_brand_color == "#6C2BD9"
    assert org.display_logo_url == "https://example.com/logo.png"
    assert org.show_powered_by is True  # Growth keeps the footer mark


async def test_enterprise_org_hides_powered_by(db):
    owner = await _make_user(db, email="ent-brand@example.com")
    org = await _make_org(db, owner, plan="enterprise", slug="ent-brand-org")
    assert org.display_brand_color == "#6C2BD9"
    assert org.show_powered_by is False


# ── Public event page ────────────────────────────────────────────────────────


async def test_public_event_page_free_tier_shows_watermark_not_brand_color(client: AsyncClient, db):
    owner = await _make_user(db, email="free-page@example.com")
    org = await _make_org(db, owner, plan="free", slug="free-page-org")
    event = await _make_published_event(db, org, slug="free-page-event")

    resp = await client.get(f"/e/{event.slug}")
    assert resp.status_code == 200
    assert "#6C2BD9" not in resp.text
    assert "Powered by" in resp.text


async def test_public_event_page_growth_tier_shows_brand_color_and_watermark(
    client: AsyncClient, db
):
    owner = await _make_user(db, email="growth-page@example.com")
    org = await _make_org(db, owner, plan="growth", slug="growth-page-org")
    event = await _make_published_event(db, org, slug="growth-page-event")

    resp = await client.get(f"/e/{event.slug}")
    assert resp.status_code == 200
    assert "#6C2BD9" in resp.text
    assert "Powered by" in resp.text


async def test_public_event_page_enterprise_tier_hides_watermark(client: AsyncClient, db):
    owner = await _make_user(db, email="ent-page@example.com")
    org = await _make_org(db, owner, plan="enterprise", slug="ent-page-org")
    event = await _make_published_event(db, org, slug="ent-page-event")

    resp = await client.get(f"/e/{event.slug}")
    assert resp.status_code == 200
    assert "#6C2BD9" in resp.text
    assert "Powered by" not in resp.text


# ── Email branding ───────────────────────────────────────────────────────────


async def test_org_branding_helper_gates_on_plan(db):
    """app.tasks.email._org_branding runs in a sync Celery context against a
    sync session - exercise it directly rather than through the async ORM."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.tasks.email import _org_branding
    from tests.conftest import TEST_DATABASE_URL

    sync_url = TEST_DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg2")

    owner = await _make_user(db, email="sync-brand@example.com")
    org = await _make_org(db, owner, plan="free", slug="sync-brand-org")
    await db.commit()
    org_id = org.id

    engine = create_engine(sync_url)
    SyncSession = sessionmaker(bind=engine)
    with SyncSession() as sync_db:
        branding = _org_branding(sync_db, org_id)
    assert branding["brand_color"] is None
    assert branding["org_logo_url"] is None
    assert branding["show_powered_by"] is True
    engine.dispose()


# ── Certificate / badge PDF generators ──────────────────────────────────────


def test_certificate_pdf_includes_powered_by_mark_by_default():
    from app.utils.certificate_pdf import CertificateData, generate_certificate_pdf

    common = {
        "attendee_name": "Jane",
        "event_title": "Test Event",
        "org_name": "Acme",
        "event_date": datetime.now(UTC),
    }
    pdf_with_mark = generate_certificate_pdf([CertificateData(**common, show_powered_by=True)])
    pdf_without_mark = generate_certificate_pdf([CertificateData(**common, show_powered_by=False)])
    # Different content (the drawn text differs) - a cheap way to confirm the
    # flag actually changes output without parsing PDF internals.
    assert pdf_with_mark != pdf_without_mark


def test_badge_pdf_includes_powered_by_mark_by_default():
    from app.utils.badge_pdf import BadgeData, generate_badge_pdf

    common = {
        "attendee_name": "Jane",
        "ticket_type_name": "GA",
        "event_title": "Test Event",
        "org_name": "Acme",
    }
    pdf_with_mark = generate_badge_pdf([BadgeData(**common, show_powered_by=True)])
    pdf_without_mark = generate_badge_pdf([BadgeData(**common, show_powered_by=False)])
    assert pdf_with_mark != pdf_without_mark
