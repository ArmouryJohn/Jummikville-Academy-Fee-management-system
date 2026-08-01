"""
Pydantic schemas for the dashboard and student-overview endpoints.

These schemas exist purely to serve the frontend. They combine data that lives
across several tables (students + fee records + payments) into the exact shapes
the Dashboard and Parents screens need, so the frontend never has to stitch
things together itself.

Every money value is returned twice:
- `*_kobo`  → the raw integer, for any maths the frontend might do
- `*_display` → a ready-to-show "₦75,000.00" string, so formatting is consistent
                everywhere and the frontend never re-implements it
"""

from datetime import datetime

from pydantic import BaseModel


class CategoryBreakdown(BaseModel):
    """
    Per-category collection numbers, so the dashboard can show
    "Textbook Fee: ₦120,000 collected of ₦300,000" alongside every other category.
    """
    category_id: int
    category_name: str

    total_expected_kobo: int
    total_collected_kobo: int
    total_remaining_kobo: int
    total_overpaid_kobo: int

    total_expected_display: str
    total_collected_display: str
    total_remaining_display: str
    total_overpaid_display: str


class SectionSummary(BaseModel):
    """
    The four headline numbers for one school section (or the whole school when
    section is 'All'): Total Fee, Collected, Remaining, Overpaid.
    """
    section: str  # 'Nursery' | 'Primary' | 'Secondary' | 'All'

    total_students: int

    total_expected_kobo: int
    total_collected_kobo: int
    total_remaining_kobo: int  # what's still owed to complete (never negative)
    total_overpaid_kobo: int  # credit owed back to parents (never negative)

    total_expected_display: str
    total_collected_display: str
    total_remaining_display: str
    total_overpaid_display: str


class DashboardSummary(BaseModel):
    """
    Top-of-dashboard numbers and the paid/unpaid breakdown for the chart.

    Returns whole-school figures plus a per-section list, so the frontend can
    switch between "All", "Nursery", "Primary", and "Secondary" without another
    round-trip. `sections` always includes an 'All' entry (whole school).
    """
    school_id: int
    school_name: str

    total_students: int

    # ---- Whole-school headline numbers (the four the user asked for) ----
    total_expected_kobo: int
    total_collected_kobo: int
    total_remaining_kobo: int
    total_overpaid_kobo: int

    total_expected_display: str
    total_collected_display: str
    total_remaining_display: str
    total_overpaid_display: str

    # Collection rate as a whole-number percentage (0–100), for a progress bar
    collection_rate: int

    # How many students fall into each bucket — drives the paid/unpaid visual
    students_paid: int
    students_partial: int
    students_unpaid: int
    students_overpaid: int = 0
    # Students with no fees assigned yet — kept distinct from 'paid' so the
    # gap is visible instead of masquerading as fully-settled.
    students_no_fee: int = 0

    # Per-section headline numbers ('All' + each section that has data)
    sections: list[SectionSummary] = []

    # Per-category collection breakdown (whole school)
    categories: list[CategoryBreakdown] = []


class StudentOverview(BaseModel):
    """One row in the Parents/Students list — everything the table shows."""
    student_id: int
    student_name: str
    section: str
    class_name: str | None
    parent_name: str
    parent_phone: str
    parent_email: str | None

    total_fees_kobo: int
    amount_paid_kobo: int
    balance_kobo: int
    remaining_kobo: int  # what's left to complete (never negative)
    overpaid_kobo: int  # credit owed back (never negative)

    total_fees_display: str
    amount_paid_display: str
    balance_display: str
    remaining_display: str
    overpaid_display: str

    # 'paid' | 'partial' | 'unpaid' | 'overpaid' — aggregated across ALL fees
    status: str


class FeeRecordDetail(BaseModel):
    """A single fee line inside the student-detail drawer."""
    fee_record_id: int
    fee_name: str
    fee_term: str
    total_fees_kobo: int
    amount_paid_kobo: int
    balance_kobo: int
    remaining_kobo: int
    overpaid_kobo: int
    total_fees_display: str
    amount_paid_display: str
    balance_display: str
    remaining_display: str
    overpaid_display: str
    status: str


class PaymentHistoryItem(BaseModel):
    """A single payment inside the student-detail drawer."""
    amount_kobo: int
    amount_display: str
    method: str
    recorded_by: str | None
    note: str | None
    paid_at: datetime


class MessageHistoryItem(BaseModel):
    """A reminder/confirmation line inside the student-detail drawer."""
    action: str
    description: str
    created_at: datetime


class StudentDetail(BaseModel):
    """Everything the drawer shows when you click a parent/student."""
    student_id: int
    student_name: str
    section: str
    class_name: str | None
    parent_name: str
    parent_phone: str
    parent_email: str | None

    total_fees_kobo: int
    amount_paid_kobo: int
    balance_kobo: int
    remaining_kobo: int
    overpaid_kobo: int
    total_fees_display: str
    amount_paid_display: str
    balance_display: str
    remaining_display: str
    overpaid_display: str
    status: str

    fee_records: list[FeeRecordDetail]
    payments: list[PaymentHistoryItem]
    messages: list[MessageHistoryItem]
