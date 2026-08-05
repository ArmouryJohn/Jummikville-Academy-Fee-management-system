"""
School model — represents a school in the system.

WHY MULTI-TENANT FROM DAY ONE:
Even though we're starting with just Jummikville Academy, storing the school
as a database record (not hardcoded) means adding another school later is
just an INSERT, not a code change. Every student, fee, and payment links
back to a school_id, so data is always isolated per school.
"""

from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class School(Base):
    __tablename__ = "schools"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # School identity
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False,
        comment="URL-friendly identifier, e.g. 'jummikville'"
    )
    phone: Mapped[str | None] = mapped_column(
        String(120),
        comment="One or more contact numbers (comma-separated); shown on receipts"
    )
    email: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(500))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # ---------- Relationships ----------
    # These let you do: school.students, school.fee_types
    students: Mapped[list["Student"]] = relationship(  # noqa: F821
        back_populates="school", cascade="all, delete-orphan"
    )
    fee_types: Mapped[list["FeeType"]] = relationship(  # noqa: F821
        back_populates="school", cascade="all, delete-orphan"
    )
    terms: Mapped[list["Term"]] = relationship(  # noqa: F821
        back_populates="school", cascade="all, delete-orphan"
    )
    fee_categories: Mapped[list["FeeCategory"]] = relationship(  # noqa: F821
        back_populates="school", cascade="all, delete-orphan"
    )
    users: Mapped[list["User"]] = relationship(  # noqa: F821
        back_populates="school", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<School(id={self.id}, name='{self.name}', slug='{self.slug}')>"
