"""
Pydantic schemas for Fee-related API requests and responses.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.utils.formatting import kobo_to_naira

# The three school sections. Defined once here and reused so validation is
# consistent everywhere a section is accepted.
Section = Literal["Nursery", "Primary", "Secondary"]


# --------------------------------------------------------------------------
# FeeCategory schemas (the permanent, staff-managed master list)
# --------------------------------------------------------------------------

class FeeCategoryCreate(BaseModel):
    """Schema for adding a new fee category (e.g. 'Uniform Fee')."""
    school_id: int
    name: str = Field(..., min_length=2, max_length=100, examples=["Tuition Fee"])


class FeeCategoryResponse(BaseModel):
    """Schema for a fee category in API responses."""
    id: int
    school_id: int
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --------------------------------------------------------------------------
# FeeType schemas ("this category, this section, this term, this amount")
# --------------------------------------------------------------------------

class FeeTypeCreate(BaseModel):
    """Schema for creating a new fee type."""
    school_id: int
    category_id: int = Field(..., description="Which FeeCategory this belongs to")
    section: Section = Field(..., description="Nursery, Primary, or Secondary")
    term: str = Field(..., min_length=1, max_length=100, examples=["Term 1 2025/2026"])
    amount_kobo: int = Field(
        ..., gt=0,
        examples=[7500000],
        description="Amount in kobo. ₦75,000 = 7500000 kobo"
    )


class FeeTypeResponse(BaseModel):
    """Schema for fee type in API responses."""
    id: int
    school_id: int
    category_id: int
    name: str  # comes from the category (FeeType.name property)
    section: str
    term: str
    amount_kobo: int
    amount_display: str = ""  # Human-readable naira amount
    created_at: datetime

    model_config = {"from_attributes": True}

    def model_post_init(self, __context) -> None:
        """Add a human-readable amount after the model is created."""
        if not self.amount_display:
            self.amount_display = kobo_to_naira(self.amount_kobo)


# --------------------------------------------------------------------------
# FeeRecord schemas
# --------------------------------------------------------------------------

class FeeRecordCreate(BaseModel):
    """Schema for assigning a fee to a student."""
    student_id: int
    fee_type_id: int
    total_fees_kobo: int = Field(
        ..., gt=0,
        description=(
            "Total amount owed in kobo. Usually matches the fee type's amount, "
            "but can be overridden per student (e.g., scholarship discount)."
        )
    )


class FeeRecordResponse(BaseModel):
    """Schema for fee record in API responses. Includes computed balance."""
    id: int
    student_id: int
    fee_type_id: int
    total_fees_kobo: int
    amount_paid_kobo: int
    balance_kobo: int  # Computed property from the model (can be negative if overpaid)
    remaining_kobo: int  # What's left to complete (never negative)
    overpaid_kobo: int  # Credit owed back (never negative)
    status: str
    total_display: str = ""
    paid_display: str = ""
    balance_display: str = ""
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    def model_post_init(self, __context) -> None:
        """Add human-readable amounts after the model is created."""
        if not self.total_display:
            self.total_display = kobo_to_naira(self.total_fees_kobo)
        if not self.paid_display:
            self.paid_display = kobo_to_naira(self.amount_paid_kobo)
        if not self.balance_display:
            self.balance_display = kobo_to_naira(self.balance_kobo)


class BulkFeeAssign(BaseModel):
    """
    Schema for assigning a fee type to multiple students at once.
    Useful when a school wants to assign "Tuition Term 1" to all JSS 2 students.
    """
    fee_type_id: int
    student_ids: list[int] = Field(
        ..., min_length=1,
        description="List of student IDs to assign this fee to"
    )
    total_fees_kobo: int | None = Field(
        None,
        description="Override amount per student. If null, uses the fee type's default amount."
    )
