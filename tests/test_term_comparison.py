"""
Tests for side-by-side comparison of academic terms.
"""

import pytest

from app.models import Student, FeeCategory, FeeType, FeeRecord, Term, User
from app.schemas.expense import ExpenseCreate
from app.services.expense_service import create_expense
from app.services.payment_service import record_payment
from app.services.report_service import compare_terms, ReportError
from app.services.security import hash_password


def _make_term(db, school, name, current=False):
    t = Term(school_id=school.id, name=name, is_current=current)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _make_fee_type(db, school, term, category_name="Tuition Fee"):
    cat = db.query(FeeCategory).filter(FeeCategory.school_id == school.id, FeeCategory.name == category_name).first()
    if not cat:
        cat = FeeCategory(school_id=school.id, name=category_name)
        db.add(cat)
        db.commit()
        db.refresh(cat)
    ft = FeeType(
        school_id=school.id,
        category_id=cat.id,
        term_id=term.id,
        section="Primary",
        amount_kobo=5_000_000,
    )
    db.add(ft)
    db.commit()
    db.refresh(ft)
    return ft


def _make_record(db, student, fee_type, total_kobo):
    r = FeeRecord(student_id=student.id, fee_type_id=fee_type.id, total_fees_kobo=total_kobo, status="unpaid")
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def test_compare_terms_side_by_side_isolation(db, school, student):
    """Verify that compare_terms returns distinct metrics for two terms without bleed."""
    term1 = _make_term(db, school, "First Term 2024/2025")
    term2 = _make_term(db, school, "Second Term 2024/2025")

    ft1 = _make_fee_type(db, school, term1)
    ft2 = _make_fee_type(db, school, term2)

    r1 = _make_record(db, student, ft1, 5_000_000)
    r2 = _make_record(db, student, ft2, 6_000_000)

    # Pay Term 1: 3,000,000 via cash
    record_payment(db=db, fee_record_id=r1.id, amount_kobo=3_000_000, method="cash", send_confirmation=False)
    # Pay Term 2: 6,000,000 via paystack
    record_payment(db=db, fee_record_id=r2.id, amount_kobo=6_000_000, method="paystack", send_confirmation=False)

    # Add expense to Term 1
    admin = User(school_id=school.id, email="dir@jummikville.sch", hashed_password=hash_password("pw"), role="admin")
    db.add(admin)
    db.commit()
    db.refresh(admin)

    create_expense(db, school.id, ExpenseCreate(category="Repairs", amount_kobo=1_000_000, purpose="Roof fix", term_id=term1.id), user=admin)

    comparison = compare_terms(db, school_id=school.id, term_id_1=term1.id, term_id_2=term2.id)

    assert comparison.term1.term_name == "First Term 2024/2025"
    assert comparison.term1.total_expected_kobo == 5_000_000
    assert comparison.term1.total_collected_kobo == 3_000_000
    assert comparison.term1.total_remaining_kobo == 2_000_000
    assert comparison.term1.total_expenses_kobo == 1_000_000
    assert comparison.term1.net_available_kobo == 2_000_000  # 3m - 1m
    assert comparison.term1.collection_rate == 60

    assert comparison.term2.term_name == "Second Term 2024/2025"
    assert comparison.term2.total_expected_kobo == 6_000_000
    assert comparison.term2.total_collected_kobo == 6_000_000
    assert comparison.term2.total_remaining_kobo == 0
    assert comparison.term2.total_expenses_kobo == 0
    assert comparison.term2.net_available_kobo == 6_000_000
    assert comparison.term2.collection_rate == 100


def test_compare_terms_invalid_term_raises(db, school):
    term1 = _make_term(db, school, "Term A")
    with pytest.raises(ReportError):
        compare_terms(db, school_id=school.id, term_id_1=term1.id, term_id_2=99999)
