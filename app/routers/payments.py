"""
Payment endpoints — cash/POS recording and Paystack link generation.

TWO ENTRY POINTS, ONE PIPELINE:
- POST /api/v1/payments/cash     → Staff records a cash/POS/transfer payment
- POST /api/v1/payments/initialize → Generate a Paystack payment link

Both flow through the same payment_service.record_payment() pipeline,
so all payment methods get the same balance updates and WhatsApp messages.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FeeRecord, Student
from app.schemas.payment import (
    CashPaymentCreate,
    PaymentInitialize,
    PaymentResponse,
    PaymentLinkResponse,
)
from app.services.payment_service import record_payment
from app.services.paystack import initialize_transaction, generate_reference

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/payments", tags=["Payments"])


@router.post("/cash", response_model=PaymentResponse)
def record_cash_payment(
    payment_data: CashPaymentCreate,
    db: Session = Depends(get_db),
):
    """
    Record a cash, POS, or bank transfer payment.

    This is the "one action" endpoint for school staff:
    - Staff enters: fee_record_id, amount, method, their name
    - System does everything else: update balance, send WhatsApp

    No manual bookkeeping needed.
    """
    try:
        payment = record_payment(
            db=db,
            fee_record_id=payment_data.fee_record_id,
            amount_kobo=payment_data.amount_kobo,
            method=payment_data.method,
            recorded_by=payment_data.recorded_by,
            note=payment_data.note,
        )
        return payment

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/initialize", response_model=PaymentLinkResponse)
async def initialize_payment(
    data: PaymentInitialize,
    db: Session = Depends(get_db),
):
    """
    Generate a Paystack payment link for a parent.

    The link can be sent via WhatsApp so the parent can pay from their phone.
    If amount is not specified, it defaults to the remaining balance.
    """
    # Load the fee record with student info
    fee_record = (
        db.query(FeeRecord)
        .join(FeeRecord.student)
        .filter(FeeRecord.id == data.fee_record_id)
        .first()
    )

    if not fee_record:
        raise HTTPException(status_code=404, detail="Fee record not found")

    student = fee_record.student

    # Default to remaining balance if no amount specified
    amount = data.amount_kobo or fee_record.balance_kobo

    if amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="This fee is already fully paid"
        )

    # Generate a reference that encodes the fee_record_id
    reference = generate_reference(fee_record.id)

    # Use parent email, or create a placeholder
    email = student.parent_email or f"{student.id}@jummikville.sch"

    try:
        paystack_data = await initialize_transaction(
            email=email,
            amount_kobo=amount,
            reference=reference,
            metadata={
                "student_name": student.student_name,
                "parent_name": student.parent_name,
                "fee_record_id": fee_record.id,
            },
        )

        return PaymentLinkResponse(
            authorization_url=paystack_data["authorization_url"],
            reference=paystack_data["reference"],
            amount_kobo=amount,
        )

    except Exception as e:
        logger.error(f"Paystack initialization failed: {e}")
        raise HTTPException(
            status_code=502,
            detail="Failed to generate payment link. Please try again."
        )
