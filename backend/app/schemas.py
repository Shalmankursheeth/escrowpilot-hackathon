import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _check_email(v: str) -> str:
    v = v.strip().lower()
    if not _EMAIL.match(v) or len(v) > 255:
        raise ValueError("Enter a valid email address")
    return v


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=72)
    role: Literal["buyer", "seller"]
    company_name: str = Field(min_length=2, max_length=255)
    paypal_email: str  # payouts and compensation go here, so both roles need one

    _e = field_validator("email")(_check_email)
    _pp = field_validator("paypal_email")(_check_email)

    @field_validator("password")
    @classmethod
    def _pw(cls, v):
        if len(v.encode()) > 72:
            raise ValueError("Password is too long")
        return v


class LoginIn(BaseModel):
    email: str
    password: str

    _e = field_validator("email")(_check_email)


ProofType = Literal["order_confirmation", "bill_of_lading", "commercial_invoice", "packing_list", "delivery_receipt"]


class MilestoneIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    share_pct: int = Field(gt=0, le=100)
    required_proof: ProofType


class TermsIn(BaseModel):
    """Payment terms one side proposes and the other signs. Includes what happens if delivery fails."""
    total_amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    goods: str | None = Field(default=None, max_length=300)
    quantity: int | None = Field(default=None, gt=0)
    inspection_days: int = Field(default=3, ge=0, le=30)
    milestones: list[MilestoneIn] = Field(min_length=1, max_length=12)
    return_refund_pct: int = Field(default=100, ge=0, le=100)
    return_shipping_by: Literal["seller", "buyer"] = "seller"
    return_proof_required: bool = True
    return_check_days: int = Field(default=5, ge=0, le=30)
    funding_mode: Literal["per_milestone", "upfront"] = "per_milestone"
    release_rule: Literal["on_completion", "per_stage"] = "on_completion"
    failure_scope: Literal["whole_order", "stage"] = "whole_order"
    funding_deadline_days: int = Field(default=7, ge=1, le=90)
    default_penalty_pct: int = Field(default=10, ge=0, le=100)
    seller_deposit_pct: int = Field(default=5, ge=0, le=20)


class ConfirmIn(BaseModel):
    version: int  # the terms version being signed; stale versions are rejected


class ConnectIn(BaseModel):
    public_id: str = Field(min_length=4, max_length=16)

    @field_validator("public_id")
    @classmethod
    def _up(cls, v):
        return v.strip().upper()


class DealCreateIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    counterparty_id: str = Field(min_length=4, max_length=16)
    terms: TermsIn | None = None
    contract_text: str | None = Field(default=None, min_length=20)  # optional: let the AI draft the terms
    inspection_days: int | None = Field(default=None, ge=0, le=30)

    @field_validator("counterparty_id")
    @classmethod
    def _cid(cls, v):
        return v.strip().upper()


class ProofIn(BaseModel):
    """A proof document: pasted text, or an uploaded file (PDF, PNG, JPEG, text) sent as base64."""
    filename: str = Field(min_length=1, max_length=200)
    text: str | None = Field(default=None, min_length=10)
    content_type: str | None = Field(default=None, max_length=100)
    data_b64: str | None = Field(default=None, max_length=8_000_000)

    @model_validator(mode="after")
    def _one(self):
        if not self.text and not self.data_b64:
            raise ValueError("Send the document text or upload a file")
        return self


class DisputeIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class AppealIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class ReturnCheckIn(BaseModel):
    """The seller's check of returned goods: they match what was shipped (ok), or they do not (a note is then required)."""
    ok: bool
    note: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def _note(self):
        if not self.ok and len(self.note.strip()) < 5:
            raise ValueError("Say what is wrong with the returned goods")
        return self


class ReviewIn(BaseModel):
    decision: Literal["approve", "refund", "seller_fault", "buyer_fault"]
    note: str = Field(default="", max_length=1000)
    # The reviewer may settle just this stage or the whole order; unset keeps the scope both sides signed.
    scope: Literal["stage", "whole_order"] | None = None
