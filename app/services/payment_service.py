"""Payment processing service for handling online and offline school fee payments."""

import logging

from sqlalchemy.orm import Session, joinedload

from app.models import FeeRecord, Payment, Student
from app.services import twilio_wa
from app.services import receipt_service
from app.services.activity_service import log_activity
from app.utils.formatting import kobo_to_naira

logger = logging.getLogger(__name__)


def record_payment(
    db: Session,
    fee_record_id: int,
    amount_kobo: int,
    method: str,
    paystack_reference: str | None = None,
    recorded_by: str | None = None,
    recorded_by_user_id: int | None = None,
    note: str | None = None,
    send_confirmation: bool = True,
) -> Payment:
    """Record a payment and update fee record balance."""
    # Load fee record and relationships
    fee_record = (
        db.query(FeeRecord)
        .options(
            joinedload(FeeRecord.student).joinedload(Student.school),
            joinedload(FeeRecord.fee_type),
        )
        .filter(FeeRecord.id == fee_record_id)
        .first()
    )

    if not fee_record:
        raise ValueError(f"Fee record {fee_record_id} not found")

    if amount_kobo <= 0:
        raise ValueError("Payment amount must be greater than zero")

    # Prevent duplicate recording for Paystack transactions
    if paystack_reference:
        existing = (
            db.query(Payment)
            .filter(Payment.paystack_reference == paystack_reference)
            .first()
        )
        if existing:
            logger.info(
                f"Duplicate Paystack payment skipped: ref={paystack_reference}"
            )
            return existing

    # Create payment record
    payment = Payment(
        fee_record_id=fee_record_id,
        amount_kobo=amount_kobo,
        method=method,
        paystack_reference=paystack_reference,
        recorded_by=recorded_by,
        recorded_by_user_id=recorded_by_user_id,
        note=note,
    )
    db.add(payment)

    # Update in-memory relationship and recalculate status
    fee_record.payments.append(payment)
    fee_record.recalculate_status()

    # Log payment activity
    student = fee_record.student
    method_label = {
        "cash": "cash",
        "pos": "POS",
        "bank_transfer": "bank transfer",
        "other": "other",
        "paystack": "Paystack",
    }.get(method, method)
    actor = recorded_by or ("Paystack" if method == "paystack" else "system")
    log_activity(
        db=db,
        school_id=student.school_id,
        student_id=student.id,
        action="payment_recorded",
        description=(
            f"Payment confirmed for {student.student_name} — "
            f"{kobo_to_naira(amount_kobo)} received via {method_label} "
            f"(recorded by {actor})"
        ),
    )

    # Commit payment
    db.commit()
    db.refresh(payment)
    db.refresh(fee_record)

    logger.info(
        f"Payment recorded: {amount_kobo} kobo via {method} "
        f"for fee_record {fee_record_id}. "
        f"New balance: {fee_record.balance_kobo} kobo. "
        f"Status: {fee_record.status}"
    )

    # Generate receipt PDF
    if not payment.receipt_url:
        try:
            receipt_service.generate_receipt(payment)
            payment.receipt_url = f"/api/v1/payments/{payment.id}/receipt"
            db.commit()
            db.refresh(payment)
        except Exception as e:
            db.rollback()
            logger.error(f"Receipt generation failed (payment still recorded): {e}")

    # Send WhatsApp confirmation to parent
    if send_confirmation:
        try:
            fee_type = fee_record.fee_type
            school = student.school

            if fee_record.status == "overpaid":
                twilio_wa.send_overpaid_message(
                    parent_name=student.parent_name,
                    student_name=student.student_name,
                    parent_phone=student.parent_phone,
                    amount_paid_kobo=amount_kobo,
                    fee_name=fee_type.name,
                    fee_term=fee_type.term,
                    total_paid_kobo=fee_record.amount_paid_kobo,
                    overpaid_kobo=fee_record.overpaid_kobo,
                    school_name=school.name,
                )
            elif fee_record.status == "paid":
                twilio_wa.send_completion_message(
                    parent_name=student.parent_name,
                    student_name=student.student_name,
                    parent_phone=student.parent_phone,
                    amount_paid_kobo=amount_kobo,
                    fee_name=fee_type.name,
                    fee_term=fee_type.term,
                    total_paid_kobo=fee_record.amount_paid_kobo,
                    school_name=school.name,
                )
            else:
                twilio_wa.send_payment_confirmation(
                    parent_name=student.parent_name,
                    student_name=student.student_name,
                    parent_phone=student.parent_phone,
                    amount_paid_kobo=amount_kobo,
                    fee_name=fee_type.name,
                    fee_term=fee_type.term,
                    total_paid_kobo=fee_record.amount_paid_kobo,
                    balance_kobo=fee_record.balance_kobo,
                    school_name=school.name,
                )
        except Exception as e:
            # Don't fail the payment if WhatsApp fails
            # The payment is already recorded — the message is a nice-to-have
            logger.error(f"WhatsApp confirmation failed (payment still recorded): {e}")

    return payment


def check_duplicate_reference(db: Session, reference: str) -> bool:
    """
    Check if a Paystack reference has already been recorded.

    Used by the webhook handler to quickly check before processing.
    """
    return (
        db.query(Payment)
        .filter(Payment.paystack_reference == reference)
        .first()
    ) is not None
