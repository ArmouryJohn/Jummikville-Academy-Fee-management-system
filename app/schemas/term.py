"""
Pydantic schemas for Term API requests and responses.

A Term is a real academic term ("First Term 2025/2026") with optional dates and
a manual is_current flag. Fee types, reports, expenses, and payroll all key off
a term, so it's a first-class managed resource rather than a free-text string.
"""

from datetime import datetime, date

from pydantic import BaseModel, Field


class TermCreate(BaseModel):
    """Create a new term. Dates are optional; is_current is set separately."""
    school_id: int
    name: str = Field(
        ..., min_length=1, max_length=100,
        examples=["First Term 2025/2026"],
        description="Unique per school — e.g. 'First Term 2025/2026'"
    )
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = Field(
        False,
        description="Mark this term current on creation (clears the flag on other terms)"
    )


class TermUpdate(BaseModel):
    """Edit a term's name or dates. All fields optional (partial update)."""
    name: str | None = Field(None, min_length=1, max_length=100)
    start_date: date | None = None
    end_date: date | None = None


class TermResponse(BaseModel):
    """A term in API responses."""
    id: int
    school_id: int
    name: str
    start_date: date | None
    end_date: date | None
    is_current: bool
    created_at: datetime
    fee_type_count: int = 0  # how many fee types reference this term

    model_config = {"from_attributes": True}
