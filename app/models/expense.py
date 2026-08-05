"""
Expense model — money the school spends (money going OUT).

WHY THIS EXISTS:
The system tracks money coming IN (fees/payments) in fine detail, but until now
had no record of money going OUT — textbooks bought, a generator repaired, fuel,
"Nepa Light" (electricity), events. Without that, a director can see what was
collected but not what's actually left after running costs. An Expense row is one
outgoing spend, by category, with who recorded it and when (the audit trail).

LOAD-BEARING RULES:
- amount_kobo is a REAL stored integer column (unlike FeeRecord.amount_paid_kobo,
  which is a derived property). So expenses may be summed in SQL (func.sum) — see
  expense_service.total_expenses_kobo.
- Expenses NEVER touch student fee balances. They reduce the school's cash
  position (Net Available = Collected − Expenses on the dashboard), nothing else.
- term_id is nullable and defaulted to the current term at create time, so a term
  can later compare its own expenses (Part E) while old rows without a term still
  count toward the all-time total.
- created_by_user_id mirrors Payment.recorded_by_user_id — the audit actor,
  stamped from the authenticated admin. Nullable so a system/import row is allowed.
"""

from datetime import datetime, timezone, date

from sqlalchemy import String, DateTime, Date, Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    school_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("schools.id"), nullable=False
    )

    # Optional term this spend belongs to (defaulted to the current term at create
    # time). Nullable so an expense can exist before any term is marked current.
    term_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("terms.id"), nullable=True
    )

    category: Mapped[str] = mapped_column(
        String(40), nullable=False,
        comment="One of EXPENSE_CATEGORIES (Textbooks, Repairs, Fuel, ...)"
    )

    amount_kobo: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Amount spent in kobo. ₦15,000 = 1500000"
    )

    purpose: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="What the money was spent on, e.g. 'Generator repair'"
    )

    expense_date: Mapped[date] = mapped_column(
        Date, nullable=False,
        default=lambda: datetime.now(timezone.utc).date(),
        comment="The date the spend happened (defaults to today)"
    )

    note: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Optional free-text note"
    )

    # A free-text reference to a paper receipt / vendor slip (NOT a file upload).
    receipt_ref: Mapped[str | None] = mapped_column(
        String(120), nullable=True,
        comment="Optional vendor slip / receipt reference number"
    )

    # The authenticated admin who recorded this expense — the AUDIT ACTOR.
    # Mirrors Payment.recorded_by_user_id. Nullable for system/import rows.
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True,
        comment="id of the admin who recorded this expense (audit trail)"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # ---------- Relationships ----------
    school: Mapped["School"] = relationship()  # noqa: F821
    term: Mapped["Term | None"] = relationship()  # noqa: F821
    created_by_user: Mapped["User | None"] = relationship()  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<Expense(id={self.id}, category='{self.category}', "
            f"amount={self.amount_kobo}, purpose='{self.purpose}')>"
        )
