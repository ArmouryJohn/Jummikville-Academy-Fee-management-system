"""Tests for staff payroll management, payouts, and reports."""

import pytest
from fastapi import HTTPException
from app.models import User, Staff, StaffPayrollRecord, StaffPayment, Term
from app.schemas.staff import StaffCreate
from app.schemas.payroll import StaffPayrollSetup, StaffPaymentCreate
from app.routers.staff import create_staff, delete_staff, list_staff
from app.routers.payroll import (
    setup_staff_payroll,
    record_staff_payment,
    get_payroll_summary,
    compare_term_payroll,
    export_term_payroll_pdf,
)
from app.services.auth_deps import require_director


@pytest.fixture()
def director_user(db, school):
    u = User(
        school_id=school.id,
        email="director@jummikville.sch",
        hashed_password="hash",
        role="director",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_create_staff_with_bank_and_classes(db, school, director_user):
    """Director can add a staff member with bank details and assigned classes."""
    data = StaffCreate(
        school_id=school.id,
        full_name="Mr. Clement Udoh",
        role_title="Senior Science Teacher",
        phone_number="08031234567",
        email="clement@jummikville.sch",
        bank_name="Access Bank",
        account_number="0123456789",
        account_name="Clement Udoh",
        classes_taught=["Primary 4", "Primary 5"],
    )

    created = create_staff(data=data, db=db, actor=require_director(director_user))

    assert created.full_name == "Mr. Clement Udoh"
    assert created.bank_name == "Access Bank"
    assert created.account_number == "0123456789"
    assert created.classes_taught == ["Primary 4", "Primary 5"]
    assert created.is_active is True


def test_assign_term_salary_and_record_payout(db, school, term, director_user):
    """Director schedules term salary and records payout installments."""
    staff = create_staff(
        data=StaffCreate(
            school_id=school.id,
            full_name="Mrs. Aniefiok Bassey",
            role_title="Primary 1 Teacher",
            phone_number="08098765432",
            bank_name="GTBank",
            account_number="0987654321",
            account_name="Aniefiok Bassey",
            classes_taught=["Primary 1"],
        ),
        db=db,
        actor=require_director(director_user),
    )

    # 1. Assign ₦150,000 term salary
    sched = setup_staff_payroll(
        data=StaffPayrollSetup(
            school_id=school.id,
            staff_id=staff.id,
            term_id=term.id,
            amount_scheduled_kobo=150_000_00,
        ),
        db=db,
        actor=require_director(director_user),
    )

    assert sched.amount_scheduled_kobo == 150_000_00
    assert sched.status == "unpaid"

    # 2. Record ₦50,000 partial payout
    payout1 = record_staff_payment(
        data=StaffPaymentCreate(
            payroll_record_id=sched.id,
            amount_kobo=50_000_00,
            method="bank_transfer",
        ),
        db=db,
        actor=require_director(director_user),
    )
    assert payout1.amount_kobo == 50_000_00

    # Verify summary after partial payout
    summary = get_payroll_summary(school_id=school.id, term_id=term.id, db=db, actor=require_director(director_user))
    rec = summary.records[0]
    assert rec.status == "partial"
    assert rec.remaining_kobo == 100_000_00

    # 3. Record remaining ₦100,000 payout
    record_staff_payment(
        data=StaffPaymentCreate(
            payroll_record_id=sched.id,
            amount_kobo=100_000_00,
            method="bank_transfer",
        ),
        db=db,
        actor=require_director(director_user),
    )

    summary_final = get_payroll_summary(school_id=school.id, term_id=term.id, db=db, actor=require_director(director_user))
    assert summary_final.records[0].status == "paid"
    assert summary_final.records[0].remaining_kobo == 0


def test_term_comparison_calculations(db, school, term, director_user):
    """Director can compare staff payroll metrics across 2 terms."""
    term2 = Term(school_id=school.id, name="Second Term 2025/2026", is_current=False)
    db.add(term2)
    db.commit()
    db.refresh(term2)

    staff = create_staff(
        data=StaffCreate(
            school_id=school.id,
            full_name="Mr. John Okon",
            role_title="Bus Driver",
            phone_number="08022223333",
        ),
        db=db,
        actor=require_director(director_user),
    )

    # Term 1: ₦100,000 scheduled, ₦100,000 paid (100%)
    r1 = setup_staff_payroll(
        data=StaffPayrollSetup(school_id=school.id, staff_id=staff.id, term_id=term.id, amount_scheduled_kobo=100_000_00),
        db=db, actor=require_director(director_user)
    )
    record_staff_payment(data=StaffPaymentCreate(payroll_record_id=r1.id, amount_kobo=100_000_00), db=db, actor=require_director(director_user))

    # Term 2: ₦120,000 scheduled, ₦60,000 paid (50%)
    r2 = setup_staff_payroll(
        data=StaffPayrollSetup(school_id=school.id, staff_id=staff.id, term_id=term2.id, amount_scheduled_kobo=120_000_00),
        db=db, actor=require_director(director_user)
    )
    record_staff_payment(data=StaffPaymentCreate(payroll_record_id=r2.id, amount_kobo=60_000_00), db=db, actor=require_director(director_user))

    comp = compare_term_payroll(term_id_1=term.id, term_id_2=term2.id, school_id=school.id, db=db, actor=require_director(director_user))

    assert comp.term1.total_scheduled_kobo == 100_000_00
    assert comp.term2.total_scheduled_kobo == 120_000_00
    assert comp.scheduled_change_kobo == 20_000_00
    assert comp.completion_rate_change == -50


def test_soft_delete_preserves_payroll_history(db, school, term, director_user):
    """Deactivating a staff member sets is_active=False without destroying payroll history."""
    staff = create_staff(
        data=StaffCreate(
            school_id=school.id, full_name="Retired Staff", role_title="Ex-Teacher", phone_number="08000000000"
        ),
        db=db, actor=require_director(director_user)
    )

    rec = setup_staff_payroll(
        data=StaffPayrollSetup(school_id=school.id, staff_id=staff.id, term_id=term.id, amount_scheduled_kobo=80_000_00),
        db=db, actor=require_director(director_user)
    )

    # Soft delete staff
    res = delete_staff(staff_id=staff.id, db=db, actor=require_director(director_user))
    assert res["status"] == "ok"

    # Verify staff is soft-deleted
    db.refresh(staff)
    assert staff.is_active is False

    # Verify payroll record still exists in DB
    p_rec = db.query(StaffPayrollRecord).filter(StaffPayrollRecord.id == rec.id).first()
    assert p_rec is not None
    assert p_rec.amount_scheduled_kobo == 80_000_00


def test_export_term_payroll_pdf_report(db, school, term, director_user):
    """Director can export full term payroll backup PDF report."""
    staff = create_staff(
        data=StaffCreate(school_id=school.id, full_name="Mrs. Faith Effiong", role_title="Teacher", phone_number="08011112222"),
        db=db, actor=require_director(director_user)
    )
    setup_staff_payroll(
        data=StaffPayrollSetup(school_id=school.id, staff_id=staff.id, term_id=term.id, amount_scheduled_kobo=90_000_00),
        db=db, actor=require_director(director_user)
    )

    response = export_term_payroll_pdf(term_id=term.id, school_id=school.id, db=db, actor=require_director(director_user))
    assert response.media_type == "application/pdf"
    assert len(response.body) > 0
