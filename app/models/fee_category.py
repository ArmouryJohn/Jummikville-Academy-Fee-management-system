"""FeeCategory model for grouping fee types (e.g. Tuition, Textbooks, Uniforms)."""

from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FeeCategory(Base):
    __tablename__ = "fee_categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    school_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("schools.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(
        String(100), nullable=False,
        comment="e.g. 'Tuition Fee', 'Textbook Fee', 'Lesson Fee'"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # ---------- Relationships ----------
    school: Mapped["School"] = relationship(back_populates="fee_categories")  # noqa: F821
    fee_types: Mapped[list["FeeType"]] = relationship(  # noqa: F821
        back_populates="category"
    )

    def __repr__(self) -> str:
        return f"<FeeCategory(id={self.id}, name='{self.name}')>"
