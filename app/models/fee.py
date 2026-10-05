"""Models for fee structures (FeeType) and student fee assignments (FeeRecord)."""

from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FeeType(Base):
    """Fee type definition with category, section, term, and default amount."""
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

    term_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("terms.id"), nullable=True,
        comment="Academic term id"
    )
    amount_kobo: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Default amount in kobo"
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
        """Display name of fee type from category."""
        return self.category.name if self.category else "Fee"

    @property
    def term(self) -> str:
        """Term name from linked Term record."""
        return self.term_obj.name if self.term_obj is not None else ""

    def __repr__(self) -> str:
        return f"<FeeType(id={self.id}, category_id={self.category_id}, section='{self.section}', term='{self.term}')>"


class FeeRecord(Base):
    """Tracks what a student owes for a fee type, with derived paid amounts."""
    __tablename__ = "fee_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    student_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("students.id"), nullable=False
    )
    fee_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fee_types.id"), nullable=False
    )

    total_fees_kobo: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Total amount owed in kobo"
    )

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
