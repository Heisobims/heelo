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


class ManualAccountRequest(BaseModel):
    """A locally-recorded payout account not linked to any payment gateway
    subaccount - for orgs whose bank isn't covered by Paystack/Flutterwave's
    subaccount API, or who want a reference record without an automatic
    split."""

    bank_name: str = Field(..., min_length=2, max_length=255)
    account_number: str = Field(..., min_length=4, max_length=34)
    account_name: str = Field(..., min_length=2, max_length=255)
    bank_code: str | None = Field(None, max_length=50)


class PaymentAccountOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    provider: str
    provider_account_id: str
    account_name: str | None
    bank_name: str | None
    account_number: str | None
    bank_code: str | None = None
    recipient_code: str | None = None
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
