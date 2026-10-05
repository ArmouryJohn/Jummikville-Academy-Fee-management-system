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
    section: str  # 'Preschool' | 'Primary' | 'Smart Skills High School' | 'All'

    total_students: int

    total_expected_kobo: int
    total_collected_kobo: int
    total_remaining_kobo: int  # what's still owed to complete (never negative)
    total_overpaid_kobo: int  # credit owed back to parents (never negative)

    total_expected_display: str
    total_collected_display: str
    total_remaining_display: str
    total_overpaid_display: str


class ClassSummary(BaseModel):
    """
    The headline numbers for a single class within a section.

    Returned by GET /api/v1/dashboard/classes?school_id=1&section=Primary
    so the frontend can render the class-tab list without calling the full
    dashboard/summary endpoint once per class.
    """
    section: str        # Parent section name
    class_name: str     # e.g. 'Primary 3'

    total_students: int

    total_expected_kobo: int
    total_collected_kobo: int
    total_remaining_kobo: int
    total_overpaid_kobo: int

    total_expected_display: str
    total_collected_display: str
    total_remaining_display: str
    total_overpaid_display: str

    # How many students fall into each payment bucket (for mini badges)
    students_paid: int
    students_partial: int
    students_unpaid: int
    students_overpaid: int
    students_no_fee: int


class DashboardInsights(BaseModel):
    """Aggregated insights for the dashboard overview."""
    top_unpaid_class: str | None = None
    top_unpaid_class_remaining_kobo: int = 0
    top_unpaid_class_remaining_display: str = "₦0.00"

    most_common_payment_method: str | None = None

    biggest_expense_category: str | None = None
    biggest_expense_category_kobo: int = 0
    biggest_expense_category_display: str = "₦0.00"

    collection_by_section: dict[str, int] = {}


class DashboardSummary(BaseModel):
    """
    Top-of-dashboard numbers and the paid/unpaid breakdown for the chart.

    Returns whole-school figures plus a per-section list, so the frontend can
    switch between sections without extra round-trips.
    """
    school_id: int
    school_name: str

    total_students: int

    # Whole-school headline numbers
    total_expected_kobo: int
    total_collected_kobo: int
    total_remaining_kobo: int
    total_overpaid_kobo: int

    total_expected_display: str
    total_collected_display: str
    total_remaining_display: str
    total_overpaid_display: str

    # Net funds: collections vs expenses
    total_expenses_kobo: int = 0
    net_available_kobo: int = 0  # total_collected_kobo - total_expenses_kobo
    total_expenses_display: str = "₦0.00"
    net_available_display: str = "₦0.00"

    collection_rate: int

    students_paid: int
    students_partial: int
    students_unpaid: int
    students_overpaid: int = 0
    students_no_fee: int = 0

    sections: list[SectionSummary] = []
    categories: list[CategoryBreakdown] = []
    insights: DashboardInsights | None = None



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
    id: int
    amount_kobo: int
    amount_display: str
    method: str
    recorded_by: str | None
    note: str | None
    paid_at: datetime
    receipt_url: str | None = None


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
