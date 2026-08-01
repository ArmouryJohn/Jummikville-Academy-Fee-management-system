"""
FeeCategory model — the permanent, school-wide list of fee kinds.

WHY A SEPARATE TABLE (not a string on FeeType):
The school wants to know, across everything, "how much have we collected for
Textbooks vs Tuition?" That only works if a category is a real row every fee
type points at — then we can GROUP BY category and sum. Storing the category
as free text on each fee type would let "Textbook", "Textbooks", and "Text book"
drift apart and break the totals.

RELATIONSHIP CHAIN:
    FeeCategory  (Tuition Fee)
      └─ FeeType     (Tuition Fee · Primary · Term 1 · ₦75,000)
           └─ FeeRecord  (Ada owes ₦75,000 for it, has paid ₦50,000)
                └─ Payment (₦50,000 received via cash)

Eight categories are seeded on startup (see app.main), but staff can add more
from the Setup screen without any code change — that's the whole point of this
being data, not an enum.
"""

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
