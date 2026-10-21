from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.organization import Organization
from app.models.ticketing import Registration
from app.utils.certificate_pdf import CertificateData, generate_certificate_pdf


async def generate_certificates(db: AsyncSession, event: Event) -> Event:
    """Mark certificates as available for this event's attendees. Certificates
    are generated on-the-fly per download (same pattern as badges/OG images),
    so this is purely an availability gate - nothing is rendered here."""
    if event.status != "ended":
        raise HTTPException(400, "Certificates can only be generated once the event has ended.")

    event.certificates_generated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(event)
    return event


def _certificate_data(reg: Registration, org: Organization) -> CertificateData:
    return CertificateData(
        attendee_name=reg.attendee_name,
        event_title=reg.event.title if reg.event else "",
        org_name=org.name,
        event_date=reg.event.start_datetime if reg.event else datetime.now(UTC),
        brand_color=org.display_brand_color,
        show_powered_by=org.show_powered_by,
    )


async def get_certificate_pdf_for_registration(db: AsyncSession, reg: Registration) -> bytes:
    if not reg.event:
        raise HTTPException(404, "Event not found.")
    if not reg.event.certificates_generated_at:
        raise HTTPException(403, "Certificates aren't available for this event yet.")
    if reg.status != "checked_in":
        raise HTTPException(403, "Only checked-in attendees can download a certificate.")

    org = await db.scalar(select(Organization).where(Organization.id == reg.event.org_id))
    if not org:
        raise HTTPException(404, "Organization not found.")

    return generate_certificate_pdf([_certificate_data(reg, org)])


async def get_certificates_pdf_for_event(
    db: AsyncSession, event: Event, org: Organization
) -> bytes:
    from sqlalchemy.orm import selectinload

    if not event.certificates_generated_at:
        raise HTTPException(400, "Generate certificates for this event first.")

    regs = await db.scalars(
        select(Registration)
        .where(Registration.event_id == event.id, Registration.status == "checked_in")
        .options(selectinload(Registration.event))
        .order_by(Registration.attendee_name)
    )
    registrations = list(regs.all())
    if not registrations:
        raise HTTPException(404, "No checked-in attendees to generate certificates for.")

    certs = [_certificate_data(r, org) for r in registrations]
    return generate_certificate_pdf(certs)
