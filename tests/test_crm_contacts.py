"""CRM contacts - CSV import and the unsubscribe-link flow. Both are
compliance-relevant (an unsubscribe request must actually suppress future
campaign sends) and had zero test coverage."""

from __future__ import annotations

from httpx import AsyncClient


def _csv_file(content: str, filename: str = "contacts.csv"):
    return {"file": (filename, content.encode("utf-8"), "text/csv")}


# ── Import ───────────────────────────────────────────────────────────────────


async def test_import_contacts_creates_rows(client: AsyncClient, org, user_headers):
    csv_content = (
        "name,email,phone\n"
        "Ada Lovelace,ada@example.com,+2348012345678\n"
        "Grace Hopper,grace@example.com,+2348012345679\n"
    )
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/contacts/import",
        files=_csv_file(csv_content),
        headers=user_headers,
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["imported"] == 2
    assert data["skipped"] == 0

    listing = await client.get(f"/api/v1/organizations/{org.slug}/contacts", headers=user_headers)
    emails = {c["email"] for c in listing.json()["data"]}
    assert {"ada@example.com", "grace@example.com"}.issubset(emails)


async def test_import_contacts_skips_rows_with_no_name_or_email(
    client: AsyncClient, org, user_headers
):
    csv_content = "name,email,phone\n,,+2348012345678\nOnly Name,,\n"
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/contacts/import",
        files=_csv_file(csv_content),
        headers=user_headers,
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["imported"] == 1  # "Only Name" row has a name, gets imported
    assert data["skipped"] == 1


async def test_import_contacts_dedupes_by_email(client: AsyncClient, org, user_headers):
    csv_content = "name,email\nAda Lovelace,ada2@example.com\n"
    first = await client.post(
        f"/api/v1/organizations/{org.slug}/contacts/import",
        files=_csv_file(csv_content),
        headers=user_headers,
    )
    assert first.json()["data"]["imported"] == 1

    second = await client.post(
        f"/api/v1/organizations/{org.slug}/contacts/import",
        files=_csv_file(csv_content),
        headers=user_headers,
    )
    assert second.json()["data"]["imported"] == 0
    assert second.json()["data"]["skipped"] == 1


async def test_import_contacts_rejects_non_csv_file(client: AsyncClient, org, user_headers):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/contacts/import",
        files={"file": ("contacts.txt", b"name,email\nA,a@example.com\n", "text/plain")},
        headers=user_headers,
    )
    assert resp.status_code == 422


async def test_import_contacts_rejects_checkin_staff(
    client: AsyncClient, org, checkin_staff_headers
):
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/contacts/import",
        files=_csv_file("name,email\nA,a@example.com\n"),
        headers=checkin_staff_headers,
    )
    assert resp.status_code == 403


async def test_import_contacts_handles_header_case_and_whitespace(
    client: AsyncClient, org, user_headers
):
    csv_content = " Name , Email , WhatsApp Number \nAda,ada3@example.com,+2348012345678\n"
    resp = await client.post(
        f"/api/v1/organizations/{org.slug}/contacts/import",
        files=_csv_file(csv_content),
        headers=user_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["imported"] == 1


# ── Unsubscribe ────────────────────────────────────────────────────────────────


async def test_unsubscribe_link_marks_existing_contact(client: AsyncClient, db, org, user_headers):
    from app.utils.auth import create_unsubscribe_token

    await client.post(
        f"/api/v1/organizations/{org.slug}/contacts/import",
        files=_csv_file("name,email\nAda,ada4@example.com\n"),
        headers=user_headers,
    )

    token = create_unsubscribe_token(str(org.id), "ada4@example.com")
    resp = await client.get(f"/unsubscribe/{token}")
    assert resp.status_code == 200
    assert b"You're unsubscribed" in resp.content
    assert org.name.encode() in resp.content

    from sqlalchemy import select

    from app.models.crm import Contact

    contact = await db.scalar(
        select(Contact).where(Contact.org_id == org.id, Contact.email == "ada4@example.com")
    )
    assert contact.is_unsubscribed is True


async def test_unsubscribe_link_creates_contact_if_none_exists(client: AsyncClient, db, org):
    """A recipient can unsubscribe even if they were never separately added
    as a CRM contact - the campaign send path creates recipients straight
    from Registration rows, not from Contact."""
    from app.utils.auth import create_unsubscribe_token

    token = create_unsubscribe_token(str(org.id), "never-imported@example.com")
    resp = await client.get(f"/unsubscribe/{token}")
    assert resp.status_code == 200

    from sqlalchemy import select

    from app.models.crm import Contact

    contact = await db.scalar(
        select(Contact).where(
            Contact.org_id == org.id, Contact.email == "never-imported@example.com"
        )
    )
    assert contact is not None
    assert contact.is_unsubscribed is True


async def test_unsubscribe_rejects_invalid_token(client: AsyncClient):
    resp = await client.get("/unsubscribe/not-a-real-token")
    assert resp.status_code == 200  # renders an error page, not a raw 4xx
    assert b"invalid" in resp.content.lower() or b"expired" in resp.content.lower()


async def test_unsubscribe_rejects_token_for_nonexistent_org(client: AsyncClient):
    import uuid

    from app.utils.auth import create_unsubscribe_token

    token = create_unsubscribe_token(str(uuid.uuid4()), "someone@example.com")
    resp = await client.get(f"/unsubscribe/{token}")
    assert resp.status_code == 200
    assert b"invalid" in resp.content.lower() or b"expired" in resp.content.lower()
