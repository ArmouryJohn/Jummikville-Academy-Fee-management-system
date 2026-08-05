"""
Staff Payroll Models — term salary schedules and payout transactions.

MODELS:
1. StaffPayrollRecord — scheduled salary per staff member per term.
2. StaffPayment — individual payout transactions (installments or full payments).
"""

from datetime import datetime, timezone, date

from sqlalchemy import String, DateTime, Date, Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StaffPayrollRecord(Base):
    """
    Term salary schedule for one staff member.
    """
    __tablename__ = "staff_payroll_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    school_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("schools.id"), nullable=False
    )

    staff_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("staff.id"), nullable=False
    )

    term_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("terms.id"), nullable=False
    )

    amount_scheduled_kobo: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="Total salary scheduled to be paid for this term in kobo"
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unpaid",
        comment="'unpaid' | 'partial' | 'paid'"
    )

    note: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )

    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True,
        comment="id of Director who set up this payroll schedule"
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
    school: Mapped["School"] = relationship()  # noqa: F821
    staff: Mapped["Staff"] = relationship(back_populates="payroll_records")  # noqa: F821
    term: Mapped["Term"] = relationship()  # noqa: F821
    created_by_user: Mapped["User | None"] = relationship()  # noqa: F821
    payouts: Mapped[list["StaffPayment"]] = relationship(
        back_populates="payroll_record", cascade="all, delete-orphan"
    )

    @property
    def amount_paid_kobo(self) -> int:
        """Derived sum of payouts."""
        return sum(p.amount_kobo for p in self.payouts)

    @property
    def remaining_kobo(self) -> int:
        """Derived remaining unpaid salary balance."""
        return max(0, self.amount_scheduled_kobo - self.amount_paid_kobo)

    def recalculate_status(self) -> None:
        """Recalculate status based on payments."""
        paid = self.amount_paid_kobo
        sched = self.amount_scheduled_kobo
        if sched <= 0:
            self.status = "paid" if paid >= 0 else "unpaid"
        elif paid <= 0:
            self.status = "unpaid"
        elif paid >= sched:
            self.status = "paid"
        else:
            self.status = "partial"


class StaffPayment(Base):
    """
    Payout transaction for a staff payroll record.
    """
    __tablename__ = "staff_payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    payroll_record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("staff_payroll_records.id"), nullable=False
    )

    amount_kobo: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Amount paid out in kobo"
    )

    payment_date: Mapped[date] = mapped_column(
        Date, nullable=False,
        default=lambda: datetime.now(timezone.utc).date(),
        comment="Date salary payout was made"
    )

    method: Mapped[str] = mapped_column(
        String(30), nullable=False, default="bank_transfer",
        comment="'bank_transfer' | 'cash' | 'check'"
    )

    note: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )

    processed_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True,
        comment="Director who processed this payment"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # ---------- Relationships ----------
    payroll_record: Mapped["StaffPayrollRecord"] = relationship(back_populates="payouts")
    processed_by_user: Mapped["User | None"] = relationship()  # noqa: F821
