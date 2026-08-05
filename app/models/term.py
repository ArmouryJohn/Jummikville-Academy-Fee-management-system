"""
Term model — a real academic term (e.g. "First Term 2025/2026").

WHY THIS EXISTS:
A term used to be a free-text string living on every FeeType. That meant a typo
("First Term 2025/26" vs "First Term 2025/2026") silently split one term's money
into two buckets, and there was no place to store term dates or mark which term
is "current". Every report, expense, and payroll record needs ONE trustworthy
term to key off, so a term is now a first-class row.

HOW IT RELATES TO FeeType:
FeeType.term_id points here. FeeType.term is a read-only property that returns
this term's name, so all existing code that reads `fee_type.term` (reminders,
receipts, dashboard) keeps working unchanged.

THE "CURRENT TERM" RULE:
Exactly one term per school has is_current=True. It's toggled manually by an
admin (POST /api/v1/terms/{id}/set-current), which clears the flag on every
other term in the same school in the same transaction — never automatic by date.
"""

from datetime import datetime, timezone, date

from sqlalchemy import String, DateTime, Date, Boolean, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Term(Base):
    __tablename__ = "terms"
    __table_args__ = (
        # A term name is unique WITHIN a school, so "First Term 2025/2026" can't
        # be created twice and split a term's money in two.
        UniqueConstraint("school_id", "name", name="uq_term_school_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    school_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("schools.id"), nullable=False
    )

    name: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="e.g. 'First Term 2025/2026' — unique per school"
    )

    start_date: Mapped[date | None] = mapped_column(
        Date, nullable=True,
        comment="Optional term start date"
    )
    end_date: Mapped[date | None] = mapped_column(
        Date, nullable=True,
        comment="Optional term end date"
    )

    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="Exactly one term per school is current; toggled manually by an admin"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # ---------- Relationships ----------
    school: Mapped["School"] = relationship(back_populates="terms")  # noqa: F821
    fee_types: Mapped[list["FeeType"]] = relationship(  # noqa: F821
        back_populates="term_obj"
    )

    def __repr__(self) -> str:
        return f"<Term(id={self.id}, name='{self.name}', is_current={self.is_current})>"
