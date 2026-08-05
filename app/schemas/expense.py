"""
Pydantic schemas for Expense API requests and responses (Part C).

An Expense is one outgoing spend — money the school pays out, bucketed by a fixed
category (EXPENSE_CATEGORIES). Money is integer kobo, echoed as a twin
amount_kobo / amount_display pair like everywhere else in the app. The response
also carries the recorder's email and the term name (read-through) so the UI can
show "who / when / which term" without extra lookups.
"""

from datetime import datetime, date

from pydantic import BaseModel, Field, field_validator

from app.constants import EXPENSE_CATEGORIES
from app.utils.formatting import kobo_to_naira


class ExpenseCreate(BaseModel):
    """Record a new expense. amount_kobo is kobo (₦15,000 = 1500000)."""
    category: str = Field(
        ..., examples=["Fuel"],
        description=f"One of: {', '.join(EXPENSE_CATEGORIES)}"
    )
    amount_kobo: int = Field(
        ..., gt=0, examples=[1500000],
        description="Amount spent in kobo. Must be > 0. ₦15,000 = 1500000"
    )
    purpose: str = Field(
        ..., min_length=2, max_length=200,
        examples=["Generator repair"],
        description="What the money was spent on"
    )
    expense_date: date | None = Field(
        None, description="Date of the spend. Defaults to today if omitted."
    )
    note: str | None = Field(None, max_length=1000)
    receipt_ref: str | None = Field(
        None, max_length=120,
        description="Optional vendor slip / receipt reference (free text)"
    )
    term_id: int | None = Field(
        None,
        description="Term this expense belongs to. Defaults to the current term."
    )

    @field_validator("category")
    @classmethod
    def _known_category(cls, v: str) -> str:
        v = v.strip()
        if v not in EXPENSE_CATEGORIES:
            raise ValueError(
                f"Unknown category '{v}'. Must be one of: {', '.join(EXPENSE_CATEGORIES)}"
            )
        return v


class ExpenseUpdate(BaseModel):
    """Edit an expense. All fields optional (partial update)."""
    category: str | None = None
    amount_kobo: int | None = Field(None, gt=0)
    purpose: str | None = Field(None, min_length=2, max_length=200)
    expense_date: date | None = None
    note: str | None = Field(None, max_length=1000)
    receipt_ref: str | None = Field(None, max_length=120)
    term_id: int | None = None

    @field_validator("category")
    @classmethod
    def _known_category(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if v not in EXPENSE_CATEGORIES:
            raise ValueError(
                f"Unknown category '{v}'. Must be one of: {', '.join(EXPENSE_CATEGORIES)}"
            )
        return v


class ExpenseResponse(BaseModel):
    """An expense in API responses."""
    id: int
    school_id: int
    term_id: int | None
    term_name: str | None = None
    category: str
    amount_kobo: int
    amount_display: str = ""
    purpose: str
    expense_date: date
    note: str | None
    receipt_ref: str | None
    created_by_user_id: int | None
    created_by_email: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

    def model_post_init(self, __context) -> None:
        if not self.amount_display:
            self.amount_display = kobo_to_naira(self.amount_kobo)
