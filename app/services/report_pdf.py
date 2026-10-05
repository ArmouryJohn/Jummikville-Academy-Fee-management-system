"""
PDF generator for term financial summary reports.
"""

import logging
import os

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.schemas.report import TermReportResponse

logger = logging.getLogger(__name__)

# Repo root (three levels up from app/services/report_pdf.py) — same anchor the
# receipt service uses, so the shared logo path resolves identically.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_LOGO_PATH = os.path.join(
    _REPO_ROOT, "frontend", "assets", "images", "jummikville_logo.jpeg"
)

_NL = dict(new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _naira(amount_kobo: int) -> str:
    """Font-safe money for the PDF — 'NGN 75,000.00' (fpdf2 can't render ₦)."""
    return f"NGN {amount_kobo / 100:,.2f}"


from app.utils.formatting import font_safe_text

_safe = font_safe_text


def render_term_report_pdf(report: TermReportResponse) -> bytes:
    """Render the report to PDF bytes (returned inline; never written to disk)."""
    pdf = FPDF(format="A4")
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    _header(pdf, report)
    _totals_block(pdf, report)
    _student_counts(pdf, report)
    _category_table(pdf, report)
    _section_class_tables(pdf, report)
    _method_tables(pdf, report)
    _reminder_line(pdf, report)
    _footer(pdf)

    # fpdf2 returns a bytearray from output() with no dest; normalise to bytes.
    return bytes(pdf.output())


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------
def _header(pdf: FPDF, report: TermReportResponse) -> None:
    if os.path.exists(_LOGO_PATH):
        try:
            logo_w = 20  # mm
            page_w = pdf.w - pdf.l_margin - pdf.r_margin
            x = pdf.l_margin + (page_w - logo_w) / 2
            pdf.image(_LOGO_PATH, x=x, y=pdf.get_y(), w=logo_w)
            pdf.ln(logo_w + 1)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(f"Could not render report logo: {exc}")

    pdf.set_font("Helvetica", "B", 17)
    pdf.cell(0, 9, _safe(report.school_name), align="C", **_NL)

    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "TERM REPORT", align="C", **_NL)

    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, _safe(report.term_name), align="C", **_NL)

    # Dates line (if set) + generated timestamp.
    dates = _date_range(report)
    if dates:
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, _safe(dates), align="C", **_NL)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    gen = report.generated_at.strftime("%d %b %Y, %I:%M %p UTC")
    pdf.cell(0, 5, f"Generated {gen}", align="C", **_NL)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)


def _totals_block(pdf: FPDF, report: TermReportResponse) -> None:
    t = report.totals
    _section_title(pdf, "Summary")

    def line(label: str, value: str) -> None:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(70, 7, label)
        pdf.set_font("Helvetica", "", 11)
        pdf.cell(0, 7, value, **_NL)

    line("Total Expected:", _naira(t.total_expected_kobo))
    line("Total Collected:", _naira(t.total_collected_kobo))
    line("Outstanding:", _naira(t.total_remaining_kobo))
    line("Overpaid (credit):", _naira(t.total_overpaid_kobo))
    line("Collection Rate:", f"{t.collection_rate}%")
    pdf.ln(2)


def _student_counts(pdf: FPDF, report: TermReportResponse) -> None:
    t = report.totals
    _section_title(pdf, "Students")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, f"Total students with fees this term: {t.students_total}", **_NL)
    pdf.cell(
        0, 6,
        f"Paid: {t.students_paid}    Partial: {t.students_partial}    "
        f"Unpaid: {t.students_unpaid}    Overpaid: {t.students_overpaid}",
        **_NL,
    )
    pdf.ln(2)


def _category_table(pdf: FPDF, report: TermReportResponse) -> None:
    _section_title(pdf, "By Fee Category")
    if not report.categories:
        _empty(pdf)
        return
    _table_header(pdf, ["Category", "Expected", "Collected", "Outstanding"], [60, 40, 40, 40])
    for c in report.categories:
        _table_row(
            pdf,
            [_safe(c.category_name), _naira(c.expected_kobo), _naira(c.collected_kobo), _naira(c.remaining_kobo)],
            [60, 40, 40, 40],
        )
    pdf.ln(2)


def _section_class_tables(pdf: FPDF, report: TermReportResponse) -> None:
    _section_title(pdf, "By Section")
    if report.sections:
        _table_header(pdf, ["Section", "Students", "Expected", "Collected", "Outstanding"], [46, 20, 38, 38, 38])
        for s in report.sections:
            _table_row(
                pdf,
                [_safe(s.section), str(s.students), _naira(s.expected_kobo), _naira(s.collected_kobo), _naira(s.remaining_kobo)],
                [46, 20, 38, 38, 38],
            )
    else:
        _empty(pdf)
    pdf.ln(2)

    _section_title(pdf, "By Class")
    if report.classes:
        _table_header(pdf, ["Class", "Students", "Expected", "Collected", "Outstanding"], [46, 20, 38, 38, 38])
        for c in report.classes:
            _table_row(
                pdf,
                [_safe(c.class_name), str(c.students), _naira(c.expected_kobo), _naira(c.collected_kobo), _naira(c.remaining_kobo)],
                [46, 20, 38, 38, 38],
            )
    else:
        _empty(pdf)
    pdf.ln(2)


def _method_tables(pdf: FPDF, report: TermReportResponse) -> None:
    _section_title(pdf, "By Payment Method")
    ch = report.channels
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(
        0, 6,
        f"Online (Paystack): {ch.online_count} payment(s), {_naira(ch.online_amount_kobo)}",
        **_NL,
    )
    pdf.cell(
        0, 6,
        f"Manual (cash/POS/transfer/other): {ch.manual_count} payment(s), {_naira(ch.manual_amount_kobo)}",
        **_NL,
    )
    pdf.ln(1)
    if report.methods:
        _table_header(pdf, ["Method", "Payments", "Amount"], [80, 40, 60])
        for m in report.methods:
            _table_row(pdf, [_safe(m.label), str(m.count), _naira(m.amount_kobo)], [80, 40, 60])
    else:
        _empty(pdf, "No payments recorded for this term yet.")
    pdf.ln(2)


def _reminder_line(pdf: FPDF, report: TermReportResponse) -> None:
    _section_title(pdf, "Reminder Activity")
    r = report.reminders
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, f"Reminders sent: {r.reminders_sent}", **_NL)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 5, _safe(r.note), **_NL)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)


def _footer(pdf: FPDF) -> None:
    pdf.ln(2)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(
        0, 6,
        "Computer-generated report. Figures reflect payments recorded at generation time.",
        align="C", **_NL,
    )
    pdf.set_text_color(0, 0, 0)


# --------------------------------------------------------------------------
# Small rendering helpers
# --------------------------------------------------------------------------
def _section_title(pdf: FPDF, title: str) -> None:
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_fill_color(240, 243, 248)
    pdf.cell(0, 8, title, fill=True, **_NL)
    pdf.ln(1)


def _table_header(pdf: FPDF, cols: list[str], widths: list[int]) -> None:
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(90, 90, 90)
    for i, col in enumerate(cols):
        align = "L" if i == 0 else "R"
        last = i == len(cols) - 1
        pdf.cell(widths[i], 6, col, align=align, **(_NL if last else {}))
    pdf.set_text_color(0, 0, 0)


def _table_row(pdf: FPDF, cells: list[str], widths: list[int]) -> None:
    pdf.set_font("Helvetica", "", 9)
    for i, val in enumerate(cells):
        align = "L" if i == 0 else "R"
        last = i == len(cells) - 1
        pdf.cell(widths[i], 6, val, align=align, **(_NL if last else {}))


def _empty(pdf: FPDF, text: str = "No data.") -> None:
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_text_color(140, 140, 140)
    pdf.cell(0, 6, text, **_NL)
    pdf.set_text_color(0, 0, 0)


def _date_range(report: TermReportResponse) -> str:
    def fmt(d):
        return d.strftime("%d %b %Y")
    if report.term_start_date and report.term_end_date:
        return f"{fmt(report.term_start_date)} - {fmt(report.term_end_date)}"
    if report.term_start_date:
        return f"From {fmt(report.term_start_date)}"
    if report.term_end_date:
        return f"Until {fmt(report.term_end_date)}"
    return ""
