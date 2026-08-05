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

from sqlalchemy import String, DateTime, Integer, ForeignKey
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
        String(50), nullable=False,
        comment="'Preschool', 'Primary', or 'Smart Skills High School' — required so different sections can have different amounts"
    )

    # The term is now a real Term row. The legacy free-text `term` column has been
    # dropped (see migrate_terms.py) — its value was backfilled into Term rows and
    # this FK is the single source of truth. Nullable so ADD COLUMN works on the
    # existing table before the backfill links each row.
    term_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("terms.id"), nullable=True,
        comment="Which Term this fee type belongs to (source of truth)"
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
    term_obj: Mapped["Term"] = relationship(back_populates="fee_types")  # noqa: F821
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

    @property
    def term(self) -> str:
        """
        The term NAME as a string — reads through to the linked Term row.

        Kept as a property (not a column) so there's one source of truth: the
        Term. Every existing caller that reads `fee_type.term` (reminders,
        receipts, dashboard) keeps working unchanged. Empty string if a row is
        somehow unlinked (should not happen after the backfill migration).
        """
        return self.term_obj.name if self.term_obj is not None else ""

    def __repr__(self) -> str:
        return f"<FeeType(id={self.id}, category_id={self.category_id}, section='{self.section}', term='{self.term}')>"


class FeeRecord(Base):
    """
    Tracks what a specific student owes for a specific fee type.

    IMPORTANT: both amount_paid_kobo AND balance_kobo are COMPUTED PROPERTIES,
    not database columns. amount_paid_kobo is the sum of this record's confirmed
    Payment rows; balance_kobo is total_fees_kobo - amount_paid_kobo. This means
    they can never be "wrong" — they're mathematically derived from the payments.
    """
    __tablename__ = "fee_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    student_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("students.id"), nullable=False
    )
    fee_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fee_types.id"), nullable=False
    )

    # What they owe. What they've PAID is NOT stored — it's computed from the
    # Payment rows (see the amount_paid_kobo property below). Storing it as a
    # column would be a cached aggregate that can silently drift from the actual
    # payments; deriving it means the balance can never be "wrong".
    total_fees_kobo: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Total amount owed in kobo"
    )

    # Status is derived from amounts, but stored for easy querying
    # (it's much faster to query WHERE status='unpaid' than to compute).
    # It's a denormalised index with a single writer (recalculate_status,
    # called by the payment pipeline) — never a source of truth.
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
    def amount_paid_kobo(self) -> int:
        """
        Total confirmed money paid against this record — the SUM of its Payment
        rows, ALWAYS computed, never stored.

        "Confirmed" is the definition of a Payment row: we only ever insert a
        Payment when money has actually been received (cash/POS/transfer recorded
        by staff, or a signature-verified Paystack webhook). There is no "pending"
        payment state, so summing every Payment row gives the true paid amount.
        """
        return sum(p.amount_kobo for p in self.payments)

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
