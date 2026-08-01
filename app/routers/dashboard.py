"""
Dashboard endpoints — aggregated, read-only views built for the frontend.

WHY A SEPARATE ROUTER:
The Students and Fees routers already expose the raw data. But the frontend's
Dashboard and Parents screens need that data pre-combined and pre-summed. Doing
those joins/sums here (once, in Python) keeps the frontend simple and — crucially —
means the balance/status logic still lives in ONE place (the FeeRecord model).
We never recompute a balance here; we only add up the balances the model gives us.

ENDPOINTS:
- GET /api/v1/dashboard/summary          → the four summary cards + chart data
- GET /api/v1/dashboard/students         → the Parents/Students list rows
- GET /api/v1/dashboard/students/{id}    → one student's full record + history
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import School, Student, FeeRecord, FeeType, FeeCategory, Payment, ActivityLog
from app.schemas.dashboard import (
    DashboardSummary,
    SectionSummary,
    CategoryBreakdown,
    StudentOverview,
    StudentDetail,
    FeeRecordDetail,
    PaymentHistoryItem,
    MessageHistoryItem,
)
from app.utils.formatting import kobo_to_naira

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])


def _aggregate_status(total_kobo: int, paid_kobo: int) -> str:
    """
    Roll a student's many fee records up into ONE status for the list view.

    Mirrors the same rule the FeeRecord model uses, just applied to the
    student's combined totals:
        no fees assigned yet   → 'no_fee'   (distinct from 'paid'!)
        nothing paid           → 'unpaid'
        overpaid               → 'overpaid'
        paid covers everything → 'paid'
        somewhere in between   → 'partial'

    WHY 'no_fee' IS ITS OWN STATUS:
    A student with no fees assigned owes ₦0 and has paid ₦0. Mathematically
    that looks "fully paid", but it really means "we haven't set this student's
    fees yet". Collapsing it into 'paid' hides students who still need fees
    assigned. Keeping it separate makes that gap visible.
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


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(
    school_id: int = Query(..., description="Which school to summarise"),
    section: str | None = Query(None, description="Filter by section: Nursery, Primary, Secondary, or null for All"),
    db: Session = Depends(get_db),
):
    """
    The home-screen numbers: total students, the four headline totals
    (expected/collected/remaining/overpaid), how many students are fully paid /
    partial / unpaid / overpaid (for the chart), per-section breakdown, and
    per-category collection breakdown.

    When `section` is null, returns whole-school figures. When set, filters to
    that section. The `sections` list always includes 'All' plus each section
    that has data, so the frontend can switch views without another round-trip.
    """
    school = db.query(School).filter(School.id == school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="School not found")

    # Pull every active student with their fee records in one go, optionally
    # filtered by section.
    query = (
        db.query(Student)
        .options(
            joinedload(Student.fee_records).joinedload(FeeRecord.fee_type)
        )
        .filter(Student.school_id == school_id, Student.is_active == True)  # noqa: E712
    )
    if section:
        query = query.filter(Student.section == section)
    students = query.all()

    total_expected = 0
    total_collected = 0
    total_remaining = 0  # what's still owed (never negative)
    total_overpaid = 0  # credit owed back (never negative)
    paid = partial = unpaid = overpaid = no_fee = 0

    for student in students:
        s_total = sum(r.total_fees_kobo for r in student.fee_records)
        s_paid = sum(r.amount_paid_kobo for r in student.fee_records)
        total_expected += s_total
        total_collected += s_paid
        # Use the split so overpayments don't mask shortfalls
        total_remaining += sum(r.remaining_kobo for r in student.fee_records)
        total_overpaid += sum(r.overpaid_kobo for r in student.fee_records)

        status = _aggregate_status(s_total, s_paid)
        if status == "paid":
            paid += 1
        elif status == "partial":
            partial += 1
        elif status == "overpaid":
            overpaid += 1
        elif status == "no_fee":
            no_fee += 1
        else:
            unpaid += 1

    collection_rate = (
        round(total_collected / total_expected * 100) if total_expected > 0 else 0
    )

    # ---- Per-section breakdown (always returned, even when filtering) ----
    sections_list: list[SectionSummary] = []

    # Whole-school 'All' entry (unfiltered)
    all_students = (
        db.query(Student)
        .options(joinedload(Student.fee_records))
        .filter(Student.school_id == school_id, Student.is_active == True)  # noqa: E712
        .all()
    )
    all_exp = sum(
        r.total_fees_kobo for s in all_students for r in s.fee_records
    )
    all_coll = sum(
        r.amount_paid_kobo for s in all_students for r in s.fee_records
    )
    all_rem = sum(
        r.remaining_kobo for s in all_students for r in s.fee_records
    )
    all_over = sum(
        r.overpaid_kobo for s in all_students for r in s.fee_records
    )
    sections_list.append(
        SectionSummary(
            section="All",
            total_students=len(all_students),
            total_expected_kobo=all_exp,
            total_collected_kobo=all_coll,
            total_remaining_kobo=all_rem,
            total_overpaid_kobo=all_over,
            total_expected_display=kobo_to_naira(all_exp),
            total_collected_display=kobo_to_naira(all_coll),
            total_remaining_display=kobo_to_naira(all_rem),
            total_overpaid_display=kobo_to_naira(all_over),
        )
    )

    # Each actual section that has students
    for sec in ["Nursery", "Primary", "Secondary"]:
        sec_students = [s for s in all_students if s.section == sec]
        if not sec_students:
            continue
        sec_exp = sum(
            r.total_fees_kobo for s in sec_students for r in s.fee_records
        )
        sec_coll = sum(
            r.amount_paid_kobo for s in sec_students for r in s.fee_records
        )
        sec_rem = sum(
            r.remaining_kobo for s in sec_students for r in s.fee_records
        )
        sec_over = sum(
            r.overpaid_kobo for s in sec_students for r in s.fee_records
        )
        sections_list.append(
            SectionSummary(
                section=sec,
                total_students=len(sec_students),
                total_expected_kobo=sec_exp,
                total_collected_kobo=sec_coll,
                total_remaining_kobo=sec_rem,
                total_overpaid_kobo=sec_over,
                total_expected_display=kobo_to_naira(sec_exp),
                total_collected_display=kobo_to_naira(sec_coll),
                total_remaining_display=kobo_to_naira(sec_rem),
                total_overpaid_display=kobo_to_naira(sec_over),
            )
        )

    # ---- Per-category breakdown (whole school) ----
    categories_list: list[CategoryBreakdown] = []
    categories = (
        db.query(FeeCategory)
        .filter(FeeCategory.school_id == school_id)
        .order_by(FeeCategory.name)
        .all()
    )
    for cat in categories:
        # All fee types in this category
        fee_type_ids = [
            ft.id
            for ft in db.query(FeeType)
            .filter(FeeType.category_id == cat.id)
            .all()
        ]
        if not fee_type_ids:
            # No fee types yet for this category — skip or show zeros?
            # Let's skip so the dashboard doesn't show unused categories.
            continue

        # All fee records linked to those fee types
        records = (
            db.query(FeeRecord)
            .filter(FeeRecord.fee_type_id.in_(fee_type_ids))
            .all()
        )
        cat_exp = sum(r.total_fees_kobo for r in records)
        cat_coll = sum(r.amount_paid_kobo for r in records)
        cat_rem = sum(r.remaining_kobo for r in records)
        cat_over = sum(r.overpaid_kobo for r in records)

        categories_list.append(
            CategoryBreakdown(
                category_id=cat.id,
                category_name=cat.name,
                total_expected_kobo=cat_exp,
                total_collected_kobo=cat_coll,
                total_remaining_kobo=cat_rem,
                total_overpaid_kobo=cat_over,
                total_expected_display=kobo_to_naira(cat_exp),
                total_collected_display=kobo_to_naira(cat_coll),
                total_remaining_display=kobo_to_naira(cat_rem),
                total_overpaid_display=kobo_to_naira(cat_over),
            )
        )

    return DashboardSummary(
        school_id=school.id,
        school_name=school.name,
        total_students=len(students),
        total_expected_kobo=total_expected,
        total_collected_kobo=total_collected,
        total_remaining_kobo=total_remaining,
        total_overpaid_kobo=total_overpaid,
        total_expected_display=kobo_to_naira(total_expected),
        total_collected_display=kobo_to_naira(total_collected),
        total_remaining_display=kobo_to_naira(total_remaining),
        total_overpaid_display=kobo_to_naira(total_overpaid),
        collection_rate=collection_rate,
        students_paid=paid,
        students_partial=partial,
        students_unpaid=unpaid,
        students_overpaid=overpaid,
        students_no_fee=no_fee,
        sections=sections_list,
        categories=categories_list,
    )


@router.get("/students", response_model=list[StudentOverview])
def students_overview(
    school_id: int = Query(..., description="Which school's students to list"),
    section: str | None = Query(None, description="Filter by section"),
    db: Session = Depends(get_db),
):
    """
    One row per active student with combined fees, paid, balance, remaining,
    overpaid, and status. This is exactly what the Parents/Students table renders.
    Searching and status-filtering are done on the frontend so the table feels instant.
    """
    school = db.query(School).filter(School.id == school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="School not found")

    query = (
        db.query(Student)
        .options(joinedload(Student.fee_records))
        .filter(Student.school_id == school_id, Student.is_active == True)  # noqa: E712
    )
    if section:
        query = query.filter(Student.section == section)

    students = query.order_by(Student.student_name).all()

    rows: list[StudentOverview] = []
    for student in students:
        total = sum(r.total_fees_kobo for r in student.fee_records)
        paid = sum(r.amount_paid_kobo for r in student.fee_records)
        balance = total - paid
        remaining = sum(r.remaining_kobo for r in student.fee_records)
        over = sum(r.overpaid_kobo for r in student.fee_records)

        rows.append(
            StudentOverview(
                student_id=student.id,
                student_name=student.student_name,
                section=student.section,
                class_name=student.class_name,
                parent_name=student.parent_name,
                parent_phone=student.parent_phone,
                parent_email=student.parent_email,
                total_fees_kobo=total,
                amount_paid_kobo=paid,
                balance_kobo=balance,
                remaining_kobo=remaining,
                overpaid_kobo=over,
                total_fees_display=kobo_to_naira(total),
                amount_paid_display=kobo_to_naira(paid),
                balance_display=kobo_to_naira(balance),
                remaining_display=kobo_to_naira(remaining),
                overpaid_display=kobo_to_naira(over),
                status=_aggregate_status(total, paid),
            )
        )

    return rows


@router.get("/students/{student_id}", response_model=StudentDetail)
def student_detail(student_id: int, db: Session = Depends(get_db)):
    """
    Full record for the detail drawer: the student's fee lines, every payment,
    and the message history (reminders + confirmations) for THIS student.
    """
    student = (
        db.query(Student)
        .options(
            joinedload(Student.fee_records).joinedload(FeeRecord.fee_type).joinedload(FeeType.category),
            joinedload(Student.fee_records).joinedload(FeeRecord.payments),
        )
        .filter(Student.id == student_id)
        .first()
    )
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    total = sum(r.total_fees_kobo for r in student.fee_records)
    paid = sum(r.amount_paid_kobo for r in student.fee_records)
    balance = total - paid
    remaining = sum(r.remaining_kobo for r in student.fee_records)
    over = sum(r.overpaid_kobo for r in student.fee_records)

    # Fee lines
    fee_records = [
        FeeRecordDetail(
            fee_record_id=r.id,
            fee_name=r.fee_type.name,
            fee_term=r.fee_type.term,
            total_fees_kobo=r.total_fees_kobo,
            amount_paid_kobo=r.amount_paid_kobo,
            balance_kobo=r.balance_kobo,
            remaining_kobo=r.remaining_kobo,
            overpaid_kobo=r.overpaid_kobo,
            total_fees_display=kobo_to_naira(r.total_fees_kobo),
            amount_paid_display=kobo_to_naira(r.amount_paid_kobo),
            balance_display=kobo_to_naira(r.balance_kobo),
            remaining_display=kobo_to_naira(r.remaining_kobo),
            overpaid_display=kobo_to_naira(r.overpaid_kobo),
            status=r.status,
        )
        for r in student.fee_records
    ]

    # Payment history — flatten payments across all fee records, newest first
    payments: list[PaymentHistoryItem] = []
    for r in student.fee_records:
        for p in r.payments:
            payments.append(
                PaymentHistoryItem(
                    amount_kobo=p.amount_kobo,
                    amount_display=kobo_to_naira(p.amount_kobo),
                    method=p.method,
                    recorded_by=p.recorded_by,
                    note=p.note,
                    paid_at=p.paid_at,
                )
            )
    payments.sort(key=lambda p: p.paid_at, reverse=True)

    # Message history — reminders/confirmations logged for this student
    activity = (
        db.query(ActivityLog)
        .filter(ActivityLog.student_id == student_id)
        .order_by(ActivityLog.created_at.desc())
        .all()
    )
    messages = [
        MessageHistoryItem(
            action=a.action,
            description=a.description,
            created_at=a.created_at,
        )
        for a in activity
    ]

    return StudentDetail(
        student_id=student.id,
        student_name=student.student_name,
        section=student.section,
        class_name=student.class_name,
        parent_name=student.parent_name,
        parent_phone=student.parent_phone,
        parent_email=student.parent_email,
        total_fees_kobo=total,
        amount_paid_kobo=paid,
        balance_kobo=balance,
        remaining_kobo=remaining,
        overpaid_kobo=over,
        total_fees_display=kobo_to_naira(total),
        amount_paid_display=kobo_to_naira(paid),
        balance_display=kobo_to_naira(balance),
        remaining_display=kobo_to_naira(remaining),
        overpaid_display=kobo_to_naira(over),
        status=_aggregate_status(total, paid),
        fee_records=fee_records,
        payments=payments,
        messages=messages,
    )
