"""
Term report endpoints (Part B) — the downloadable/printable term snapshot.

Three views of the SAME numbers (all built by report_service.build_term_report,
the single source of truth, so they can never disagree):
- GET /api/v1/reports/terms/{term_id}            → JSON (on-screen preview)
- GET /api/v1/reports/terms/{term_id}/export.csv → CSV  (spreadsheets/accounting)
- GET /api/v1/reports/terms/{term_id}/export.pdf → PDF  (printing/sharing)

The whole router is auth-gated at include time in app/main.py (dependencies=_auth),
exactly like the dashboard — so every endpoint here requires a valid session.
"""

import csv
import io
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.report import TermReportResponse, TermComparisonResponse
from app.services.report_service import build_term_report, compare_terms, ReportError
from app.services.report_pdf import render_term_report_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])


# Jummikville is single-school (the frontend hardcodes CONFIG.SCHOOL_ID = 1); the
# school_id query param defaults to it so the UI need not pass it.
_DEFAULT_SCHOOL_ID = 1


def _build(db: Session, term_id: int, school_id: int) -> TermReportResponse:
    """Build the report or raise a 404 — shared by all three endpoints."""
    try:
        return build_term_report(db, school_id=school_id, term_id=term_id)
    except ReportError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


def _slug(text: str) -> str:
    """Filesystem-safe slug for the download filename, e.g. 'first-term-2025-2026'."""
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return s or "term"


@router.get("/terms/{term_id}", response_model=TermReportResponse)
def get_term_report(
    term_id: int,
    school_id: int = Query(_DEFAULT_SCHOOL_ID, description="School id (defaults to Jummikville)"),
    db: Session = Depends(get_db),
):
    """The full term report as JSON — powers the on-screen preview."""
    return _build(db, term_id, school_id)


@router.get("/terms/{term_id}/export.csv")
def export_term_report_csv(
    term_id: int,
    school_id: int = Query(_DEFAULT_SCHOOL_ID),
    db: Session = Depends(get_db),
):
    """Download the term report as a sectioned CSV (spreadsheet-friendly)."""
    report = _build(db, term_id, school_id)
    buf = io.StringIO()
    w = csv.writer(buf)

    w.writerow([report.school_name, "Term Report"])
    w.writerow(["Term", report.term_name])
    if report.term_start_date:
        w.writerow(["Start date", report.term_start_date.isoformat()])
    if report.term_end_date:
        w.writerow(["End date", report.term_end_date.isoformat()])
    w.writerow(["Generated", report.generated_at.isoformat()])
    w.writerow([])

    t = report.totals
    w.writerow(["SUMMARY"])
    w.writerow(["Metric", "Amount (NGN)", "Kobo"])
    w.writerow(["Total expected", t.total_expected_display, t.total_expected_kobo])
    w.writerow(["Total collected", t.total_collected_display, t.total_collected_kobo])
    w.writerow(["Outstanding", t.total_remaining_display, t.total_remaining_kobo])
    w.writerow(["Overpaid (credit)", t.total_overpaid_display, t.total_overpaid_kobo])
    w.writerow(["Collection rate (%)", t.collection_rate, ""])
    w.writerow([])

    w.writerow(["STUDENTS"])
    w.writerow(["Total", "Paid", "Partial", "Unpaid", "Overpaid"])
    w.writerow([
        t.students_total, t.students_paid, t.students_partial,
        t.students_unpaid, t.students_overpaid,
    ])
    w.writerow([])

    w.writerow(["BY FEE CATEGORY"])
    w.writerow(["Category", "Expected (NGN)", "Collected (NGN)", "Outstanding (NGN)"])
    for c in report.categories:
        w.writerow([c.category_name, c.expected_display, c.collected_display, c.remaining_display])
    w.writerow([])

    w.writerow(["BY SECTION"])
    w.writerow(["Section", "Students", "Expected (NGN)", "Collected (NGN)", "Outstanding (NGN)"])
    for s in report.sections:
        w.writerow([s.section, s.students, s.expected_display, s.collected_display, s.remaining_display])
    w.writerow([])

    w.writerow(["BY CLASS"])
    w.writerow(["Section", "Class", "Students", "Expected (NGN)", "Collected (NGN)", "Outstanding (NGN)"])
    for c in report.classes:
        w.writerow([c.section, c.class_name, c.students, c.expected_display, c.collected_display, c.remaining_display])
    w.writerow([])

    w.writerow(["BY PAYMENT METHOD"])
    w.writerow(["Method", "Payments", "Amount (NGN)"])
    for m in report.methods:
        w.writerow([m.label, m.count, m.amount_display])
    ch = report.channels
    w.writerow([])
    w.writerow(["Online (Paystack)", ch.online_count, ch.online_amount_display])
    w.writerow(["Manual (cash/POS/transfer/other)", ch.manual_count, ch.manual_amount_display])
    w.writerow([])

    w.writerow(["REMINDER ACTIVITY"])
    w.writerow(["Reminders sent", report.reminders.reminders_sent])
    w.writerow(["Note", report.reminders.note])

    buf.seek(0)
    filename = f"term-report-{_slug(report.term_name)}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/terms/{term_id}/export.pdf")
def export_term_report_pdf(
    term_id: int,
    school_id: int = Query(_DEFAULT_SCHOOL_ID),
    db: Session = Depends(get_db),
):
    """Download the term report as a printable PDF."""
    report = _build(db, term_id, school_id)
    try:
        pdf_bytes = render_term_report_pdf(report)
    except Exception as exc:
        logger.error(f"PDF render failed for term {term_id}: {exc}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Could not generate PDF. Please try again or use the CSV export.",
        )
    filename = f"term-report-{_slug(report.term_name)}.pdf"
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/compare", response_model=TermComparisonResponse)
def compare_terms_endpoint(
    term_id_1: int = Query(..., description="First term id"),
    term_id_2: int = Query(..., description="Second term id"),
    school_id: int = Query(_DEFAULT_SCHOOL_ID),
    db: Session = Depends(get_db),
):
    """Side-by-side comparison of two terms (Part E)."""
    try:
        return compare_terms(db, school_id=school_id, term_id_1=term_id_1, term_id_2=term_id_2)
    except ReportError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

