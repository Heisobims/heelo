from __future__ import annotations

import csv
import io
import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.dependencies import DBSession, OrgAccess
from app.permissions import Permission, require_permission
from app.services import crm_service as crm_svc

router_crm = APIRouter(
    prefix="/api/v1/organizations/{slug}",
    tags=["crm"],
)

CrmManageAccess = Annotated[tuple, Depends(require_permission(Permission.CRM_MANAGE))]


@router_crm.get("/registrations/export.csv")
async def export_registrations_csv(
    slug: str,
    db: DBSession,
    org_access: OrgAccess,
    event_id: str | None = Query(None),
    status: str | None = Query(None),
    q: str | None = Query(None),
):
    org, role, is_owner = org_access
    eid: uuid.UUID | None = None
    if event_id:
        try:
            eid = uuid.UUID(event_id)
        except ValueError:
            pass

    csv_data = await crm_svc.export_csv_string(
        db, org.id, event_id=eid, status=status or None, search=q or None
    )
    return StreamingResponse(
        io.BytesIO(csv_data.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=registrations.csv"},
    )


@router_crm.post("/contacts/import", status_code=201)
async def import_contacts_csv(
    slug: str,
    db: DBSession,
    org_access: CrmManageAccess,
    file: UploadFile = File(...),
):
    """
    Import contacts from a CSV file.
    Expected columns (case-insensitive): name, email, phone, whatsapp_number.
    Returns count of imported / skipped rows.
    """
    org, role, _ = org_access

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(422, "File must be a .csv")

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")  # handles BOM
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    # Normalize header names
    fieldnames = [h.strip().lower().replace(" ", "_") for h in (reader.fieldnames or [])]
    reader.fieldnames = fieldnames

    imported = 0
    skipped = 0
    errors: list[str] = []

    from sqlalchemy import select

    from app.models.crm import Contact

    for i, row in enumerate(reader, start=2):
        name = (row.get("name") or "").strip()
        email = (row.get("email") or "").strip().lower() or None
        phone = (row.get("phone") or "").strip() or None
        whatsapp = (row.get("whatsapp_number") or row.get("whatsapp") or "").strip() or None

        if not name and not email:
            skipped += 1
            continue
        if not name:
            name = email or "Unknown"

        # De-duplicate within org by email
        if email:
            exists = await db.scalar(
                select(Contact.id).where(
                    Contact.org_id == org.id,
                    Contact.email == email,
                )
            )
            if exists:
                skipped += 1
                continue

        contact = Contact(
            org_id=org.id,
            name=name,
            email=email,
            phone=phone,
            whatsapp_number=whatsapp,
            source="csv_import",
        )
        db.add(contact)
        imported += 1

        # Batch commit every 100 rows to avoid huge transactions
        if imported % 100 == 0:
            await db.flush()

    await db.commit()

    return {
        "success": True,
        "data": {"imported": imported, "skipped": skipped},
    }


@router_crm.patch("/contacts/{contact_id}/tags", status_code=200)
async def update_contact_tags(
    slug: str,
    contact_id: str,
    db: DBSession,
    org_access: CrmManageAccess,
    tags: list[str] = Body(...),
):
    """Replace the tag list on a contact."""
    from sqlalchemy import select

    from app.models.crm import Contact

    org, role, _ = org_access

    try:
        cid = uuid.UUID(contact_id)
    except ValueError as err:
        raise HTTPException(422, "Invalid contact ID.") from err

    contact = await db.scalar(select(Contact).where(Contact.id == cid, Contact.org_id == org.id))
    if not contact:
        raise HTTPException(404, "Contact not found.")

    clean = [t.strip().lower()[:50] for t in tags if t.strip()][:20]
    contact.tags = clean or None
    await db.commit()
    return {"success": True, "data": {"tags": contact.tags or []}}


@router_crm.get("/contacts")
async def list_contacts(
    slug: str,
    db: DBSession,
    org_access: OrgAccess,
    q: str | None = Query(None),
    page: int = 1,
    per_page: int = 50,
):
    org, role, _ = org_access
    from sqlalchemy import func, or_, select

    from app.models.crm import Contact

    per_page = min(per_page, 100)
    stmt = select(Contact).where(Contact.org_id == org.id)
    if q:
        stmt = stmt.where(
            or_(
                Contact.name.ilike(f"%{q}%"),
                Contact.email.ilike(f"%{q}%"),
            )
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await db.scalars(
        stmt.order_by(Contact.created_at.desc()).offset((page - 1) * per_page).limit(per_page)
    )
    contacts = list(rows.all())
    return {
        "success": True,
        "meta": {"total": total, "page": page, "per_page": per_page},
        "data": [
            {
                "id": str(c.id),
                "name": c.name,
                "email": c.email,
                "phone": c.phone,
                "whatsapp_number": c.whatsapp_number,
                "source": c.source,
                "tags": c.tags or [],
                "is_unsubscribed": c.is_unsubscribed,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in contacts
        ],
    }
