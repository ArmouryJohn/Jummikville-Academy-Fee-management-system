"""
User model — represents a staff member who can log into the dashboard.

DESIGN DECISIONS:
- Passwords are hashed with PBKDF2-SHA256 (200k iterations, per-password salt).
  Never stored in plain text.
- role field allows multiple roles in the future ('admin', 'bursar', 'staff'),
  but for now only 'admin' is seeded.
- school_id links the user to a school (multi-tenant ready — each user sees
  only their school's data).
- is_active lets you disable an account without deleting it.
"""

from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Boolean, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Link to school (a user belongs to one school)
    school_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("schools.id"), nullable=False
    )

    # User identity
    email: Mapped[str] = mapped_column(
        String(200), unique=True, nullable=False,
        comment="Email address — used for login"
    )
    hashed_password: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="PBKDF2-SHA256 hash — NEVER the plain password"
    )

    # Role/permissions
    role: Mapped[str] = mapped_column(
        String(50), nullable=False, default="admin",
        comment="'admin' (full access) — expandable later to 'bursar', 'staff'"
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ---------- Relationships ----------
    school: Mapped["School"] = relationship(back_populates="users")  # noqa: F821

    @property
    def is_director(self) -> bool:
        """True if user has Director level privileges ('director' or legacy 'admin')."""
        return self.role in ("director", "admin")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}', role='{self.role}')>"
