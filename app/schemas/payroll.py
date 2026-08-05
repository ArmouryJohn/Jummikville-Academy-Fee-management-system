"""
Pydantic schemas for Staff Payroll scheduling, payouts, summary cards, and comparisons.
"""

from datetime import datetime, date
from pydantic import BaseModel, Field


# --- Legacy / Simple Payroll Schemas (backward compatibility) ---

class PayrollCreate(BaseModel):
    """Legacy payload to record a salary payment."""
    school_id: int = Field(1, description="School ID")
    term_id: int | None = Field(None, description="Term ID")
    staff_name: str = Field(..., min_length=2, max_length=100)
    phone_number: str = Field(..., min_length=5, max_length=50)
    amount_kobo: int = Field(..., gt=0, description="Salary amount in kobo")
    payment_date: date | None = None
    note: str | None = None


class PayrollResponse(BaseModel):
    """Legacy response view of a salary payment."""
    id: int
    school_id: int
    term_id: int | None = None
    term_name: str | None = None
    staff_name: str
    phone_number: str
    amount_kobo: int
    amount_display: str
    payment_date: date
    note: str | None = None
    processed_by_email: str | None = None
    payslip_url: str
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Setup & Payout schemas ---

class StaffPayrollSetup(BaseModel):
    """Assign or update a staff member's scheduled salary for a term."""
    school_id: int = Field(1, description="School ID")
    staff_id: int = Field(..., description="Staff member ID")
    term_id: int = Field(..., description="Term ID")
    amount_scheduled_kobo: int = Field(..., ge=0, description="Scheduled term salary in kobo")
    note: str | None = None


class StaffPaymentCreate(BaseModel):
    """Record a payout transaction (full or installment) for a staff member's term salary."""
    payroll_record_id: int = Field(..., description="Payroll schedule record ID")
    amount_kobo: int = Field(..., gt=0, description="Payout amount in kobo")
    payment_date: date | None = Field(None, description="Date paid (defaults to today)")
    method: str = Field("bank_transfer", description="'bank_transfer' | 'cash' | 'check'")
    note: str | None = None


class StaffPaymentResponse(BaseModel):
    """Response view of a payout transaction."""
    id: int
    payroll_record_id: int
    amount_kobo: int
    amount_display: str
    payment_date: date
    method: str
    note: str | None = None
    processed_by_email: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class StaffPayrollRecordResponse(BaseModel):
    """Full detail of one staff member's payroll status for a term."""
    id: int
    school_id: int
    staff_id: int
    staff_name: str
    role_title: str
    phone_number: str
    bank_name: str | None = None
    account_number: str | None = None
    account_name: str | None = None
    classes_taught: list[str] = []
    term_id: int
    term_name: str
    amount_scheduled_kobo: int
    amount_paid_kobo: int
    remaining_kobo: int
    amount_scheduled_display: str
    amount_paid_display: str
    remaining_display: str
    status: str  # 'unpaid' | 'partial' | 'paid'
    note: str | None = None
    payouts: list[StaffPaymentResponse] = []
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Summary & Comparison schemas ---

class StaffPayrollSummary(BaseModel):
    """Dashboard headline numbers for staff payroll."""
    total_staff: int
    total_scheduled_kobo: int
    total_paid_kobo: int
    total_remaining_kobo: int
    total_scheduled_display: str
    total_paid_display: str
    total_remaining_display: str
    staff_paid_count: int
    staff_partial_count: int
    staff_unpaid_count: int
    completion_rate: int
    records: list[StaffPayrollRecordResponse] = []


class TermPayrollSnapshot(BaseModel):
    """Term payroll metrics snapshot for comparison."""
    term_id: int
    term_name: str
    total_staff: int
    total_scheduled_kobo: int
    total_paid_kobo: int
    total_remaining_kobo: int
    total_scheduled_display: str
    total_paid_display: str
    total_remaining_display: str
    completion_rate: int


class TermPayrollComparison(BaseModel):
    """Side-by-side comparison of 2 terms for staff payroll."""
    term1: TermPayrollSnapshot
    term2: TermPayrollSnapshot
    scheduled_change_kobo: int
    paid_change_kobo: int
    completion_rate_change: int
