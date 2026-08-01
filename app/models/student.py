"""
Student model — represents a student and their parent/guardian contact info.

DESIGN DECISIONS:
- We store the PARENT's contact info on the student record because they're
  the ones who receive messages and make payments.
- parent_email is needed for Paystack (they require an email to initialize
  a transaction). If a parent doesn't have email, we can use a placeholder
  like parentname@jummikville.sch (Paystack doesn't verify the email).
- parent_phone is stored in E.164 format (+234...) for Twilio compatibility.
"""

from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Boolean, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Link to school (multi-tenant)
    school_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("schools.id"), nullable=False
    )

    # Student info
    student_name: Mapped[str] = mapped_column(String(200), nullable=False)
    section: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="'Nursery', 'Primary', or 'Secondary' — required; drives per-section dashboard stats"
    )
    class_name: Mapped[str | None] = mapped_column(
        String(50),
        comment="e.g. 'JSS 2', 'SS 1', 'Primary 4'"
    )

    # Parent/guardian contact info
    parent_name: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_phone: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="E.164 format: +234XXXXXXXXXX"
    )
    parent_email: Mapped[str | None] = mapped_column(
        String(200),
        comment="Needed for Paystack transactions"
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # ---------- Relationships ----------
    school: Mapped["School"] = relationship(back_populates="students")  # noqa: F821
    fee_records: Mapped[list["FeeRecord"]] = relationship(  # noqa: F821
        back_populates="student", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Student(id={self.id}, name='{self.student_name}', "
            f"parent='{self.parent_name}')>"
        )
