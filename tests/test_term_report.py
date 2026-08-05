"""
Part B — Term Report Export tests.

Exercises app/services/report_service.build_term_report (the single source of the
report's numbers) plus the CSV/PDF exports. In-memory SQLite, network stubbed by
conftest. Money is summed in Python from Payment rows (never SQL), so these tests
also guard that the derived totals stay correct after real payments are recorded.
"""

from datetime import datetime, date, timedelta, timezone

import pytest

from app.models import Student, FeeCategory, FeeType, FeeRecord, Term, ActivityLog
from app.services.payment_service import record_payment
from app.services.report_service import build_term_report, ReportError


# ---------------------------------------------------------------------------
# Helpers to build a second term / extra records inline.
# ---------------------------------------------------------------------------
def _make_term(db, school, name, current=False, start=None, end=None):
    t = Term(
        school_id=school.id, name=name, is_current=current,
        start_date=start, end_date=end,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _make_record(db, student, fee_type, total_kobo, status="unpaid"):
    r = FeeRecord(
        student_id=student.id, fee_type_id=fee_type.id,
        total_fees_kobo=total_kobo, status=status,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


# ---------------------------------------------------------------------------
# Totals + term scoping
# ---------------------------------------------------------------------------
def test_totals_sum_over_term_records(db, school, term, student, fee_record):
    """Expected = Σ total_fees; collected = Σ payments; rate reflects both."""
    record_payment(
        db=db, fee_record_id=fee_record.id, amount_kobo=3_000_000,
        method="cash", send_confirmation=False,
    )
    report = build_term_report(db, school_id=school.id, term_id=term.id)

    assert report.totals.total_expected_kobo == 7_500_000
    assert report.totals.total_collected_kobo == 3_000_000
    assert report.totals.total_remaining_kobo == 4_500_000
    assert report.totals.total_overpaid_kobo == 0
    assert report.totals.collection_rate == 40  # 3.0m / 7.5m
    assert report.totals.total_collected_display == "₦30,000.00"


def test_second_term_is_excluded(db, school, term, student, tuition_type, fee_record):
    """A record in another term must NOT leak into this term's totals."""
    other = _make_term(db, school, "Second Term 2025/2026")
    other_type = FeeType(
        school_id=school.id, category_id=tuition_type.category_id,
        section="Primary", term_id=other.id, amount_kobo=5_000_000,
    )
    db.add(other_type)
    db.commit()
    db.refresh(other_type)
    _make_record(db, student, other_type, 5_000_000)

    report = build_term_report(db, school_id=school.id, term_id=term.id)
    # Only the first term's ₦75,000 record counts.
    assert report.totals.total_expected_kobo == 7_500_000


def test_unknown_term_raises(db, school):
    with pytest.raises(ReportError):
        build_term_report(db, school_id=school.id, term_id=9999)


# ---------------------------------------------------------------------------
# Payment-method split (online vs manual)
# ---------------------------------------------------------------------------
def test_online_vs_manual_split(db, school, term, student, fee_record):
    record_payment(
        db=db, fee_record_id=fee_record.id, amount_kobo=2_000_000,
        method="cash", send_confirmation=False,
    )
    record_payment(
        db=db, fee_record_id=fee_record.id, amount_kobo=1_500_000,
        method="paystack", paystack_reference="JMK-1-1706547200",
        send_confirmation=False,
    )
    report = build_term_report(db, school_id=school.id, term_id=term.id)

    assert report.channels.online_count == 1
    assert report.channels.online_amount_kobo == 1_500_000
    assert report.channels.manual_count == 1
    assert report.channels.manual_amount_kobo == 2_000_000

    by_method = {m.method: m for m in report.methods}
    assert by_method["paystack"].count == 1
    assert by_method["paystack"].amount_kobo == 1_500_000
    assert by_method["cash"].amount_kobo == 2_000_000


# ---------------------------------------------------------------------------
# Student status counts
# ---------------------------------------------------------------------------
def test_student_status_counts(db, school, term, tuition_type):
    """One paid, one partial, one unpaid student → correct rolled-up counts."""
    students = []
    for i, name in enumerate(("Ada", "Bola", "Chidi")):
        st = Student(
            school_id=school.id, student_name=name, section="Primary",
            class_name="Primary 4", parent_name="P", parent_phone="+2348010000000",
        )
        db.add(st)
        db.commit()
        db.refresh(st)
        students.append(st)

    recs = [_make_record(db, st, tuition_type, 7_500_000) for st in students]
    # Ada pays in full, Bola pays half, Chidi pays nothing.
    record_payment(db=db, fee_record_id=recs[0].id, amount_kobo=7_500_000,
                   method="cash", send_confirmation=False)
    record_payment(db=db, fee_record_id=recs[1].id, amount_kobo=3_000_000,
                   method="cash", send_confirmation=False)

    report = build_term_report(db, school_id=school.id, term_id=term.id)
    assert report.totals.students_total == 3
    assert report.totals.students_paid == 1
    assert report.totals.students_partial == 1
    assert report.totals.students_unpaid == 1


# ---------------------------------------------------------------------------
# Category / class breakdowns
# ---------------------------------------------------------------------------
def test_category_and_class_breakdown(db, school, term, student, fee_record):
    record_payment(db=db, fee_record_id=fee_record.id, amount_kobo=2_500_000,
                   method="cash", send_confirmation=False)
    report = build_term_report(db, school_id=school.id, term_id=term.id)

    cats = {c.category_name: c for c in report.categories}
    assert "Tuition Fee" in cats
    assert cats["Tuition Fee"].expected_kobo == 7_500_000
    assert cats["Tuition Fee"].collected_kobo == 2_500_000

    classes = {(c.section, c.class_name): c for c in report.classes}
    assert ("Primary", "Primary 4") in classes
    assert classes[("Primary", "Primary 4")].students == 1


# ---------------------------------------------------------------------------
# Reminder summary
# ---------------------------------------------------------------------------
def test_reminder_summary_scoped_to_term_window(db, school, student):
    """Reminders within the term dates count; ones outside don't."""
    start = date(2025, 9, 1)
    end = date(2025, 12, 20)
    dated_term = _make_term(db, school, "Dated Term", start=start, end=end)

    inside = ActivityLog(
        school_id=school.id, student_id=student.id, action="reminder_sent",
        description="in window",
        created_at=datetime(2025, 10, 1, 12, 0, tzinfo=timezone.utc),
    )
    outside = ActivityLog(
        school_id=school.id, student_id=student.id, action="reminder_sent",
        description="out of window",
        created_at=datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc),
    )
    db.add_all([inside, outside])
    db.commit()

    report = build_term_report(db, school_id=school.id, term_id=dated_term.id)
    assert report.reminders.scoped_by_dates is True
    assert report.reminders.reminders_sent == 1


# ---------------------------------------------------------------------------
# Export smoke tests (CSV rows + real PDF bytes)
# ---------------------------------------------------------------------------
def test_csv_export_has_expected_sections(db, school, term, student, fee_record):
    import asyncio

    from app.routers.reports import export_term_report_csv

    resp = export_term_report_csv(term_id=term.id, school_id=school.id, db=db)

    # Starlette wraps our sync iterator as an async body_iterator; drain it.
    async def _drain():
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk if isinstance(chunk, str) else chunk.decode())
        return "".join(chunks)

    body = asyncio.run(_drain())
    assert "SUMMARY" in body
    assert "BY FEE CATEGORY" in body
    assert "BY PAYMENT METHOD" in body
    assert "REMINDER ACTIVITY" in body
    assert resp.media_type == "text/csv"


def test_pdf_renderer_returns_bytes(db, school, term, student, fee_record):
    # Call the real renderer directly (conftest stubs the receipt generator, not this).
    from app.services.report_pdf import render_term_report_pdf

    report = build_term_report(db, school_id=school.id, term_id=term.id)
    pdf = render_term_report_pdf(report)
    assert isinstance(pdf, (bytes, bytearray))
    assert len(pdf) > 500
    assert pdf[:4] == b"%PDF"
