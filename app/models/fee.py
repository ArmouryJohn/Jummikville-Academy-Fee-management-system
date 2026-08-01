"""
Fee models — FeeType (catalog) and FeeRecord (what each student owes).

TWO TABLES, ONE CONCEPT:

FeeType = "Tuition for Term 1 2025 costs ₦75,000"
  → Defined once per school, shared across all students

FeeRecord = "Emmanuel Okon owes ₦75,000 for Tuition Term 1, has paid ₦50,000"
  → One per student per fee type, tracks individual progress

THE GOLDEN RULE:
balance = total_fees - amount_paid
This is ALWAYS computed, never stored or manually entered.
If amount_paid changes (via Paystack or cash), the balance updates automatically.
"""

from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, ForeignKey, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FeeType(Base):
    """
    A type of fee that a school charges.

    WHAT CHANGED FROM THE OLD DESIGN:
    Before: one FeeType = "Tuition - Term 1 2025"
    Now: one FeeType = "Tuition Fee (category) · Primary (section) · Term 1 · ₦75,000"

    The category_id links to the permanent FeeCategory (Tuition, Textbook, etc.),
    and the section (Nursery/Primary/Secondary) lets different sections have
    different amounts for the same category in the same term. This way:
    - We can sum all Tuition collected vs all Textbook collected (GROUP BY category)
    - We can see Primary's total vs Secondary's total (filter by section)
    - Staff can set ₦50k tuition for Nursery and ₦75k for Primary in one term
    """
    __tablename__ = "fee_types"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    school_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("schools.id"), nullable=False
    )

    # NEW: link to the permanent category (Tuition, Textbook, Lesson, etc.)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fee_categories.id"), nullable=False,
        comment="Which permanent fee category this type belongs to"
    )

    # NEW: which school section this fee type applies to
    section: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="'Nursery', 'Primary', or 'Secondary' — required so different sections can have different amounts"
    )

    term: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="e.g. 'Term 1 2025/2026'"
    )
    amount_kobo: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Default amount in kobo (₦75,000 = 7500000)"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # ---------- Relationships ----------
    school: Mapped["School"] = relationship(back_populates="fee_types")  # noqa: F821
    category: Mapped["FeeCategory"] = relationship(back_populates="fee_types")  # noqa: F821
    fee_records: Mapped[list["FeeRecord"]] = relationship(
        back_populates="fee_type"
    )

    # ---------- Computed Properties ----------
    @property
    def name(self) -> str:
        """
        The display name of this fee type = its category's name.

        Kept as a property (not a column) so there's one source of truth: the
        category. Existing code and messages that referenced `fee_type.name`
        (payment confirmations, reminders, dashboard) keep working unchanged.
        """
        return self.category.name if self.category else "Fee"

    def __repr__(self) -> str:
        return f"<FeeType(id={self.id}, category_id={self.category_id}, section='{self.section}', term='{self.term}')>"


class FeeRecord(Base):
    """
    Tracks what a specific student owes for a specific fee type.

    IMPORTANT: balance_kobo is a COMPUTED PROPERTY, not a database column.
    It's always: total_fees_kobo - amount_paid_kobo
    This means it can never be "wrong" — it's mathematically derived.
    """
    __tablename__ = "fee_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    student_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("students.id"), nullable=False
    )
    fee_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fee_types.id"), nullable=False
    )

    # What they owe and what they've paid
    total_fees_kobo: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Total amount owed in kobo"
    )
    amount_paid_kobo: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Total amount paid so far in kobo"
    )

    # Status is derived from amounts, but stored for easy querying
    # (it's much faster to query WHERE status='unpaid' than to compute)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unpaid",
        comment="'unpaid', 'partial', 'paid', or 'overpaid'"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # ---------- Relationships ----------
    student: Mapped["Student"] = relationship(back_populates="fee_records")  # noqa: F821
    fee_type: Mapped["FeeType"] = relationship(back_populates="fee_records")
    payments: Mapped[list["Payment"]] = relationship(  # noqa: F821
        back_populates="fee_record", cascade="all, delete-orphan"
    )

    # ---------- Computed Properties ----------
    @property
    def balance_kobo(self) -> int:
        """
        The remaining balance. ALWAYS computed, never stored.
        balance = total_fees - amount_paid

        Can be negative when a parent has overpaid — callers use
        `overpaid_kobo` / `remaining_kobo` below for the clean split.
        """
        return self.total_fees_kobo - self.amount_paid_kobo

    @property
    def remaining_kobo(self) -> int:
        """How much is still owed to COMPLETE the fee (never negative)."""
        return max(0, self.total_fees_kobo - self.amount_paid_kobo)

    @property
    def overpaid_kobo(self) -> int:
        """How much was paid OVER the fee — a credit owed back (never negative)."""
        return max(0, self.amount_paid_kobo - self.total_fees_kobo)

    def recalculate_status(self) -> None:
        """
        Update the status field based on current amounts.
        Call this after any payment is recorded.
        """
        self.status = _status_for(self.amount_paid_kobo, self.total_fees_kobo)

    def __repr__(self) -> str:
        return (
            f"<FeeRecord(id={self.id}, student_id={self.student_id}, "
            f"total={self.total_fees_kobo}, paid={self.amount_paid_kobo}, "
            f"balance={self.balance_kobo}, status='{self.status}')>"
        )


# --------------------------------------------------------------------------
# Shared status logic — one source of truth for both recalculate_status()
# and the event listener below, so they can never disagree.
# --------------------------------------------------------------------------
def _status_for(amount_paid_kobo: int, total_fees_kobo: int) -> str:
    """Derive the status string from the paid vs total amounts."""
    if amount_paid_kobo <= 0:
        return "unpaid"
    if amount_paid_kobo > total_fees_kobo:
        return "overpaid"
    if amount_paid_kobo == total_fees_kobo:
        return "paid"
    return "partial"


# --------------------------------------------------------------------------
# Auto-recalculate status whenever amount_paid changes
# --------------------------------------------------------------------------
# This is a SQLAlchemy event listener. Whenever amount_paid_kobo is modified
# on a FeeRecord, the status is automatically recalculated. This means you
# can NEVER forget to update the status — it happens automatically.
#
# IMPORTANT: Do NOT re-set target.amount_paid_kobo inside this listener —
# that would trigger the listener again and cause infinite recursion.
# Instead, compute status directly from the incoming `value`.
@event.listens_for(FeeRecord.amount_paid_kobo, "set")
def _auto_recalculate_status(target: FeeRecord, value: int, oldvalue: int, initiator):
    """Auto-update status when amount_paid_kobo changes."""
    if value != oldvalue:
        # Compute status from the NEW value (which SQLAlchemy is about to set).
        # total_fees_kobo may be None during initial object construction; guard it.
        total = target.total_fees_kobo or 0
        target.status = _status_for(value, total)
