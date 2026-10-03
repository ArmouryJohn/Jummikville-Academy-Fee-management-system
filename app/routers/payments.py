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

from fastapi import APIRouter, Depends, HTTPException, Query
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
from app.services import receipt_service, twilio_wa
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
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        try:
            path = receipt_service.generate_receipt(payment)
        except Exception as exc:
            logger.error(f"Receipt generation failed for payment {payment.id}: {exc}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Could not generate receipt PDF. Please try again.",
            )

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

    # Paystack requires an email address on initialize. If the parent doesn't have
    # an email recorded, supply a standard deterministic placeholder
    # so staff NEVER need to add a parent email just to generate a payment link.
    email = (student.parent_email or "").strip()
    if not email or "@" not in email:
        email = f"parent.{student.id}@jummikville.com"

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

        auth_url = paystack_data["authorization_url"]

        # Automatically send the payment link via WhatsApp to the parent
        if student.parent_phone:
            try:
                fee_name = fee_record.fee_type.name if fee_record.fee_type else "School Fee"
                amount_display = kobo_to_naira(amount)
                twilio_wa.send_payment_link_whatsapp(
                    parent_name=student.parent_name,
                    student_name=student.student_name,
                    parent_phone=student.parent_phone,
                    fee_name=fee_name,
                    amount_display=amount_display,
                    payment_link=auth_url,
                    school_name=student.school.name if student.school else "Jummikville Academy",
                )
            except Exception as wa_err:
                logger.warning(f"WhatsApp link dispatch failed: {wa_err}")

        return PaymentLinkResponse(
            authorization_url=auth_url,
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


@router.get("/mock-checkout-page/{reference}", response_class=HTMLResponse)
def mock_checkout_page(
    reference: str,
    amount: int = 0,
    db: Session = Depends(get_db),
):
    """
    Local development mock Paystack checkout page.

    Renders a realistic Paystack payment checkout page so parents/admins can test
    online payment flows in local dev mode without live Paystack secrets.
    """
    fee_record_id = parse_fee_record_id_from_reference(reference)
    fee_record = None
    if fee_record_id:
        fee_record = (
            db.query(FeeRecord)
            .options(
                joinedload(FeeRecord.student),
                joinedload(FeeRecord.fee_type),
            )
            .filter(FeeRecord.id == fee_record_id)
            .first()
        )

    student_name = fee_record.student.student_name if (fee_record and fee_record.student) else "Student"
    fee_name = fee_record.fee_type.name if (fee_record and fee_record.fee_type) else "School Fee"
    amount_display = kobo_to_naira(amount) if amount > 0 else (fee_record.remaining_display if fee_record else "₦0.00")

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Paystack Checkout — Jummikville Academy</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
</head>
<body class="bg-slate-900 font-sans min-h-screen flex items-center justify-center p-4">
    <div class="w-full max-w-md bg-white rounded-2xl shadow-2xl overflow-hidden border border-slate-100">
        <!-- Paystack Header -->
        <div class="bg-slate-900 p-6 text-white text-center border-b border-slate-800">
            <div class="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-teal-500/20 text-teal-400 mb-3 text-xl font-bold">
                J
            </div>
            <h2 class="text-lg font-bold">Jummikville Academy</h2>
            <p class="text-xs text-slate-400 mt-0.5">Online Fee Checkout (Demo Sandbox)</p>
            <div class="mt-4 bg-slate-800/80 rounded-xl p-3 text-center border border-slate-700/50">
                <span class="text-xs text-slate-400 block uppercase tracking-wider font-semibold">Amount to Pay</span>
                <span class="text-2xl font-bold text-teal-400">{amount_display}</span>
            </div>
        </div>

        <!-- Body Details -->
        <div class="p-6 space-y-4">
            <div class="rounded-xl bg-slate-50 p-4 space-y-2 text-sm text-slate-600">
                <div class="flex justify-between"><span class="text-slate-400">Student:</span><span class="font-semibold text-slate-800">{student_name}</span></div>
                <div class="flex justify-between"><span class="text-slate-400">Fee Category:</span><span class="font-semibold text-slate-800">{fee_name}</span></div>
                <div class="flex justify-between"><span class="text-slate-400">Reference:</span><span class="font-mono text-xs text-slate-500">{reference}</span></div>
            </div>

            <form action="/api/v1/payments/mock-checkout-page/{reference}/pay?amount_kobo={amount}" method="POST">
                <button type="submit" class="w-full py-3.5 bg-teal-500 hover:bg-teal-600 text-white font-semibold rounded-xl shadow-lg shadow-teal-500/25 transition flex items-center justify-center gap-2">
                    🔒 Pay {amount_display} (Simulate Success)
                </button>
            </form>
            <p class="text-center text-xs text-slate-400">Demo checkout sandbox. Clicking pay records this transaction automatically.</p>
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_content)


@router.post("/mock-checkout-page/{reference}/pay", response_class=HTMLResponse)
def complete_mock_checkout(
    reference: str,
    amount_kobo: int = 0,
    db: Session = Depends(get_db),
):

    """
    Simulate successful Paystack payment for local dev mode.
    """
    fee_record_id = parse_fee_record_id_from_reference(reference)
    if not fee_record_id:
        raise HTTPException(status_code=400, detail="Invalid reference format")

    fee_record = (
        db.query(FeeRecord)
        .options(joinedload(FeeRecord.student))
        .filter(FeeRecord.id == fee_record_id)
        .first()
    )
    if not fee_record:
        raise HTTPException(status_code=404, detail="Fee record not found")

    pay_amount = amount_kobo if amount_kobo > 0 else fee_record.balance_kobo
    if pay_amount <= 0:
        pay_amount = fee_record.total_fees_kobo

    payment = record_payment(
        db=db,
        fee_record_id=fee_record.id,
        amount_kobo=pay_amount,
        method="paystack",
        recorded_by="Paystack Checkout (Online)",
        note=f"Paystack payment completed via reference {reference}",
        paystack_reference=reference,
    )

    amount_display = kobo_to_naira(payment.amount_kobo)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Payment Successful — Jummikville Academy</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
</head>
<body class="bg-slate-900 font-sans min-h-screen flex items-center justify-center p-4">
    <div class="w-full max-w-md bg-white rounded-2xl shadow-2xl p-6 text-center space-y-5 border border-slate-100">
        <div class="w-16 h-16 bg-emerald-100 text-emerald-600 rounded-full flex items-center justify-center mx-auto text-3xl font-bold">
            ✓
        </div>
        <h2 class="text-xl font-bold text-slate-900">Payment Successful!</h2>
        <p class="text-sm text-slate-500">
            Payment of <strong class="text-slate-800">{amount_display}</strong> for <strong>{fee_record.student.student_name}</strong> has been received and confirmed.
        </p>

        <div class="rounded-xl bg-slate-50 p-4 text-xs text-slate-500 text-left space-y-1">
            <p>✓ Receipt PDF generated & stored</p>
            <p>✓ Student balance updated automatically</p>
            <p>✓ WhatsApp confirmation sent to parent</p>
        </div>

        <div class="space-y-2 pt-2">
            <a href="/api/v1/payments/{payment.id}/receipt" target="_blank"
               class="block w-full py-3 bg-teal-600 hover:bg-teal-700 text-white font-semibold rounded-xl text-sm transition">
               📄 Download PDF Receipt
            </a>
            <a href="/"
               class="block w-full py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold rounded-xl text-sm transition">
               Return to App Dashboard
            </a>
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html_content)


