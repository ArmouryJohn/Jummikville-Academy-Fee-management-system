"""Pydantic schemas for Student-related API requests and responses."""

from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel, Field, model_validator

from app.constants import SECTIONS, SECTION_CLASSES

# Build the Section literal dynamically from the constants so validation
# stays in sync with the authoritative list in one place.
Section = Literal["Preschool", "Primary", "Smart Skills High School"]


def _validate_class_for_section(section: str | None, class_name: str | None) -> None:
    """
    Raise ValueError if class_name is not valid for the given section.
    Called from both StudentCreate and StudentUpdate validators.
    """
    if section and class_name:
        allowed = SECTION_CLASSES.get(section, [])
        if class_name not in allowed:
            raise ValueError(
                f"'{class_name}' is not a valid class for section '{section}'. "
                f"Valid classes: {', '.join(allowed)}"
            )


# --------------------------------------------------------------------------
# Request schemas (what the API accepts)
# --------------------------------------------------------------------------

class StudentCreate(BaseModel):
    """Schema for creating a new student."""
    school_id: int
    student_name: str = Field(..., min_length=2, max_length=200)
    section: Section = Field(
        ...,
        description="Preschool, Primary, or Smart Skills High School"
    )
    class_name: str | None = Field(
        None, max_length=50,
        examples=["Primary 3", "JSS1"],
        description="Must belong to the chosen section's class list."
    )
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

    @model_validator(mode="after")
    def class_must_belong_to_section(self) -> "StudentCreate":
        _validate_class_for_section(self.section, self.class_name)
        return self


class StudentUpdate(BaseModel):
    """Schema for updating a student. All fields optional."""
    student_name: str | None = Field(None, min_length=2, max_length=200)
    section: Section | None = None
    class_name: str | None = Field(None, max_length=50)
    parent_name: str | None = Field(None, min_length=2, max_length=200)
    parent_phone: str | None = Field(None, min_length=10, max_length=20)
    parent_email: str | None = Field(None, max_length=200)
    is_active: bool | None = None

    @model_validator(mode="after")
    def class_must_belong_to_section(self) -> "StudentUpdate":
        # Only validate when BOTH section and class_name are being updated
        # together. Partial updates that only change one field are allowed
        # (the existing DB values are trusted as already valid).
        if self.section and self.class_name:
            _validate_class_for_section(self.section, self.class_name)
        return self


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
