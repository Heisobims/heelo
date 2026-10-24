from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, computed_field, field_validator, model_validator


class TicketTypeCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    price: Decimal = Field(Decimal("0"), ge=0)
    currency: str = Field("NGN", min_length=3, max_length=3)
    quantity: int | None = Field(None, gt=0)
    tier: Literal["free", "general", "early_bird", "vip", "group"] = "general"
    sale_start: datetime | None = None
    sale_end: datetime | None = None
    max_per_order: int = Field(10, ge=1, le=100)
    min_per_order: int = Field(1, ge=1)
    is_visible: bool = True
    sort_order: int = 0

    @field_validator("price", mode="before")
    @classmethod
    def coerce_price(cls, v):
        return Decimal(str(v))

    @model_validator(mode="after")
    def check_free_tier(self):
        if self.tier == "free" and self.price > Decimal("0"):
            raise ValueError("Free tier tickets must have a price of 0.")
        if self.price == Decimal("0"):
            self.tier = "free"
        return self


class TicketTypeUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    price: Decimal | None = Field(None, ge=0)
    currency: str | None = Field(None, min_length=3, max_length=3)
    quantity: int | None = Field(None, gt=0)
    tier: Literal["free", "general", "early_bird", "vip", "group"] | None = None
    sale_start: datetime | None = None
    sale_end: datetime | None = None
    max_per_order: int | None = Field(None, ge=1, le=100)
    min_per_order: int | None = Field(None, ge=1)
    is_visible: bool | None = None
    sort_order: int | None = None


class TicketTypeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    event_id: uuid.UUID
    name: str
    description: str | None
    price: Decimal
    currency: str
    quantity: int | None
    quantity_sold: int
    quantity_reserved: int
    tier: str
    sale_start: datetime | None
    sale_end: datetime | None
    is_visible: bool
    max_per_order: int
    min_per_order: int
    sort_order: int
    created_at: datetime

    @computed_field
    @property
    def quantity_available(self) -> int | None:
        if self.quantity is None:
            return None
        return max(0, self.quantity - self.quantity_sold - self.quantity_reserved)

    @computed_field
    @property
    def is_sold_out(self) -> bool:
        if self.quantity is None:
            return False
        return self.quantity_sold + self.quantity_reserved >= self.quantity

    @computed_field
    @property
    def is_on_sale(self) -> bool:
        now = datetime.now(UTC)
        if self.sale_start and self.sale_start.tzinfo and now < self.sale_start:
            return False
        if self.sale_end and self.sale_end.tzinfo and now > self.sale_end:
            return False
        return True


class FormFieldCreateRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=500)
    field_type: Literal["short_text", "long_text", "dropdown", "multi_select", "checkbox"] = (
        "short_text"
    )
    is_required: bool = False
    options: list[str] | None = None
    sort_order: int = 0
    applies_to_ticket_type_ids: list[uuid.UUID] | None = None


class FormFieldUpdateRequest(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=500)
    field_type: (
        Literal["short_text", "long_text", "dropdown", "multi_select", "checkbox"] | None
    ) = None
    is_required: bool | None = None
    options: list[str] | None = None
    sort_order: int | None = None
    applies_to_ticket_type_ids: list[uuid.UUID] | None = None


class FormFieldOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    label: str
    field_type: str
    is_required: bool
    options: list[str] | None
    sort_order: int
    applies_to_ticket_type_ids: list[uuid.UUID] | None = None


class PromoCodeCreateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    discount_type: Literal["percent", "fixed"] = "percent"
    discount_value: Decimal = Field(..., gt=0)
    max_uses: int | None = Field(None, gt=0)
    expires_at: datetime | None = None
    applicable_ticket_type_ids: list[uuid.UUID] | None = None

    @field_validator("code", mode="before")
    @classmethod
    def uppercase_code(cls, v):
        return str(v).strip().upper()

    @field_validator("discount_value", mode="before")
    @classmethod
    def coerce_discount(cls, v):
        return Decimal(str(v))


class PromoCodeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    code: str
    discount_type: str
    discount_value: Decimal
    max_uses: int | None
    used_count: int
    expires_at: datetime | None
    is_active: bool


class OrderItemRequest(BaseModel):
    ticket_type_id: uuid.UUID
    quantity: int = Field(..., ge=1, le=50)


class PromoValidateRequest(BaseModel):
    code: str
    items: list[OrderItemRequest]


class PromoValidateResponse(BaseModel):
    valid: bool
    discount_type: str | None = None
    discount_value: Decimal | None = None
    discount_amount: Decimal = Decimal("0")
    message: str = ""


class AttendeeDetail(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    phone: str | None = Field(None, max_length=30)


class RegisterRequest(BaseModel):
    buyer_name: str = Field(..., min_length=1, max_length=255)
    buyer_email: EmailStr
    buyer_phone: str | None = Field(None, max_length=30)
    # Opt-in to receive ticket delivery, reminders, and support replies via WhatsApp
    whatsapp_consent: bool = False
    items: list[OrderItemRequest] = Field(..., min_length=1)
    attendees: list[AttendeeDetail] | None = None
    form_answers: dict[str, str] = Field(default_factory=dict)
    promo_code: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    referral_code: str | None = None
    # Corporate invoicing & VAT compliance
    is_corporate: bool = False
    company_name: str | None = Field(None, max_length=255)
    tax_id: str | None = Field(None, max_length=100)
    billing_address: str | None = None


class RegistrationOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    event_id: uuid.UUID
    ticket_type_id: uuid.UUID
    attendee_name: str
    attendee_email: str
    attendee_phone: str | None
    qr_code: str
    status: str
    ticket_type_name: str | None = None


class OrderOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    event_id: uuid.UUID
    buyer_name: str | None
    buyer_email: str
    total_amount: Decimal
    net_amount: Decimal
    platform_fee: Decimal = Decimal("0")
    fees_passed_to_buyer: bool = False
    currency: str
    payment_status: str
    payment_provider: str | None
    discount_amount: Decimal
    is_corporate: bool = False
    company_name: str | None = None
    tax_id: str | None = None
    billing_address: str | None = None
    registrations: list[RegistrationOut] = Field(default_factory=list)
    payment_url: str | None = None
    invoice_url: str | None = None
    recovery_token: str | None = None


class WaitlistJoinRequest(BaseModel):
    ticket_type_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    phone: str | None = Field(None, max_length=30, description="Optional - for WhatsApp notice")


class WaitlistOut(BaseModel):
    id: uuid.UUID
    ticket_type_id: uuid.UUID
    ticket_type_name: str | None
    name: str
    email: str
    phone: str | None
    position: int
    notified_at: datetime | None
    offer_expires_at: datetime | None
    created_at: datetime
