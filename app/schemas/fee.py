"""
Pydantic schemas for Fee-related API requests and responses.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.utils.formatting import kobo_to_naira

from app.constants import SECTIONS

# The three school sections. Defined once here and reused so validation is
# consistent everywhere a section is accepted.
Section = Literal["Preschool", "Primary", "Smart Skills High School"]


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
    """
    Schema for creating a new fee type.

    A term can be given either by `term_id` (preferred — points at a real Term
    row) or by `term` name (resolved/created for you, so the existing UI that
    sends a term string keeps working). At least one must be provided.
    """
    school_id: int
    category_id: int = Field(..., description="Which FeeCategory this belongs to")
    section: Section = Field(..., description="Preschool, Primary, or Smart Skills High School")
    term_id: int | None = Field(None, description="The Term this fee belongs to (preferred)")
    term: str | None = Field(
        None, min_length=1, max_length=100, examples=["First Term 2025/2026"],
        description="Term name — resolved/created if term_id is not given"
    )
    amount_kobo: int = Field(
        ..., gt=0,
        examples=[7500000],
        description="Amount in kobo. ₦75,000 = 7500000 kobo"
    )

    @model_validator(mode="after")
    def _require_term(self):
        if self.term_id is None and not (self.term and self.term.strip()):
            raise ValueError("Provide either term_id or term")
        return self


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


# --------------------------------------------------------------------------
# Term rollover schemas
# --------------------------------------------------------------------------

class TermRolloverRequest(BaseModel):
    """
    Schema for starting a new term by rolling the fee catalog + student records
    forward. Explicit and human-triggered — there is no automatic rollover.
    """
    school_id: int
    from_term: str = Field(
        ..., min_length=1, max_length=100,
        examples=["Term 1 2025/2026"],
        description="The term to roll FROM (its catalog and unpaid balances)"
    )
    to_term: str = Field(
        ..., min_length=1, max_length=100,
        examples=["Term 2 2025/2026"],
        description="The new term to create records in"
    )
    section: Section | None = Field(
        None,
        description="Optional — restrict rollover to one section. If null, all sections."
    )
    carry_forward: bool = Field(
        True,
        description=(
            "When true (default), each student's UNPAID prior-term balance is "
            "carried into the new term as an 'Outstanding (Prior Term)' arrears "
            "record. When false, the new term starts clean."
        )
    )


class TermRolloverResponse(BaseModel):
    """Summary of what a rollover did."""
    from_term: str
    to_term: str
    fee_types_cloned: int
    records_created: int
    students_skipped: int
    arrears_carried: int
    arrears_total_kobo: int
    arrears_total_display: str = ""

    def model_post_init(self, __context) -> None:
        if not self.arrears_total_display:
            self.arrears_total_display = kobo_to_naira(self.arrears_total_kobo)
