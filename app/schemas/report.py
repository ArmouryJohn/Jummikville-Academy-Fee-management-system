"""
Pydantic schemas for the Term Report export (Part B).

A term report is a term-scoped snapshot of how money moved: the headline totals,
paid/unpaid student counts, and breakdowns by fee category, by section/class, and
by payment method (online vs manual), plus a reminder-activity summary.

Following the same convention as schemas/dashboard.py, every money value is
returned twice: `*_kobo` (raw integer for maths) and `*_display` ("₦75,000.00"
ready-to-show string). The PDF renderer uses its own font-safe "NGN" formatting
(fpdf2 can't render ₦) — see app/services/report_pdf.py.
"""

from datetime import datetime, date

from pydantic import BaseModel


class ReportTotals(BaseModel):
    """The headline numbers for the whole term."""
    total_expected_kobo: int
    total_collected_kobo: int
    total_remaining_kobo: int   # still owed (never negative)
    total_overpaid_kobo: int    # credit owed back (never negative)

    total_expected_display: str
    total_collected_display: str
    total_remaining_display: str
    total_overpaid_display: str

    collection_rate: int        # 0–100

    # Student counts by rolled-up status across this term's fees.
    students_total: int
    students_paid: int
    students_partial: int
    students_unpaid: int
    students_overpaid: int
    students_no_fee: int


class CategoryLine(BaseModel):
    """Collection numbers for one fee category, scoped to the term."""
    category_name: str
    expected_kobo: int
    collected_kobo: int
    remaining_kobo: int
    expected_display: str
    collected_display: str
    remaining_display: str


class SectionLine(BaseModel):
    """Collection numbers for one school section, scoped to the term."""
    section: str
    students: int
    expected_kobo: int
    collected_kobo: int
    remaining_kobo: int
    expected_display: str
    collected_display: str
    remaining_display: str


class ClassLine(BaseModel):
    """Collection numbers for one class within a section, scoped to the term."""
    section: str
    class_name: str
    students: int
    expected_kobo: int
    collected_kobo: int
    remaining_kobo: int
    expected_display: str
    collected_display: str
    remaining_display: str


class MethodLine(BaseModel):
    """Count + amount of payments made with one method, scoped to the term."""
    method: str          # 'paystack' | 'cash' | 'pos' | 'bank_transfer' | 'other'
    label: str           # human label, e.g. 'Bank Transfer'
    count: int
    amount_kobo: int
    amount_display: str


class ChannelSplit(BaseModel):
    """Online (Paystack) vs manual (cash/pos/bank_transfer/other) roll-up."""
    online_count: int
    online_amount_kobo: int
    online_amount_display: str
    manual_count: int
    manual_amount_kobo: int
    manual_amount_display: str


class ReminderSummary(BaseModel):
    """How many fee reminders went out for this term."""
    reminders_sent: int
    # True when the count is scoped to the term's start/end window; False when the
    # term has no dates set, in which case the count is school-wide all-time.
    scoped_by_dates: bool
    note: str


class TermReportResponse(BaseModel):
    """The full term report — powers the on-screen preview, CSV and PDF exports."""
    school_id: int
    school_name: str

    term_id: int
    term_name: str
    term_start_date: date | None
    term_end_date: date | None
    is_current: bool

    generated_at: datetime

    totals: ReportTotals
    categories: list[CategoryLine]
    sections: list[SectionLine]
    classes: list[ClassLine]
    methods: list[MethodLine]
    channels: ChannelSplit
    reminders: ReminderSummary


class TermComparisonItem(BaseModel):
    """Headline metrics and breakdowns for one term in a side-by-side comparison (Part E)."""
    term_id: int
    term_name: str
    term_start_date: date | None
    term_end_date: date | None
    is_current: bool

    total_expected_kobo: int
    total_collected_kobo: int
    total_remaining_kobo: int
    total_overpaid_kobo: int
    total_expenses_kobo: int
    net_available_kobo: int
    collection_rate: int

    total_expected_display: str
    total_collected_display: str
    total_remaining_display: str
    total_overpaid_display: str
    total_expenses_display: str
    net_available_display: str

    students_total: int
    students_paid: int
    students_partial: int
    students_unpaid: int
    students_overpaid: int

    methods: list[MethodLine]
    channels: ChannelSplit


class TermComparisonResponse(BaseModel):
    """Side-by-side comparison of two academic terms (Part E)."""
    school_id: int
    school_name: str
    term1: TermComparisonItem
    term2: TermComparisonItem

