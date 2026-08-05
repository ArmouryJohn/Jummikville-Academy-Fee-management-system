"""
Payroll PDF service — generates official PDF payslip receipts for staff salary payments.
"""

import logging
import os

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.models import Payroll

logger = logging.getLogger(__name__)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_STORAGE_DIR = os.path.join(_REPO_ROOT, "storage", "payslips")
_LOGO_PATH = os.path.join(
    _REPO_ROOT, "frontend", "assets", "images", "jummikville_logo.jpeg"
)


def _naira(amount_kobo: int) -> str:
    """Money for the PDF — 'NGN 100,000.00' (font-safe, unlike ₦)."""
    return f"NGN {amount_kobo / 100:,.2f}"


def payslip_path(payroll_id: int) -> str:
    """Absolute path where this payroll's payslip PDF lives."""
    return os.path.join(_STORAGE_DIR, f"payslip-{payroll_id}.pdf")


def generate_payslip(payroll: Payroll) -> str:
    """
    Render a one-page PDF payslip for a staff salary payment model instance.
    """
    os.makedirs(_STORAGE_DIR, exist_ok=True)
    target = payslip_path(payroll.id)
    if os.path.isfile(target):
        return target

    return generate_payslip_pdf_file(
        target_path=target,
        payslip_id=payroll.id,
        staff_name=payroll.staff_name,
        amount_kobo=payroll.amount_kobo,
        payment_date=payroll.payment_date.strftime("%B %d, %Y") if payroll.payment_date else "N/A",
        term_name=payroll.term.name if payroll.term else "N/A",
        school_name=payroll.school.name if payroll.school else "Jummikville Academy",
        processed_by=payroll.processed_by_user.email if payroll.processed_by_user else "Management",
        note=payroll.note or "Salary Payment",
        phone_number=payroll.phone_number,
    )


def generate_payslip_pdf(
    payslip_id: int,
    staff_name: str,
    amount_kobo: int,
    payment_date: str,
    term_name: str | None = None,
    school_name: str = "Jummikville Academy",
) -> bytes:
    """
    Generate payslip PDF as bytes.
    """
    pdf = FPDF()
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    if os.path.isfile(_LOGO_PATH):
        try:
            pdf.image(_LOGO_PATH, x=15, y=14, w=22)
            pdf.set_x(42)
        except Exception:
            pdf.set_x(15)
    else:
        pdf.set_x(15)

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 7, school_name, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_x(42 if os.path.isfile(_LOGO_PATH) else 15)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(
        0, 5,
        "29c Udo Ekot Street, Mbiaobong Ikot Antem, Uyo, Akwa Ibom State, Nigeria",
        new_x=XPos.LMARGIN, new_y=YPos.NEXT
    )
    pdf.ln(8)

    pdf.set_fill_color(30, 58, 138)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 10, "  OFFICIAL SALARY PAYSLIP / PAYMENT RECEIPT", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(6)

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 10)

    items = [
        ("Payslip Reference:", f"PAY-{payslip_id:05d}"),
        ("Staff Name:", staff_name),
        ("Academic Term:", term_name or "N/A"),
        ("Payment Date:", payment_date),
        ("Amount Paid:", _naira(amount_kobo)),
    ]

    for label, val in items:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(55, 7, label)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 7, str(val), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(12)

    pdf.set_fill_color(240, 253, 244)
    pdf.set_draw_color(22, 163, 74)
    pdf.set_line_width(0.5)
    pdf.rect(15, pdf.get_y(), 180, 16, style="DF")
    pdf.set_y(pdf.get_y() + 4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(22, 101, 52)
    pdf.cell(180, 8, f"TOTAL AMOUNT CONFIRMED:  {_naira(amount_kobo)}", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(20)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, "This is an official computer-generated payslip issued by Jummikville Academy Management.", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    return bytes(pdf.output())


def generate_payslip_pdf_file(
    target_path: str,
    payslip_id: int,
    staff_name: str,
    amount_kobo: int,
    payment_date: str,
    term_name: str | None = None,
    school_name: str = "Jummikville Academy",
    processed_by: str = "Management",
    note: str = "Salary Payment",
    phone_number: str = "",
) -> str:
    pdf_bytes = generate_payslip_pdf(
        payslip_id=payslip_id,
        staff_name=staff_name,
        amount_kobo=amount_kobo,
        payment_date=payment_date,
        term_name=term_name,
        school_name=school_name,
    )
    with open(target_path, "wb") as f:
        f.write(pdf_bytes)
    return target_path
