"""
Payroll model — staff salary payment records (Director-only).

WHY THIS EXISTS:
Directors record staff salary payments per term. Staff members have NO login account
to the system — they only receive an outbound WhatsApp notification and downloadable
PDF payslip sent to their phone when paid.

AUDITABILITY:
Every payroll record stores `processed_by_user_id` pointing to the Director user who
recorded the payment.
"""

from datetime import datetime, timezone, date

from sqlalchemy import String, DateTime, Date, Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Payroll(Base):
    __tablename__ = "payroll"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    school_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("schools.id"), nullable=False
    )

    term_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("terms.id"), nullable=True,
        comment="Academic term this salary payment is for"
    )

    staff_name: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="Full name of staff member"
    )

    phone_number: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="Staff phone number (for WhatsApp notification)"
    )

    amount_kobo: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Salary amount paid in kobo (₦100,000 = 10000000)"
    )

    payment_date: Mapped[date] = mapped_column(
        Date, nullable=False,
        default=lambda: datetime.now(timezone.utc).date(),
        comment="Date salary was paid"
    )

    note: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Optional note / memo"
    )

    # The Director account that processed this payroll payment (Audit Trail)
    processed_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True,
        comment="id of the Director who processed this payment"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # ---------- Relationships ----------
    school: Mapped["School"] = relationship()  # noqa: F821
    term: Mapped["Term | None"] = relationship()  # noqa: F821
    processed_by_user: Mapped["User | None"] = relationship()  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<Payroll(id={self.id}, staff='{self.staff_name}', "
            f"amount={self.amount_kobo}, date={self.payment_date})>"
        )
