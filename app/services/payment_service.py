"""
Payment service — the shared pipeline for ALL payment methods.

THE GOLDEN RULE OF THIS FILE:
Whether a payment comes from Paystack, cash, POS, or bank transfer,
it goes through the SAME process:
    1. Record the payment in the database
    2. Update the fee record's amount_paid_kobo
    3. Recalculate status (unpaid → partial → paid)
    4. Send WhatsApp confirmation to the parent

ONE CODE PATH = FEWER BUGS.
If you fix a bug here, it's fixed for all payment methods.
If you add a feature here (like logging or receipts), it works for all methods.
"""

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
    """
    Record a payment and update the fee record balance.

    This is THE payment processing function. Every payment method calls this.

    Args:
        db: Database session
        fee_record_id: Which fee record to apply this payment to
        amount_kobo: Payment amount in kobo
        method: 'paystack', 'cash', 'pos', 'bank_transfer', or 'other'
        paystack_reference: Paystack ref (for idempotency — only for Paystack payments)
        recorded_by: Staff label (for cash/POS payments) — defaults to the admin's email
        recorded_by_user_id: id of the authenticated admin who recorded a manual
            payment (null for Paystack/system-initiated payments) — the audit actor
        note: Optional note
        send_confirmation: Whether to send a WhatsApp confirmation

    Returns:
        The created Payment object

    Raises:
        ValueError: If the fee record doesn't exist or the payment is invalid
    """
    # ---- Step 1: Load the fee record with all related data ----
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

    # ---- Step 2: Check for duplicate Paystack payment (idempotency) ----
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
            return existing  # Return the existing payment — don't double-credit

    # ---- Step 3: Create the payment record ----
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

    # ---- Step 4: Attach the payment so the derived balance sees it ----
    # amount_paid_kobo is a computed SUM of this record's Payment rows (see
    # FeeRecord.amount_paid_kobo). We append the new payment to the in-session
    # relationship so recalculate_status() — and every balance read below —
    # counts it immediately, before the commit round-trips to the DB.
    fee_record.payments.append(payment)
    fee_record.recalculate_status()

    # ---- Step 4b: Record this in the activity feed ----
    # Staged (not committed) here so it lands in the SAME transaction as the
    # payment below — the feed entry and the payment succeed or fail together.
    student = fee_record.student
    method_label = {
        "cash": "cash",
        "pos": "POS",
        "bank_transfer": "bank transfer",
        "other": "other",
        "paystack": "Paystack",
    }.get(method, method)
    # Who recorded it — the audit actor. For manual payments this is the staff
    # label (the admin's email by default); Paystack payments are system-driven.
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

    # ---- Step 5: Commit to database ----
    db.commit()
    db.refresh(payment)
    db.refresh(fee_record)

    logger.info(
        f"Payment recorded: {amount_kobo} kobo via {method} "
        f"for fee_record {fee_record_id}. "
        f"New balance: {fee_record.balance_kobo} kobo. "
        f"Status: {fee_record.status}"
    )

    # ---- Step 5b: Generate the receipt PDF (once) and save its URL ----
    # Best-effort, like the WhatsApp send below: the payment is already
    # committed, so a receipt failure must never fail the payment. The URL is
    # the protected download route, saved once so it's stable for re-download.
    if not payment.receipt_url:
        try:
            receipt_service.generate_receipt(payment)
            payment.receipt_url = f"/api/v1/payments/{payment.id}/receipt"
            db.commit()
            db.refresh(payment)
        except Exception as e:
            db.rollback()
            logger.error(f"Receipt generation failed (payment still recorded): {e}")

    # ---- Step 6: Send WhatsApp confirmation ----
    # The message we send depends on where this payment LEFT the fee record:
    #   overpaid → tell them we'll refund the excess
    #   paid     → celebrate completing the fees
    #   otherwise (partial) → the standard "payment received, here's your balance"
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
