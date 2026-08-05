"""
Expense service (Part C) — the single place expense logic lives.

Everything the app does with expenses flows through here: create/list/update/delete
plus the total used by the dashboard's Net Available card (Part D). Keeping it in
one module mirrors payment_service — routers stay thin, business rules stay testable.

MONEY NOTE: expense.amount_kobo is a REAL stored integer column (not a derived
property like FeeRecord's paid amount), so total_expenses_kobo may sum in SQL.

AUDIT: create_expense stamps the acting admin (created_by_user_id) and writes an
ActivityLog(action="expense_recorded") in the SAME transaction — the audit trail
Part J builds on.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Expense, ActivityLog, User
from app.schemas.expense import ExpenseCreate, ExpenseUpdate
from app.services.term_service import get_current_term
from app.utils.formatting import kobo_to_naira

logger = logging.getLogger(__name__)


class ExpenseError(Exception):
    """Raised for expense operations the caller got wrong (mapped to 4xx)."""


def create_expense(
    db: Session,
    school_id: int,
    data: ExpenseCreate,
    user: User | None = None,
) -> Expense:
    """
    Record a new expense.

    - Resolves term_id: the one provided → else the school's current term → else
      null (an expense can exist before any term is marked current).
    - Stamps created_by_user_id from the acting admin (audit actor).
    - expense_date defaults to today (UTC) if omitted.
    - Writes an activity-log entry in the same transaction, then commits.
    """
    # Resolve the term this expense belongs to.
    term_id = data.term_id
    if term_id is None:
        current = get_current_term(db, school_id)
        term_id = current.id if current else None

    expense_date = data.expense_date or datetime.now(timezone.utc).date()

    expense = Expense(
        school_id=school_id,
        term_id=term_id,
        category=data.category,
        amount_kobo=data.amount_kobo,
        purpose=data.purpose.strip(),
        expense_date=expense_date,
        note=(data.note.strip() if data.note else None),
        receipt_ref=(data.receipt_ref.strip() if data.receipt_ref else None),
        created_by_user_id=(user.id if user else None),
    )
    db.add(expense)
    db.flush()  # assign an id for the log line

    who = user.email if user else "system"
    db.add(
        ActivityLog(
            school_id=school_id,
            action="expense_recorded",
            description=(
                f"Expense recorded: {expense.category} "
                f"{kobo_to_naira(expense.amount_kobo)} — {expense.purpose} (by {who})"
            ),
        )
    )

    db.commit()
    db.refresh(expense)
    logger.info(
        f"Expense recorded: id={expense.id}, {expense.category}, "
        f"{expense.amount_kobo} kobo, by user {expense.created_by_user_id}"
    )
    return expense


def list_expenses(
    db: Session,
    school_id: int,
    term_id: int | None = None,
    category: str | None = None,
) -> list[Expense]:
    """
    All expenses for the school, newest first — visible to every admin (no
    per-creator filter). Optional term/category filters.
    """
    q = db.query(Expense).filter(Expense.school_id == school_id)
    if term_id is not None:
        q = q.filter(Expense.term_id == term_id)
    if category:
        q = q.filter(Expense.category == category)
    return q.order_by(
        Expense.expense_date.desc(), Expense.created_at.desc()
    ).all()


def get_expense(db: Session, school_id: int, expense_id: int) -> Expense:
    """Fetch one expense scoped to the school, or raise ExpenseError."""
    expense = (
        db.query(Expense)
        .filter(Expense.id == expense_id, Expense.school_id == school_id)
        .first()
    )
    if not expense:
        raise ExpenseError(f"Expense {expense_id} not found")
    return expense


def update_expense(
    db: Session,
    school_id: int,
    expense_id: int,
    data: ExpenseUpdate,
) -> Expense:
    """Patch an expense's fields (only those provided)."""
    expense = get_expense(db, school_id, expense_id)

    if data.category is not None:
        expense.category = data.category
    if data.amount_kobo is not None:
        expense.amount_kobo = data.amount_kobo
    if data.purpose is not None:
        expense.purpose = data.purpose.strip()
    if data.expense_date is not None:
        expense.expense_date = data.expense_date
    if data.note is not None:
        expense.note = data.note.strip() or None
    if data.receipt_ref is not None:
        expense.receipt_ref = data.receipt_ref.strip() or None
    if data.term_id is not None:
        expense.term_id = data.term_id

    db.commit()
    db.refresh(expense)
    logger.info(f"Expense updated: id={expense.id}")
    return expense


def delete_expense(db: Session, school_id: int, expense_id: int) -> None:
    """Delete an expense."""
    expense = get_expense(db, school_id, expense_id)
    db.delete(expense)
    db.commit()
    logger.info(f"Expense deleted: id={expense_id}")


def total_expenses_kobo(
    db: Session,
    school_id: int,
    term_id: int | None = None,
) -> int:
    """
    Sum of all expense amounts (kobo) for the school — the number behind the
    dashboard's Total Expenses / Net Available cards. amount_kobo is a real
    column, so this is a plain SQL SUM. Optional term filter (for Part E).
    """
    q = db.query(func.coalesce(func.sum(Expense.amount_kobo), 0)).filter(
        Expense.school_id == school_id
    )
    if term_id is not None:
        q = q.filter(Expense.term_id == term_id)
    return int(q.scalar() or 0)
