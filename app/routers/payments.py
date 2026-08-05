"""
Payment endpoints — cash/POS recording and Paystack link generation.

TWO ENTRY POINTS, ONE PIPELINE:
- POST /api/v1/payments/cash     → Staff records a cash/POS/transfer payment
- POST /api/v1/payments/initialize → Generate a Paystack payment link

Both flow through the same payment_service.record_payment() pipeline,
so all payment methods get the same balance updates and WhatsApp messages.
"""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Form
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import FeeRecord, Student, Payment, User
from app.schemas.payment import (
    CashPaymentCreate,
    PaymentInitialize,
    PaymentResponse,
    PaymentLinkResponse,
)
from app.services.auth_deps import get_current_user
from app.services.payment_service import record_payment
from app.services import receipt_service
from app.services.paystack import initialize_transaction, generate_reference, parse_fee_record_id_from_reference
from app.utils.formatting import kobo_to_naira

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1/payments", tags=["Payments"])


@router.post("/cash", response_model=PaymentResponse)
def record_cash_payment(
    payment_data: CashPaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Record a cash, POS, bank transfer, or other manual payment.

    This is the "one action" endpoint for school staff:
    - Staff enters: fee_record_id, amount, method (and optionally a note)
    - System does everything else: record the payment, update the derived balance,
      capture WHO recorded it (the logged-in admin) for the audit trail, generate
      the receipt, and send the WhatsApp confirmation.

    The audit actor is the authenticated admin — `recorded_by_user_id` is set from
    the session, and `recorded_by` defaults to the admin's email when no explicit
    label is supplied. This makes every manual payment traceable to a real account.
    """
    try:
        payment = record_payment(
            db=db,
            fee_record_id=payment_data.fee_record_id,
            amount_kobo=payment_data.amount_kobo,
            method=payment_data.method,
            recorded_by=payment_data.recorded_by or current_user.email,
            recorded_by_user_id=current_user.id,
            note=payment_data.note,
        )
        return payment

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{payment_id}/receipt")
def download_receipt(payment_id: int, db: Session = Depends(get_db)):
    """
    Download the PDF receipt for a payment.

    Protected (the whole router requires a valid session). The receipt is normally
    generated when the payment is recorded; if the file is missing for any reason
    we regenerate it on demand so this route always returns a receipt for a real
    payment.
    """
    payment = (
        db.query(Payment)
        .options(
            joinedload(Payment.fee_record)
            .joinedload(FeeRecord.student)
            .joinedload(Student.school),
            joinedload(Payment.fee_record).joinedload(FeeRecord.fee_type),
        )
        .filter(Payment.id == payment_id)
        .first()
    )
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    path = receipt_service.receipt_path(payment.id)
    if not os.path.exists(path):
        path = receipt_service.generate_receipt(payment)

    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"receipt-JMK-{payment.id:06d}.pdf",
    )


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
        err_msg = str(e)
        if hasattr(e, "response") and getattr(e, "response") is not None:
            try:
                err_msg = e.response.json().get("message", str(e))
            except Exception:
                pass
        raise HTTPException(
            status_code=502,
            detail=f"Failed to generate payment link: {err_msg}"
        )

