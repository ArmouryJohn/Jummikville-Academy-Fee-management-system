"""
Staff model — represents a staff member at Jummikville Academy.

FIELDS:
- full_name, role_title (e.g. Teacher, Bus Driver, Administrator)
- phone_number, email
- bank_name, account_number, account_name (bank details for Director view)
- classes_taught (JSON list of assigned classes, e.g. ["Primary 1", "Primary 3"])
- is_active (boolean, default True; soft delete preserves historical payroll records)
- created_at, updated_at
"""

from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Boolean, Integer, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Staff(Base):
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    school_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("schools.id"), nullable=False
    )

    full_name: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="Staff member full name"
    )

    role_title: Mapped[str] = mapped_column(
        String(50), nullable=False, default="Teacher",
        comment="Staff title/role, e.g. 'Teacher', 'Bus Driver', 'Administrator'"
    )

    phone_number: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="Normalized phone number"
    )

    email: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        comment="Optional email address"
    )

    # Bank Details
    bank_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="Bank name (e.g. Access Bank, GTBank, First Bank)"
    )

    account_number: Mapped[str | None] = mapped_column(
        String(20), nullable=True,
        comment="NUBAN 10-digit account number"
    )

    account_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="Account holder name as registered with bank"
    )

    # Classes Taught (JSON list of class strings, e.g. ["Primary 1", "Primary 4"])
    classes_taught: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list,
        comment="List of classes assigned to this staff member"
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        comment="Soft delete status — inactive staff preserve payroll history"
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
    payroll_records: Mapped[list["StaffPayrollRecord"]] = relationship(  # noqa: F821
        back_populates="staff", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Staff(id={self.id}, name='{self.full_name}', role='{self.role_title}')>"
