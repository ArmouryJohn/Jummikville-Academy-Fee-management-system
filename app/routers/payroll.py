"""
Staff Payroll Router — Director-only term salary setup, payouts, dashboard, comparisons, and PDF reports.

ENDPOINTS:
- GET  /api/v1/payroll/summary — Dashboard summary metrics & filterable payroll roster
- POST /api/v1/payroll/setup — Assign/update staff term salary schedule
- POST /api/v1/payroll/payments — Record payout transaction (installments or full)
- GET  /api/v1/payroll/compare — Compare payroll metrics across two terms
- GET  /api/v1/payroll/reports/terms/{term_id}/export.pdf — Download printable term PDF report
- GET  /api/v1/payroll/{payment_id}/payslip — Download individual payout payslip PDF
"""

import logging
import tempfile
from datetime import datetime, date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Staff, StaffPayrollRecord, StaffPayment, Term, School, User, ActivityLog, Payroll
from app.schemas.payroll import (
    StaffPayrollSetup,
    StaffPaymentCreate,
    StaffPaymentResponse,
    StaffPayrollRecordResponse,
    StaffPayrollSummary,
    TermPayrollSnapshot,
    TermPayrollComparison,
    PayrollCreate,
    PayrollResponse,
)
from app.services.auth_deps import require_director
from app.services.payroll_pdf import generate_payslip_pdf, generate_payslip
from app.services.payroll_report_pdf import render_term_payroll_pdf
from app.services.twilio_wa import send_payroll_notification
from app.utils.formatting import kobo_to_naira

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/payroll", tags=["payroll"])


@router.get("", response_model=List[PayrollResponse])
def list_payroll(
    school_id: int = Query(1, description="School ID"),
    term_id: Optional[int] = Query(None, description="Term ID filter"),
    db: Session = Depends(get_db),
    actor: User = Depends(require_director),
):
    """List legacy single-payment payroll records."""
    query = db.query(Payroll).filter(Payroll.school_id == school_id)
    if term_id:
        query = query.filter(Payroll.term_id == term_id)
    results = query.order_by(Payroll.payment_date.desc(), Payroll.id.desc()).all()

    return [
        PayrollResponse(
            id=p.id,
            school_id=p.school_id,
            term_id=p.term_id,
            term_name=p.term.name if p.term else None,
            staff_name=p.staff_name,
            phone_number=p.phone_number,
            amount_kobo=p.amount_kobo,
            amount_display=kobo_to_naira(p.amount_kobo),
            payment_date=p.payment_date,
            note=p.note,
            processed_by_email=p.processed_by_user.email if p.processed_by_user else "Director",
            payslip_url=f"/api/v1/payroll/{p.id}/payslip",
            created_at=p.created_at,
        )
        for p in results
    ]


@router.post("", response_model=PayrollResponse, status_code=status.HTTP_201_CREATED)
def create_payroll(
    data: PayrollCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_director),
):
    """Record a single salary payment."""
    term = None
    if data.term_id:
        term = db.query(Term).filter(Term.id == data.term_id).first()
        if not term:
            raise HTTPException(status_code=404, detail="Term not found")

    payroll = Payroll(
        school_id=data.school_id,
        term_id=data.term_id,
        staff_name=data.staff_name.strip(),
        phone_number=data.phone_number.strip(),
        amount_kobo=data.amount_kobo,
        payment_date=data.payment_date or datetime.now().date(),
        note=data.note.strip() if data.note else None,
        processed_by_user_id=actor.id,
    )
    db.add(payroll)
    db.commit()
    db.refresh(payroll)

    db.add(ActivityLog(
        school_id=payroll.school_id,
        action="payroll_recorded",
        description=f"Salary payment of {kobo_to_naira(payroll.amount_kobo)} recorded for {payroll.staff_name} by Director {actor.email}.",
    ))
    db.commit()

    return PayrollResponse(
        id=payroll.id,
        school_id=payroll.school_id,
        term_id=payroll.term_id,
        term_name=term.name if term else None,
        staff_name=payroll.staff_name,
        phone_number=payroll.phone_number,
        amount_kobo=payroll.amount_kobo,
        amount_display=kobo_to_naira(payroll.amount_kobo),
        payment_date=payroll.payment_date,
        note=payroll.note,
        processed_by_email=actor.email,
        payslip_url=f"/api/v1/payroll/{payroll.id}/payslip",
        created_at=payroll.created_at,
    )


def _format_record_response(r: StaffPayrollRecord) -> StaffPayrollRecordResponse:
    r.recalculate_status()
    s = r.staff
    payout_responses = [
        StaffPaymentResponse(
            id=p.id,
            payroll_record_id=p.payroll_record_id,
            amount_kobo=p.amount_kobo,
            amount_display=kobo_to_naira(p.amount_kobo),
            payment_date=p.payment_date,
            method=p.method,
            note=p.note,
            processed_by_email=p.processed_by_user.email if p.processed_by_user else "Director",
            created_at=p.created_at,
        )
        for p in sorted(r.payouts, key=lambda x: x.payment_date, reverse=True)
    ]

    return StaffPayrollRecordResponse(
        id=r.id,
        school_id=r.school_id,
        staff_id=r.staff_id,
        staff_name=s.full_name if s else "Staff Member",
        role_title=s.role_title if s else "Staff",
        phone_number=s.phone_number if s else "",
        bank_name=s.bank_name if s else None,
        account_number=s.account_number if s else None,
        account_name=s.account_name if s else None,
        classes_taught=(s.classes_taught or []) if s else [],
        term_id=r.term_id,
        term_name=r.term.name if r.term else f"Term #{r.term_id}",
        amount_scheduled_kobo=r.amount_scheduled_kobo,
        amount_paid_kobo=r.amount_paid_kobo,
        remaining_kobo=r.remaining_kobo,
        amount_scheduled_display=kobo_to_naira(r.amount_scheduled_kobo),
        amount_paid_display=kobo_to_naira(r.amount_paid_kobo),
        remaining_display=kobo_to_naira(r.remaining_kobo),
        status=r.status,
        note=r.note,
        payouts=payout_responses,
        created_at=r.created_at,
    )


@router.get("/summary", response_model=StaffPayrollSummary)
def get_payroll_summary(
    school_id: int = Query(1, description="School ID"),
    term_id: Optional[int] = Query(None, description="Term ID (defaults to current term)"),
    class_taught: Optional[str] = Query(None, description="Filter by class taught"),
    staff_role: Optional[str] = Query(None, description="Filter by staff role"),
    payment_status: Optional[str] = Query(None, description="Filter by status ('unpaid', 'partial', 'paid')"),
    db: Session = Depends(get_db),
    actor: User = Depends(require_director),
):
    """
    Get payroll summary cards and filterable roster for a given term.
    """
    if not isinstance(term_id, int):
        term_id = None

    if not term_id:
        current_term = db.query(Term).filter(Term.school_id == school_id, Term.is_current == True).first()
        term_id = current_term.id if current_term else None

    # Total staff count in system
    total_staff = db.query(Staff).filter(Staff.school_id == school_id, Staff.is_active == True).count()

    query = db.query(StaffPayrollRecord).filter(StaffPayrollRecord.school_id == school_id)
    if term_id:
        query = query.filter(StaffPayrollRecord.term_id == term_id)

    if staff_role and isinstance(staff_role, str):
        query = query.join(Staff).filter(Staff.role_title.ilike(f"%{staff_role}%"))

    records = query.all()

    # Recalculate status and filter python-side for class / status
    formatted: List[StaffPayrollRecordResponse] = []
    for r in records:
        r.recalculate_status()
        resp = _format_record_response(r)

        if class_taught and isinstance(class_taught, str) and class_taught not in resp.classes_taught:
            continue
        if payment_status and isinstance(payment_status, str) and resp.status != payment_status:
            continue
        formatted.append(resp)

    total_sched = sum(f.amount_scheduled_kobo for f in formatted)
    total_paid = sum(f.amount_paid_kobo for f in formatted)
    total_rem = sum(f.remaining_kobo for f in formatted)

    paid_cnt = sum(1 for f in formatted if f.status == "paid")
    part_cnt = sum(1 for f in formatted if f.status == "partial")
    unpaid_cnt = sum(1 for f in formatted if f.status == "unpaid")

    comp_rate = round((total_paid / total_sched * 100)) if total_sched > 0 else 0

    return StaffPayrollSummary(
        total_staff=total_staff,
        total_scheduled_kobo=total_sched,
        total_paid_kobo=total_paid,
        total_remaining_kobo=total_rem,
        total_scheduled_display=kobo_to_naira(total_sched),
        total_paid_display=kobo_to_naira(total_paid),
        total_remaining_display=kobo_to_naira(total_rem),
        staff_paid_count=paid_cnt,
        staff_partial_count=part_cnt,
        staff_unpaid_count=unpaid_cnt,
        completion_rate=comp_rate,
        records=formatted,
    )


@router.post("/setup", response_model=StaffPayrollRecordResponse, status_code=status.HTTP_201_CREATED)
def setup_staff_payroll(
    data: StaffPayrollSetup,
    db: Session = Depends(get_db),
    actor: User = Depends(require_director),
):
    """
    Assign or update a staff member's term salary schedule.
    """
    staff = db.query(Staff).filter(Staff.id == data.staff_id).first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found")

    term = db.query(Term).filter(Term.id == data.term_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")

    record = db.query(StaffPayrollRecord).filter(
        StaffPayrollRecord.staff_id == data.staff_id,
        StaffPayrollRecord.term_id == data.term_id,
    ).first()

    if not record:
        record = StaffPayrollRecord(
            school_id=data.school_id,
            staff_id=data.staff_id,
            term_id=data.term_id,
            amount_scheduled_kobo=data.amount_scheduled_kobo,
            note=data.note,
            created_by_user_id=actor.id,
        )
        db.add(record)
    else:
        record.amount_scheduled_kobo = data.amount_scheduled_kobo
        if data.note:
            record.note = data.note

    db.commit()
    db.refresh(record)

    return _format_record_response(record)


@router.post("/payments", response_model=StaffPaymentResponse, status_code=status.HTTP_201_CREATED)
def record_staff_payment(
    data: StaffPaymentCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_director),
):
    """
    Record a salary payout transaction for a staff member.
    Triggers automated WhatsApp notification and status update.
    """
    record = db.query(StaffPayrollRecord).filter(StaffPayrollRecord.id == data.payroll_record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Staff payroll record not found")

    payout = StaffPayment(
        payroll_record_id=record.id,
        amount_kobo=data.amount_kobo,
        payment_date=data.payment_date or datetime.now().date(),
        method=data.method,
        note=data.note,
        processed_by_user_id=actor.id,
    )
    db.add(payout)
    db.commit()

    record.recalculate_status()
    db.commit()
    db.refresh(payout)

    # WhatsApp Notification to Staff
    try:
        school = db.query(School).filter(School.id == record.school_id).first()
        send_payroll_notification(
            phone_number=record.staff.phone_number,
            staff_name=record.staff.full_name,
            amount_kobo=payout.amount_kobo,
            term_name=record.term.name if record.term else None,
            school_name=school.name if school else "Jummikville Academy",
        )
    except Exception:
        logger.warning("Failed to send staff WhatsApp notification", exc_info=True)

    # Activity Audit Log
    db.add(ActivityLog(
        school_id=record.school_id,
        action="payroll_recorded",
        description=f"Salary payout of {kobo_to_naira(payout.amount_kobo)} for {record.staff.full_name} recorded by Director {actor.email}.",
    ))
    db.commit()

    return StaffPaymentResponse(
        id=payout.id,
        payroll_record_id=payout.payroll_record_id,
        amount_kobo=payout.amount_kobo,
        amount_display=kobo_to_naira(payout.amount_kobo),
        payment_date=payout.payment_date,
        method=payout.method,
        note=payout.note,
        processed_by_email=actor.email,
        created_at=payout.created_at,
    )


@router.get("/compare", response_model=TermPayrollComparison)
def compare_term_payroll(
    term_id_1: int = Query(..., description="First term ID"),
    term_id_2: int = Query(..., description="Second term ID"),
    school_id: int = Query(1, description="School ID"),
    db: Session = Depends(get_db),
    actor: User = Depends(require_director),
):
    """
    Compare staff payroll performance across two terms side-by-side.
    """
    def _snapshot(tid: int) -> TermPayrollSnapshot:
        term = db.query(Term).filter(Term.id == tid).first()
        tname = term.name if term else f"Term #{tid}"
        records = db.query(StaffPayrollRecord).filter(
            StaffPayrollRecord.school_id == school_id,
            StaffPayrollRecord.term_id == tid,
        ).all()

        sched = sum(r.amount_scheduled_kobo for r in records)
        paid = sum(r.amount_paid_kobo for r in records)
        rem = sum(r.remaining_kobo for r in records)
        comp = round((paid / sched * 100)) if sched > 0 else 0

        return TermPayrollSnapshot(
            term_id=tid,
            term_name=tname,
            total_staff=len(records),
            total_scheduled_kobo=sched,
            total_paid_kobo=paid,
            total_remaining_kobo=rem,
            total_scheduled_display=kobo_to_naira(sched),
            total_paid_display=kobo_to_naira(paid),
            total_remaining_display=kobo_to_naira(rem),
            completion_rate=comp,
        )

    snap1 = _snapshot(term_id_1)
    snap2 = _snapshot(term_id_2)

    return TermPayrollComparison(
        term1=snap1,
        term2=snap2,
        scheduled_change_kobo=snap2.total_scheduled_kobo - snap1.total_scheduled_kobo,
        paid_change_kobo=snap2.total_paid_kobo - snap1.total_paid_kobo,
        completion_rate_change=snap2.completion_rate - snap1.completion_rate,
    )


@router.get("/reports/terms/{term_id}/export.pdf")
def export_term_payroll_pdf(
    term_id: int,
    school_id: int = Query(1, description="School ID"),
    db: Session = Depends(get_db),
    actor: User = Depends(require_director),
):
    """
    Export printable term payroll backup report in PDF format.
    """
    term = db.query(Term).filter(Term.id == term_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")

    summary = get_payroll_summary(school_id=school_id, term_id=term_id, db=db, actor=actor)
    pdf_bytes = render_term_payroll_pdf(
        summary=summary,
        term_name=term.name,
        director_email=actor.email,
    )

    filename = f"staff_payroll_report_term_{term_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{payment_id}/payslip")
def download_payslip(
    payment_id: Optional[int] = None,
    payroll_id: Optional[int] = None,
    db: Session = Depends(get_db),
    actor: User = Depends(require_director),
):
    """
    Download single payout payslip PDF (supports payment_id or legacy payroll_id).
    """
    target_id = payroll_id or payment_id
    if not target_id:
        raise HTTPException(status_code=400, detail="Missing payment_id or payroll_id")

    # Try legacy Payroll model first
    legacy_payroll = db.query(Payroll).filter(Payroll.id == target_id).first()
    if legacy_payroll:
        pdf_bytes = generate_payslip_pdf(
            payslip_id=legacy_payroll.id,
            staff_name=legacy_payroll.staff_name,
            amount_kobo=legacy_payroll.amount_kobo,
            payment_date=legacy_payroll.payment_date.strftime("%d %b %Y") if legacy_payroll.payment_date else "N/A",
            term_name=legacy_payroll.term.name if legacy_payroll.term else None,
            school_name=legacy_payroll.school.name if legacy_payroll.school else "Jummikville Academy",
        )
    else:
        payout = db.query(StaffPayment).filter(StaffPayment.id == target_id).first()
        if not payout:
            raise HTTPException(status_code=404, detail="Payment record not found")

        rec = payout.payroll_record
        school = db.query(School).filter(School.id == rec.school_id).first()
        pdf_bytes = generate_payslip_pdf(
            payslip_id=payout.id,
            staff_name=rec.staff.full_name,
            amount_kobo=payout.amount_kobo,
            payment_date=payout.payment_date.strftime("%d %b %Y"),
            term_name=rec.term.name if rec.term else None,
            school_name=school.name if school else "Jummikville Academy",
        )

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(pdf_bytes)
    tmp.close()

    return FileResponse(
        path=tmp.name,
        filename=f"payslip_{target_id}.pdf",
        media_type="application/pdf",
    )
