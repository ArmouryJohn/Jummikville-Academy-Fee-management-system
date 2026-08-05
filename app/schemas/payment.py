"""
Pydantic schemas for Payment-related API requests and responses.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.utils.formatting import kobo_to_naira


# --------------------------------------------------------------------------
# Request schemas
# --------------------------------------------------------------------------

class CashPaymentCreate(BaseModel):
    """
    Schema for recording a cash/POS/transfer payment by school staff.

    This is the "one action" endpoint: staff enters the amount and who recorded it,
    and the system handles everything else (update balance, send WhatsApp, etc.)
    """
    fee_record_id: int
    amount_kobo: int = Field(
        ..., gt=0,
        examples=[2500000],
        description="Amount received in kobo. ₦25,000 = 2500000"
    )
    method: str = Field(
        default="cash",
        pattern="^(cash|pos|bank_transfer|other)$",
        description="Payment method: 'cash', 'pos', 'bank_transfer', or 'other'"
    )
    recorded_by: str | None = Field(
        None, min_length=2, max_length=200,
        examples=["Mrs. Aniefiok"],
        description=(
            "Optional label for who took the payment. If omitted, the system uses "
            "the logged-in admin's email. The authenticated admin is always recorded "
            "as the audit actor regardless of this field."
        )
    )
    note: str | None = Field(
        None, max_length=500,
        examples=["Paid at school office"],
        description="Optional note about this payment"
    )


class PaymentInitialize(BaseModel):
    """
    Schema for initializing a Paystack payment link.
    The link will be sent to the parent's WhatsApp.
    """
    fee_record_id: int
    amount_kobo: int | None = Field(
        None, gt=0,
        description=(
            "Amount to pay in kobo. If null, defaults to the remaining balance. "
            "This allows partial payments."
        )
    )


# --------------------------------------------------------------------------
# Response schemas
# --------------------------------------------------------------------------

class PaymentResponse(BaseModel):
    """Schema for payment data in API responses."""
    id: int
    fee_record_id: int
    amount_kobo: int
    amount_display: str = ""
    method: str
    paystack_reference: str | None
    recorded_by: str | None
    recorded_by_user_id: int | None = None
    receipt_url: str | None = None
    note: str | None
    paid_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}

    def model_post_init(self, __context) -> None:
        if not self.amount_display:
            self.amount_display = kobo_to_naira(self.amount_kobo)


class PaymentLinkResponse(BaseModel):
    """Response when a Paystack payment link is generated."""
    authorization_url: str = Field(
        ..., description="URL to redirect the parent to for payment"
    )
    reference: str = Field(
        ..., description="Paystack transaction reference"
    )
    amount_kobo: int
    amount_display: str = ""

    def model_post_init(self, __context) -> None:
        if not self.amount_display:
            self.amount_display = kobo_to_naira(self.amount_kobo)
