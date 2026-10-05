"""
Expense management endpoints for recording and tracking school operational costs.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.constants import EXPENSE_CATEGORIES
from app.database import get_db
from app.models import User
from app.schemas.expense import ExpenseCreate, ExpenseUpdate, ExpenseResponse
from app.services.auth_deps import get_current_user
from app.services.expense_service import (
    ExpenseError,
    create_expense,
    delete_expense,
    list_expenses,
    total_expenses_kobo,
    update_expense,
)
from app.utils.formatting import kobo_to_naira

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/expenses", tags=["Expenses"])

# Jummikville is single-school (the frontend hardcodes CONFIG.SCHOOL_ID = 1); the
# school_id query param defaults to it so the UI need not pass it. Mirrors reports.
_DEFAULT_SCHOOL_ID = 1


def _to_response(expense) -> ExpenseResponse:
    """Build an ExpenseResponse, reading the recorder email + term name through."""
    resp = ExpenseResponse.model_validate(expense)
    resp.created_by_email = (
        expense.created_by_user.email if expense.created_by_user else None
    )
    resp.term_name = expense.term.name if expense.term else None
    return resp


@router.get("/categories", response_model=list[str])
def get_expense_categories():
    """The fixed list of expense categories (for the create dropdown)."""
    return EXPENSE_CATEGORIES


@router.get("", response_model=list[ExpenseResponse])
def get_expenses(
    school_id: int = Query(_DEFAULT_SCHOOL_ID),
    term_id: int | None = Query(None, description="Filter to one term"),
    category: str | None = Query(None, description="Filter to one category"),
    db: Session = Depends(get_db),
):
    """List expenses (newest first), visible to all admins. Optional filters."""
    expenses = list_expenses(db, school_id, term_id=term_id, category=category)
    return [_to_response(e) for e in expenses]


@router.get("/total")
def get_expenses_total(
    school_id: int = Query(_DEFAULT_SCHOOL_ID),
    term_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """Total expenses (kobo + display) — powers the page's summary line."""
    total = total_expenses_kobo(db, school_id, term_id=term_id)
    return {"total_expenses_kobo": total, "total_expenses_display": kobo_to_naira(total)}


@router.post("", response_model=ExpenseResponse, status_code=201)
def create_expense_endpoint(
    data: ExpenseCreate,
    school_id: int = Query(_DEFAULT_SCHOOL_ID),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Record an expense. The acting admin is stamped as the audit actor."""
    expense = create_expense(db, school_id, data, user=current_user)
    return _to_response(expense)


@router.patch("/{expense_id}", response_model=ExpenseResponse)
def update_expense_endpoint(
    expense_id: int,
    data: ExpenseUpdate,
    school_id: int = Query(_DEFAULT_SCHOOL_ID),
    db: Session = Depends(get_db),
):
    """Edit an expense (partial update)."""
    try:
        expense = update_expense(db, school_id, expense_id, data)
    except ExpenseError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _to_response(expense)


@router.delete("/{expense_id}", status_code=200)
def delete_expense_endpoint(
    expense_id: int,
    school_id: int = Query(_DEFAULT_SCHOOL_ID),
    db: Session = Depends(get_db),
):
    """Delete an expense."""
    try:
        delete_expense(db, school_id, expense_id)
    except ExpenseError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deleted": True, "id": expense_id}
