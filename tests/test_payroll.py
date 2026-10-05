"""
Tests for staff salary payments, payslip generation, and role access control.
"""

import os
import pytest
from fastapi import HTTPException
from app.models import User, Payroll
from app.schemas.payroll import PayrollCreate
from app.routers.payroll import create_payroll, list_payroll, download_payslip
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


@pytest.fixture()
def staff_admin_user(db, school):
    u = User(
        school_id=school.id,
        email="bursar@jummikville.sch",
        hashed_password="hash",
        role="staff_admin",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_staff_admin_blocked_from_payroll(db, school, staff_admin_user):
    """Staff Admin accounts receive HTTP 403 when trying to access payroll."""
    with pytest.raises(HTTPException) as exc:
        list_payroll(school_id=school.id, db=db, actor=require_director(staff_admin_user))
    assert exc.value.status_code == 403


def test_director_records_payroll_and_audit(db, school, term, director_user):
    """Director records salary payment; verifies audit trail, payslip, and listing."""
    data = PayrollCreate(
        school_id=school.id,
        term_id=term.id,
        staff_name="Mr. Clement Udoh",
        phone_number="08031234567",
        amount_kobo=120_000_00,  # ₦120,000
        note="August Monthly Salary",
    )

    created = create_payroll(data=data, db=db, actor=require_director(director_user))

    assert created.staff_name == "Mr. Clement Udoh"
    assert created.amount_kobo == 120_000_00
    assert created.amount_display == "₦120,000.00"
    assert created.processed_by_email == "director@jummikville.sch"

    # Verify database persistence & audit trail
    p_row = db.query(Payroll).filter(Payroll.id == created.id).first()
    assert p_row is not None
    assert p_row.processed_by_user_id == director_user.id

    # Verify listing
    items = list_payroll(school_id=school.id, term_id=term.id, db=db, actor=require_director(director_user))
    assert len(items) == 1
    assert items[0].id == created.id


def test_download_payslip(db, school, term, director_user):
    """Verify downloading a payslip PDF."""
    data = PayrollCreate(
        school_id=school.id,
        term_id=term.id,
        staff_name="Mrs. Aniefiok Bassey",
        phone_number="08098765432",
        amount_kobo=95_000_00,
    )
    created = create_payroll(data=data, db=db, actor=require_director(director_user))

    response = download_payslip(payroll_id=created.id, db=db, actor=require_director(director_user))
    assert response.media_type == "application/pdf"
    assert os.path.exists(response.path)
