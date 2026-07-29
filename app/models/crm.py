from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean, ForeignKey, Index, String,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin


class Contact(Base, TimestampMixin):
    """Org-scoped contact imported via CSV or created manually."""

    __tablename__ = "contacts"
    __table_args__ = (
        Index("ix_contacts_org_email", "org_id", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    whatsapp_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # csv_import | manual
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String(100)), nullable=True)
    is_unsubscribed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return f"<Contact {self.email or self.name}>"
