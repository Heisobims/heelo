from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class PaystackSubaccountRequest(BaseModel):
    account_number: str = Field(..., min_length=10, max_length=20)
    bank_code: str = Field(..., min_length=3, max_length=10)
    business_name: str | None = Field(None, max_length=255)
    contact_email: EmailStr | None = None


class FlutterwaveSubaccountRequest(BaseModel):
    account_number: str = Field(..., min_length=10, max_length=20)
    bank_code: str = Field(..., min_length=3, max_length=10)
    business_name: str | None = Field(None, max_length=255)
    country: str = Field("NG", min_length=2, max_length=2)


class PaymentAccountOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    provider: str
    provider_account_id: str
    account_name: str | None
    bank_name: str | None
    account_number: str | None
    is_verified: bool
    is_default: bool
    currency: str
    instant_settlement: bool


class BankOut(BaseModel):
    id: int | None = None
    name: str
    code: str
    currency: str = "NGN"


class PaymentInitResult(BaseModel):
    payment_url: str
    reference: str
    provider: Literal["paystack", "flutterwave", "stripe"]
