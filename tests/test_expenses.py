"""
Part C — Expenses + Part D — Net Funds tests.

Exercises app/services/expense_service (the single home of expense logic) and the
Part D dashboard guarantee: expenses reduce Net Available WITHOUT touching any
student's fee balance. In-memory SQLite, network stubbed by conftest.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from app.models import User, Expense, ActivityLog
from app.schemas.expense import ExpenseCreate, ExpenseUpdate
from app.services.expense_service import (
    ExpenseError,
    create_expense,
    delete_expense,
    list_expenses,
    total_expenses_kobo,
    update_expense,
)
from app.services.payment_service import record_payment
from app.services.security import hash_password


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def admin(db, school):
    """An admin user to stamp as the expense recorder."""
    u = User(
        school_id=school.id,
        email="admin@jummikville.sch",
        hashed_password=hash_password("secret123"),
        role="admin",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _create(db, school, admin, **overrides):
    data = {
        "category": "Fuel",
        "amount_kobo": 1_500_000,
        "purpose": "Generator diesel",
    }
    data.update(overrides)
    return create_expense(db, school.id, ExpenseCreate(**data), user=admin)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
def test_create_stores_kobo_stamps_actor_defaults_term_and_logs(db, school, term, admin):
    expense = _create(db, school, admin)

    assert expense.id is not None
    assert expense.amount_kobo == 1_500_000  # stored as kobo
    assert expense.created_by_user_id == admin.id  # audit actor stamped
    assert expense.term_id == term.id  # defaulted to the current term
    assert expense.expense_date == date.today()  # defaulted to today

    # An activity-log entry was written in the same transaction.
    log = (
        db.query(ActivityLog)
        .filter(ActivityLog.action == "expense_recorded")
        .first()
    )
    assert log is not None
    assert "Fuel" in log.description


def test_create_uses_provided_date_and_term(db, school, term, admin):
    expense = _create(
        db, school, admin,
        expense_date=date(2025, 10, 5),
        term_id=term.id,
    )
    assert expense.expense_date == date(2025, 10, 5)
    assert expense.term_id == term.id


def test_create_without_current_term_leaves_term_null(db, school, admin):
    """No current term marked → term_id resolves to null, not an error."""
    expense = _create(db, school, admin)
    assert expense.term_id is None


def test_reject_zero_or_negative_amount(db, school, admin):
    with pytest.raises(ValidationError):
        ExpenseCreate(category="Fuel", amount_kobo=0, purpose="x")
    with pytest.raises(ValidationError):
        ExpenseCreate(category="Fuel", amount_kobo=-100, purpose="x")


def test_reject_unknown_category(db, school, admin):
    with pytest.raises(ValidationError):
        ExpenseCreate(category="Bribes", amount_kobo=1000, purpose="x")


# ---------------------------------------------------------------------------
# List / total
# ---------------------------------------------------------------------------
def test_total_expenses_sums_and_filters_by_term(db, school, term, admin):
    # A second (non-current) term to prove the term filter isolates spend.
    from app.models import Term
    other = Term(school_id=school.id, name="Second Term 2025/2026", is_current=False)
    db.add(other)
    db.commit()
    db.refresh(other)

    _create(db, school, admin, amount_kobo=1_500_000, term_id=term.id)
    _create(db, school, admin, category="Repairs", amount_kobo=2_000_000, term_id=term.id)
    _create(db, school, admin, category="Events", amount_kobo=500_000, term_id=other.id)

    # Whole-school (all-time) total across both terms.
    assert total_expenses_kobo(db, school.id) == 4_000_000
    # Term-scoped total excludes the other term's row.
    assert total_expenses_kobo(db, school.id, term_id=term.id) == 3_500_000


def test_list_returns_all_and_filters_by_category(db, school, term, admin):
    _create(db, school, admin, category="Fuel")
    _create(db, school, admin, category="Repairs")

    everything = list_expenses(db, school.id)
    assert len(everything) == 2

    fuel_only = list_expenses(db, school.id, category="Fuel")
    assert len(fuel_only) == 1
    assert fuel_only[0].category == "Fuel"


# ---------------------------------------------------------------------------
# Update / delete
# ---------------------------------------------------------------------------
def test_update_changes_fields(db, school, term, admin):
    expense = _create(db, school, admin)
    updated = update_expense(
        db, school.id, expense.id,
        ExpenseUpdate(amount_kobo=999_900, purpose="Revised"),
    )
    assert updated.amount_kobo == 999_900
    assert updated.purpose == "Revised"


def test_delete_removes_expense(db, school, term, admin):
    expense = _create(db, school, admin)
    delete_expense(db, school.id, expense.id)
    assert db.query(Expense).count() == 0


def test_delete_unknown_raises(db, school, admin):
    with pytest.raises(ExpenseError):
        delete_expense(db, school.id, 9999)


# ---------------------------------------------------------------------------
# Part D — net-funds invariant
# ---------------------------------------------------------------------------
def test_expense_never_touches_student_balances(db, school, term, admin, fee_record):
    """
    The core Part D guarantee: after a payment AND an expense, Net Available =
    Collected − Expenses, while total_remaining and the student's balance are
    UNCHANGED by the expense.
    """
    from app.routers.dashboard import dashboard_summary

    # Record a ₦30,000 payment against the ₦75,000 fee.
    record_payment(
        db=db, fee_record_id=fee_record.id, amount_kobo=3_000_000,
        method="cash", send_confirmation=False,
    )

    before = dashboard_summary(school_id=school.id, section=None, class_name=None, db=db)
    assert before.total_collected_kobo == 3_000_000
    assert before.total_remaining_kobo == 4_500_000
    assert before.total_expenses_kobo == 0
    assert before.net_available_kobo == 3_000_000  # nothing spent yet

    # Now spend ₦15,000.
    _create(db, school, admin, amount_kobo=1_500_000)

    after = dashboard_summary(school_id=school.id, section=None, class_name=None, db=db)
    # Expenses show up...
    assert after.total_expenses_kobo == 1_500_000
    assert after.net_available_kobo == after.total_collected_kobo - after.total_expenses_kobo
    assert after.net_available_kobo == 1_500_000
    # ...but student-facing fee numbers are UNCHANGED by the expense.
    assert after.total_collected_kobo == before.total_collected_kobo
    assert after.total_remaining_kobo == before.total_remaining_kobo

    # The underlying fee record's balance is untouched too.
    db.refresh(fee_record)
    assert fee_record.remaining_kobo == 4_500_000
