"""Academic term model (e.g. First Term 2025/2026)."""

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
