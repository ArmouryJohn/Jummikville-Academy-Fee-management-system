"""
Activity log model — stores a history of actions for the frontend feed.
"""

from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ActivityLog(Base):
    """
    Records an automated or manual action for the activity feed.
    """
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    school_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("schools.id"), nullable=False
    )
    
    # Optional link to a specific student
    student_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("students.id"), nullable=True
    )
    
    action: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="'payment_recorded', 'reminder_sent', etc."
    )
    
    description: Mapped[str] = mapped_column(
        String(500), nullable=False,
        comment="Human readable text: 'Payment confirmed for Emmanuel Okon, ₦30,000 received'"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    school: Mapped["School"] = relationship()  # noqa: F821
    student: Mapped["Student"] = relationship()  # noqa: F821

    def __repr__(self) -> str:
        return f"<ActivityLog(id={self.id}, action='{self.action}', desc='{self.description}')>"
