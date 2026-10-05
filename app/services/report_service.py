"""
Report service for generating term financial reports, collection breakdowns, and term comparisons.
"""

import logging
from datetime import datetime, timezone, time

from sqlalchemy.orm import Session, joinedload

from app.constants import SECTION_CLASSES
from app.models import (
    School,
    Student,
    FeeRecord,
    FeeType,
    FeeCategory,
    Payment,
    ActivityLog,
    Term,
)
from app.schemas.report import (
    TermReportResponse,
    TermComparisonResponse,
    TermComparisonItem,
    ReportTotals,
    CategoryLine,
    SectionLine,
    ClassLine,
    MethodLine,
    ChannelSplit,
    ReminderSummary,
)
from app.utils.formatting import kobo_to_naira
from app.services.expense_service import total_expenses_kobo


logger = logging.getLogger(__name__)


class ReportError(Exception):
    """Raised when a term report can't be built (e.g. unknown term)."""


# Human labels for the payment-method codes stored on Payment.method.
_METHOD_LABELS = {
    "paystack": "Paystack (online)",
    "cash": "Cash",
    "pos": "POS",
    "bank_transfer": "Bank Transfer",
    "other": "Other",
}
# The order methods appear in the report (stable, not payment-count order).
_METHOD_ORDER = ["paystack", "cash", "pos", "bank_transfer", "other"]


def _status_for(total_kobo: int, paid_kobo: int) -> str:
    """
    Roll a student's combined totals into one status — mirrors
    dashboard._aggregate_status / FeeRecord._status_for so the report agrees
    with the rest of the app.
    """
    if total_kobo <= 0:
        return "no_fee"
    if paid_kobo <= 0:
        return "unpaid"
    if paid_kobo > total_kobo:
        return "overpaid"
    if paid_kobo == total_kobo:
        return "paid"
    return "partial"


def build_term_report(db: Session, school_id: int, term_id: int) -> TermReportResponse:
    """
    Build the full term report for one term. Pure (no HTTP), so it's directly
    unit-testable.

    Raises ReportError if the school or term doesn't exist, or the term belongs
    to another school.
    """
    school = db.query(School).filter(School.id == school_id).first()
    if not school:
        raise ReportError("School not found")

    term = db.query(Term).filter(Term.id == term_id).first()
    if not term or term.school_id != school_id:
        raise ReportError("Term not found")

    # ---- The term's fee records for ACTIVE students, records + payments loaded ----
    # Join FeeType to scope by term_id; eager-load fee_type→category and payments so
    # the computed-property sums don't trigger N+1 lazy loads.
    records = (
        db.query(FeeRecord)
        .join(FeeRecord.fee_type)
        .join(FeeRecord.student)
        .options(
            joinedload(FeeRecord.fee_type).joinedload(FeeType.category),
            joinedload(FeeRecord.payments),
            joinedload(FeeRecord.student),
        )
        .filter(
            FeeType.term_id == term_id,
            Student.school_id == school_id,
            Student.is_active == True,  # noqa: E712
        )
        .all()
    )

    # Group records by student so we can roll up a per-student status.
    records_by_student: dict[int, list[FeeRecord]] = {}
    for r in records:
        records_by_student.setdefault(r.student_id, []).append(r)

    # ---- Headline totals ----
    total_expected = sum(r.total_fees_kobo for r in records)
    total_collected = sum(r.amount_paid_kobo for r in records)
    total_remaining = sum(r.remaining_kobo for r in records)
    total_overpaid = sum(r.overpaid_kobo for r in records)
    collection_rate = (
        round(total_collected / total_expected * 100) if total_expected > 0 else 0
    )

    paid = partial = unpaid = overpaid = 0
    for _sid, recs in records_by_student.items():
        s_total = sum(r.total_fees_kobo for r in recs)
        s_paid = sum(r.amount_paid_kobo for r in recs)
        status = _status_for(s_total, s_paid)
        if status == "paid":
            paid += 1
        elif status == "partial":
            partial += 1
        elif status == "overpaid":
            overpaid += 1
        else:
            unpaid += 1
    # A student counts once for this term if they have any fee record in it.
    students_total = len(records_by_student)

    totals = ReportTotals(
        total_expected_kobo=total_expected,
        total_collected_kobo=total_collected,
        total_remaining_kobo=total_remaining,
        total_overpaid_kobo=total_overpaid,
        total_expected_display=kobo_to_naira(total_expected),
        total_collected_display=kobo_to_naira(total_collected),
        total_remaining_display=kobo_to_naira(total_remaining),
        total_overpaid_display=kobo_to_naira(total_overpaid),
        collection_rate=collection_rate,
        students_total=students_total,
        students_paid=paid,
        students_partial=partial,
        students_unpaid=unpaid,
        students_overpaid=overpaid,
        students_no_fee=0,  # a record in this term means fees ARE set for the term
    )

    # ---- By fee category ----
    cat_acc: dict[str, dict[str, int]] = {}
    for r in records:
        cat_name = r.fee_type.category.name if r.fee_type.category else "Uncategorised"
        acc = cat_acc.setdefault(cat_name, {"exp": 0, "coll": 0, "rem": 0})
        acc["exp"] += r.total_fees_kobo
        acc["coll"] += r.amount_paid_kobo
        acc["rem"] += r.remaining_kobo
    categories = [
        CategoryLine(
            category_name=name,
            expected_kobo=a["exp"],
            collected_kobo=a["coll"],
            remaining_kobo=a["rem"],
            expected_display=kobo_to_naira(a["exp"]),
            collected_display=kobo_to_naira(a["coll"]),
            remaining_display=kobo_to_naira(a["rem"]),
        )
        for name, a in sorted(cat_acc.items())
    ]

    # ---- By section and by class ----
    # Accumulate per (section) and per (section, class); count distinct students.
    sec_acc: dict[str, dict[str, int]] = {}
    sec_students: dict[str, set[int]] = {}
    cls_acc: dict[tuple[str, str], dict[str, int]] = {}
    cls_students: dict[tuple[str, str], set[int]] = {}

    for r in records:
        student = r.student
        sec = student.section or "Unspecified"
        cls = student.class_name or "Unspecified"

        sa = sec_acc.setdefault(sec, {"exp": 0, "coll": 0, "rem": 0})
        sa["exp"] += r.total_fees_kobo
        sa["coll"] += r.amount_paid_kobo
        sa["rem"] += r.remaining_kobo
        sec_students.setdefault(sec, set()).add(student.id)

        key = (sec, cls)
        ca = cls_acc.setdefault(key, {"exp": 0, "coll": 0, "rem": 0})
        ca["exp"] += r.total_fees_kobo
        ca["coll"] += r.amount_paid_kobo
        ca["rem"] += r.remaining_kobo
        cls_students.setdefault(key, set()).add(student.id)

    # Order sections by the canonical SECTION_CLASSES order, then any extras.
    ordered_sections = [s for s in SECTION_CLASSES if s in sec_acc] + [
        s for s in sec_acc if s not in SECTION_CLASSES
    ]
    sections = [
        SectionLine(
            section=sec,
            students=len(sec_students.get(sec, set())),
            expected_kobo=sec_acc[sec]["exp"],
            collected_kobo=sec_acc[sec]["coll"],
            remaining_kobo=sec_acc[sec]["rem"],
            expected_display=kobo_to_naira(sec_acc[sec]["exp"]),
            collected_display=kobo_to_naira(sec_acc[sec]["coll"]),
            remaining_display=kobo_to_naira(sec_acc[sec]["rem"]),
        )
        for sec in ordered_sections
    ]

    # Classes ordered by section order, then the class order within SECTION_CLASSES.
    def _class_sort_key(item: tuple[tuple[str, str], dict]) -> tuple[int, int]:
        (sec, cls), _ = item
        sec_i = list(SECTION_CLASSES).index(sec) if sec in SECTION_CLASSES else 99
        classes = SECTION_CLASSES.get(sec, [])
        cls_i = classes.index(cls) if cls in classes else 99
        return (sec_i, cls_i)

    classes = [
        ClassLine(
            section=sec,
            class_name=cls,
            students=len(cls_students.get((sec, cls), set())),
            expected_kobo=a["exp"],
            collected_kobo=a["coll"],
            remaining_kobo=a["rem"],
            expected_display=kobo_to_naira(a["exp"]),
            collected_display=kobo_to_naira(a["coll"]),
            remaining_display=kobo_to_naira(a["rem"]),
        )
        for (sec, cls), a in sorted(cls_acc.items(), key=_class_sort_key)
    ]

    # ---- By payment method (term-scoped) ----
    # Every payment against one of this term's fee records. Scope by joining
    # Payment → FeeRecord → FeeType.term_id.
    payments = (
        db.query(Payment)
        .join(Payment.fee_record)
        .join(FeeRecord.fee_type)
        .join(FeeRecord.student)
        .filter(
            FeeType.term_id == term_id,
            Student.school_id == school_id,
            Student.is_active == True,  # noqa: E712
        )
        .all()
    )

    method_acc: dict[str, dict[str, int]] = {}
    for p in payments:
        m = p.method or "other"
        acc = method_acc.setdefault(m, {"count": 0, "amount": 0})
        acc["count"] += 1
        acc["amount"] += p.amount_kobo

    methods = [
        MethodLine(
            method=m,
            label=_METHOD_LABELS.get(m, m.replace("_", " ").title()),
            count=method_acc[m]["count"],
            amount_kobo=method_acc[m]["amount"],
            amount_display=kobo_to_naira(method_acc[m]["amount"]),
        )
        # Show known methods in canonical order, then any unexpected ones.
        for m in (_METHOD_ORDER + [k for k in method_acc if k not in _METHOD_ORDER])
        if m in method_acc
    ]

    online_count = method_acc.get("paystack", {}).get("count", 0)
    online_amount = method_acc.get("paystack", {}).get("amount", 0)
    manual_count = sum(
        a["count"] for m, a in method_acc.items() if m != "paystack"
    )
    manual_amount = sum(
        a["amount"] for m, a in method_acc.items() if m != "paystack"
    )
    channels = ChannelSplit(
        online_count=online_count,
        online_amount_kobo=online_amount,
        online_amount_display=kobo_to_naira(online_amount),
        manual_count=manual_count,
        manual_amount_kobo=manual_amount,
        manual_amount_display=kobo_to_naira(manual_amount),
    )

    # ---- Reminder activity summary ----
    reminders = _reminder_summary(db, school_id, term)

    return TermReportResponse(
        school_id=school.id,
        school_name=school.name,
        term_id=term.id,
        term_name=term.name,
        term_start_date=term.start_date,
        term_end_date=term.end_date,
        is_current=term.is_current,
        generated_at=datetime.now(timezone.utc),
        totals=totals,
        categories=categories,
        sections=sections,
        classes=classes,
        methods=methods,
        channels=channels,
        reminders=reminders,
    )


def _reminder_summary(db: Session, school_id: int, term: Term) -> ReminderSummary:
    """
    Count 'reminder_sent' activity for the term. Reminders carry no term_id, so we
    scope by created_at against the term's start/end dates. If the term has no
    dates, we fall back to a school-wide all-time count and say so.
    """
    q = db.query(ActivityLog).filter(
        ActivityLog.school_id == school_id,
        ActivityLog.action == "reminder_sent",
    )

    scoped = bool(term.start_date or term.end_date)
    if term.start_date:
        start_dt = datetime.combine(term.start_date, time.min, tzinfo=timezone.utc)
        q = q.filter(ActivityLog.created_at >= start_dt)
    if term.end_date:
        # Inclusive of the whole end day.
        end_dt = datetime.combine(term.end_date, time.max, tzinfo=timezone.utc)
        q = q.filter(ActivityLog.created_at <= end_dt)

    count = q.count()
    if scoped:
        note = "Reminders sent within this term's start/end dates."
    else:
        note = (
            "This term has no start/end dates set, so this is the school's "
            "all-time reminder count. Set term dates to scope it."
        )
    return ReminderSummary(reminders_sent=count, scoped_by_dates=scoped, note=note)


def _build_comparison_item(db: Session, school_id: int, term_id: int) -> TermComparisonItem:
    """Build a TermComparisonItem for one term by combining its report & expense totals."""
    report = build_term_report(db, school_id, term_id)
    exp_kobo = total_expenses_kobo(db, school_id, term_id=term_id)
    net_kobo = report.totals.total_collected_kobo - exp_kobo

    return TermComparisonItem(
        term_id=report.term_id,
        term_name=report.term_name,
        term_start_date=report.term_start_date,
        term_end_date=report.term_end_date,
        is_current=report.is_current,
        total_expected_kobo=report.totals.total_expected_kobo,
        total_collected_kobo=report.totals.total_collected_kobo,
        total_remaining_kobo=report.totals.total_remaining_kobo,
        total_overpaid_kobo=report.totals.total_overpaid_kobo,
        total_expenses_kobo=exp_kobo,
        net_available_kobo=net_kobo,
        collection_rate=report.totals.collection_rate,
        total_expected_display=report.totals.total_expected_display,
        total_collected_display=report.totals.total_collected_display,
        total_remaining_display=report.totals.total_remaining_display,
        total_overpaid_display=report.totals.total_overpaid_display,
        total_expenses_display=kobo_to_naira(exp_kobo),
        net_available_display=kobo_to_naira(net_kobo),
        students_total=report.totals.students_total,
        students_paid=report.totals.students_paid,
        students_partial=report.totals.students_partial,
        students_unpaid=report.totals.students_unpaid,
        students_overpaid=report.totals.students_overpaid,
        methods=report.methods,
        channels=report.channels,
    )


def compare_terms(
    db: Session, school_id: int, term_id_1: int, term_id_2: int
) -> TermComparisonResponse:
    """
    Build a side-by-side comparison of two terms.
    Raises ReportError if either term is invalid or belongs to another school.
    """
    school = db.query(School).filter(School.id == school_id).first()
    if not school:
        raise ReportError("School not found")

    term1_item = _build_comparison_item(db, school_id, term_id_1)
    term2_item = _build_comparison_item(db, school_id, term_id_2)

    return TermComparisonResponse(
        school_id=school.id,
        school_name=school.name,
        term1=term1_item,
        term2=term2_item,
    )

