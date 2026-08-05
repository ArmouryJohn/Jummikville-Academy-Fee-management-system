"""
Tests for Part F — Dashboard Insights.

Validates that GET /api/v1/dashboard/summary accurately returns:
1. top_unpaid_class (class with highest total outstanding fee balance)
2. most_common_payment_method (e.g. 'Paystack (Online)', 'Cash', etc.)
3. biggest_expense_category (category with highest spend)
4. collection_by_section (per-section collection percentage dict)
"""

import pytest
from app.models import Student, FeeRecord, FeeType, FeeCategory, Expense
from app.routers.dashboard import dashboard_summary
from app.services.payment_service import record_payment


def test_dashboard_insights_empty_school(db, school):
    """When a school has no students, payments, or expenses, insights should handle gracefully."""
    summary = dashboard_summary(school_id=school.id, section=None, class_name=None, db=db)
    insights = summary.insights

    assert insights is not None
    assert insights.top_unpaid_class is None
    assert insights.top_unpaid_class_remaining_kobo == 0
    assert insights.top_unpaid_class_remaining_display == "₦0.00"

    assert insights.most_common_payment_method is None

    assert insights.biggest_expense_category is None
    assert insights.biggest_expense_category_kobo == 0
    assert insights.biggest_expense_category_display == "₦0.00"

    assert insights.collection_by_section == {}


def test_dashboard_insights_top_unpaid_class(db, school, term):
    """Verify that the class with highest remaining unpaid balance is picked as top_unpaid_class."""
    # Category and fee type
    cat = FeeCategory(school_id=school.id, name="Tuition Fee")
    db.add(cat)
    db.flush()
    ft = FeeType(school_id=school.id, category_id=cat.id, section="Primary", term_id=term.id, amount_kobo=50_000_00)
    db.add(ft)
    db.flush()

    # Class A: Primary 1 (2 students, total expected ₦100,000, ₦0 paid) -> remaining ₦100,000
    s1 = Student(school_id=school.id, student_name="Student A1", section="Primary", class_name="Primary 1", parent_name="P1", parent_phone="+2348011111111")
    s2 = Student(school_id=school.id, student_name="Student A2", section="Primary", class_name="Primary 1", parent_name="P2", parent_phone="+2348022222222")
    db.add_all([s1, s2])
    db.flush()

    r1 = FeeRecord(student_id=s1.id, fee_type_id=ft.id, total_fees_kobo=50_000_00, status="unpaid")
    r2 = FeeRecord(student_id=s2.id, fee_type_id=ft.id, total_fees_kobo=50_000_00, status="unpaid")
    db.add_all([r1, r2])

    # Class B: Primary 3 (1 student, total expected ₦150,000, ₦0 paid) -> remaining ₦150,000
    s3 = Student(school_id=school.id, student_name="Student B1", section="Primary", class_name="Primary 3", parent_name="P3", parent_phone="+2348033333333")
    db.add(s3)
    db.flush()
    r3 = FeeRecord(student_id=s3.id, fee_type_id=ft.id, total_fees_kobo=150_000_00, status="unpaid")
    db.add(r3)
    db.commit()

    summary = dashboard_summary(school_id=school.id, section=None, class_name=None, db=db)
    insights = summary.insights

    assert insights.top_unpaid_class == "Primary 3"
    assert insights.top_unpaid_class_remaining_kobo == 150_000_00
    assert "150,000" in insights.top_unpaid_class_remaining_display


def test_dashboard_insights_most_common_payment_method(db, school, fee_record):
    """Verify that payment method counts are evaluated to find the most common method."""
    # Add 2 paystack payments and 1 cash payment
    record_payment(db, fee_record_id=fee_record.id, amount_kobo=10_000_00, method="paystack")
    record_payment(db, fee_record_id=fee_record.id, amount_kobo=10_000_00, method="paystack")
    record_payment(db, fee_record_id=fee_record.id, amount_kobo=5_000_00, method="cash")

    summary = dashboard_summary(school_id=school.id, section=None, class_name=None, db=db)
    insights = summary.insights

    assert insights.most_common_payment_method == "Paystack (Online)"


def test_dashboard_insights_biggest_expense_category(db, school, term):
    """Verify that biggest expense category is calculated correctly by total spend in kobo."""
    e1 = Expense(school_id=school.id, term_id=term.id, category="Textbooks", amount_kobo=50_000_00, purpose="Math books")
    e2 = Expense(school_id=school.id, term_id=term.id, category="Repairs", amount_kobo=120_000_00, purpose="Gen repair")
    e3 = Expense(school_id=school.id, term_id=term.id, category="Textbooks", amount_kobo=20_000_00, purpose="English books")
    db.add_all([e1, e2, e3])
    db.commit()

    summary = dashboard_summary(school_id=school.id, section=None, class_name=None, db=db)
    insights = summary.insights

    assert insights.biggest_expense_category == "Repairs"
    assert insights.biggest_expense_category_kobo == 120_000_00
    assert "120,000" in insights.biggest_expense_category_display


def test_dashboard_insights_collection_by_section(db, school, term):
    """Verify collection percentage per section."""
    cat = FeeCategory(school_id=school.id, name="Tuition")
    db.add(cat)
    db.flush()

    ft_pre = FeeType(school_id=school.id, category_id=cat.id, section="Preschool", term_id=term.id, amount_kobo=100_000_00)
    ft_pri = FeeType(school_id=school.id, category_id=cat.id, section="Primary", term_id=term.id, amount_kobo=100_000_00)
    db.add_all([ft_pre, ft_pri])
    db.flush()

    s_pre = Student(school_id=school.id, student_name="Kid 1", section="Preschool", class_name="Nursery 1", parent_name="P1", parent_phone="+234801")
    s_pri = Student(school_id=school.id, student_name="Kid 2", section="Primary", class_name="Primary 1", parent_name="P2", parent_phone="+234802")
    db.add_all([s_pre, s_pri])
    db.flush()

    r_pre = FeeRecord(student_id=s_pre.id, fee_type_id=ft_pre.id, total_fees_kobo=100_000_00, status="unpaid")
    r_pri = FeeRecord(student_id=s_pri.id, fee_type_id=ft_pri.id, total_fees_kobo=100_000_00, status="unpaid")
    db.add_all([r_pre, r_pri])
    db.commit()

    # Pay 50,000 for preschool (50%) and 100,000 for primary (100%)
    record_payment(db, fee_record_id=r_pre.id, amount_kobo=50_000_00, method="cash")
    record_payment(db, fee_record_id=r_pri.id, amount_kobo=100_000_00, method="cash")

    summary = dashboard_summary(school_id=school.id, section=None, class_name=None, db=db)
    insights = summary.insights

    assert insights.collection_by_section.get("Preschool") == 50
    assert insights.collection_by_section.get("Primary") == 100
