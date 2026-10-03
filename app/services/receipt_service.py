"""
Receipt service — renders a one-page PDF receipt for a payment and stores it.

DESIGN:
- One receipt per Payment, generated ONCE. The file is written to
  storage/receipts/receipt-{payment_id}.pdf (repo-root `storage/`, deliberately
  OUTSIDE frontend/ so it is never served as a public static file — downloads go
  through the auth-protected /api/v1/payments/{id}/receipt route).
- Idempotent: if the file already exists we return its path without re-rendering,
  so calling this again (e.g. a webhook retry) never produces a second receipt.

WHY "NGN" NOT "₦":
fpdf2's built-in Helvetica font is latin-1 encoded and cannot render the ₦ glyph
(U+20A6). To keep receipts dependency-free (no bundled TTF), money is written as
"NGN 75,000.00". The rest of the app still uses ₦ for on-screen/WhatsApp display.
"""

import logging
import os

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.models import Payment
from app.utils.formatting import font_safe_text

_safe = font_safe_text

logger = logging.getLogger(__name__)

# Repo root (three levels up from app/services/receipt_service.py).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

# storage/receipts/ at the repo root.
_STORAGE_DIR = os.path.join(_REPO_ROOT, "storage", "receipts")

# School logo drawn at the top of every receipt. Lives in the frontend assets
# folder (the same image the web UI uses); fpdf2 renders JPEG/PNG via Pillow.
_LOGO_PATH = os.path.join(
    _REPO_ROOT, "frontend", "assets", "images", "jummikville_logo.jpeg"
)


def _naira(amount_kobo: int) -> str:
    """Money for the PDF — 'NGN 75,000.00' (font-safe, unlike the ₦ sign)."""
    return f"NGN {amount_kobo / 100:,.2f}"


def receipt_path(payment_id: int) -> str:
    """Absolute path where this payment's receipt PDF lives (may not exist yet)."""
    return os.path.join(_STORAGE_DIR, f"receipt-{payment_id}.pdf")


def generate_receipt(payment: Payment) -> str:
    """
    Render (once) and return the filesystem path to a payment's receipt PDF.

    The payment is expected to be loaded with its fee_record → student → school
    and fee_type relationships reachable (they are, in the record_payment flow).

    Returns:
        Absolute path to the generated (or already-existing) PDF file.
    """
    path = receipt_path(payment.id)

    # Idempotent: never regenerate an existing receipt if valid
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path

    os.makedirs(_STORAGE_DIR, exist_ok=True)

    fee_record = payment.fee_record
    student = fee_record.student
    school = student.school
    fee_type = fee_record.fee_type

    pdf = FPDF(format="A4")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # ---- Header ----
    # _NL = the modern fpdf2 way to say "move to the next line after this cell".
    _NL = dict(new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Logo, centred at the top. Best-effort: a missing/unreadable image must never
    # break receipt generation, so we swallow any error and carry on text-only.
    if os.path.exists(_LOGO_PATH):
        try:
            logo_w = 22  # mm
            page_w = pdf.w - pdf.l_margin - pdf.r_margin
            x = pdf.l_margin + (page_w - logo_w) / 2
            pdf.image(_LOGO_PATH, x=x, y=pdf.get_y(), w=logo_w)
            pdf.ln(logo_w + 2)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Could not render receipt logo: {exc}")

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, _safe(school.name if school else "Jummikville Academy"), align="C", **_NL)
    pdf.set_font("Helvetica", "", 10)
    if school and school.address:
        # Address can be long — wrap it instead of clipping to one line.
        pdf.multi_cell(0, 5, _safe(school.address), align="C", **_NL)
    if school and school.phone:
        pdf.cell(0, 5, _safe(f"Tel: {school.phone}"), align="C", **_NL)
    if school and school.email:
        pdf.cell(0, 5, _safe(f"Email: {school.email}"), align="C", **_NL)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "PAYMENT RECEIPT", align="C", **_NL)
    pdf.ln(2)

    # ---- Meta line: receipt no. + date ----
    pdf.set_font("Helvetica", "", 11)
    paid_at = payment.paid_at.strftime("%d %b %Y, %I:%M %p") if payment.paid_at else ""
    pdf.cell(0, 7, f"Receipt No: JMK-RCP-{payment.id:06d}", **_NL)
    pdf.cell(0, 7, _safe(f"Date: {paid_at}"), **_NL)
    pdf.ln(2)

    # ---- Body rows ----
    def row(label: str, value: str) -> None:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(60, 8, label)
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 8, _safe(value), **_NL)

    row("Student:", student.student_name)
    if student.class_name:
        row("Class:", f"{student.section} / {student.class_name}")
    else:
        row("Section:", student.section)
    row("Parent/Guardian:", student.parent_name or "-")
    row("Fee:", f"{fee_type.name} ({fee_type.term})")
    row("Method:", payment.method.replace("_", " ").title())
    if payment.paystack_reference:
        row("Reference:", payment.paystack_reference)
    row("Recorded by:", payment.recorded_by or ("Paystack" if payment.method == "paystack" else "System"))
    if payment.note:
        row("Note:", payment.note)
    pdf.ln(2)

    # ---- Amounts ----
    pdf.set_draw_color(180, 180, 180)
    pdf.line(pdf.get_x(), pdf.get_y(), 200, pdf.get_y())
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(60, 9, "Amount Paid:")
    pdf.cell(0, 9, _naira(payment.amount_kobo), **_NL)

    pdf.set_font("Helvetica", "", 11)
    row("Total Paid (this fee):", _naira(fee_record.amount_paid_kobo))
    row("Total Fee:", _naira(fee_record.total_fees_kobo))
    if fee_record.overpaid_kobo > 0:
        row("Overpaid (credit):", _naira(fee_record.overpaid_kobo))
    else:
        row("Balance Remaining:", _naira(fee_record.remaining_kobo))
    pdf.ln(6)

    # ---- Footer ----
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(
        0, 6,
        "This is a computer-generated receipt and is valid without a signature.",
        align="C", **_NL,
    )

    pdf.output(path)
    logger.info(f"Receipt generated: {path}")
    return path
