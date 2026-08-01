"""
Pydantic schemas for Student-related API requests and responses.

WHY SEPARATE SCHEMAS FROM MODELS:
- Models define how data is STORED (database columns)
- Schemas define how data is SENT/RECEIVED (API requests and responses)
- A create request might need fewer fields than a response
- Schemas validate input before it ever reaches the database
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# The three school sections. Every student belongs to exactly one; it drives the
# per-section dashboard stats, so it is required on create.
Section = Literal["Nursery", "Primary", "Secondary"]


# --------------------------------------------------------------------------
# Request schemas (what the API accepts)
# --------------------------------------------------------------------------

class StudentCreate(BaseModel):
    """Schema for creating a new student."""
    school_id: int
    student_name: str = Field(..., min_length=2, max_length=200)
    section: Section = Field(..., description="Nursery, Primary, or Secondary")
    class_name: str | None = Field(None, max_length=50, examples=["JSS 2", "SS 1"])
    parent_name: str = Field(..., min_length=2, max_length=200)
    parent_phone: str = Field(
        ..., min_length=10, max_length=20,
        examples=["08012345678", "+2348012345678"],
        description="Nigerian phone number (will be normalized to +234...)"
    )
    parent_email: str | None = Field(
        None, max_length=200,
        examples=["parent@email.com"],
        description="Email for Paystack. If not provided, a placeholder will be used."
    )


class StudentUpdate(BaseModel):
    """Schema for updating a student. All fields optional."""
    student_name: str | None = Field(None, min_length=2, max_length=200)
    section: Section | None = None
    class_name: str | None = Field(None, max_length=50)
    parent_name: str | None = Field(None, min_length=2, max_length=200)
    parent_phone: str | None = Field(None, min_length=10, max_length=20)
    parent_email: str | None = Field(None, max_length=200)
    is_active: bool | None = None


# --------------------------------------------------------------------------
# Response schemas (what the API returns)
# --------------------------------------------------------------------------

class StudentResponse(BaseModel):
    """Schema for student data in API responses."""
    id: int
    school_id: int
    student_name: str
    section: str
    class_name: str | None
    parent_name: str
    parent_phone: str
    parent_email: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
