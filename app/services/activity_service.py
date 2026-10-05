"""
Activity logging service for recording system actions and audit feed items.
"""

import logging

from sqlalchemy.orm import Session

from app.models import ActivityLog

logger = logging.getLogger(__name__)


def log_activity(
    db: Session,
    school_id: int,
    action: str,
    description: str,
    student_id: int | None = None,
    commit: bool = False,
) -> ActivityLog:
    """
    Record an entry in the activity feed.

    Args:
        db: Database session
        school_id: Which school this activity belongs to
        action: A short machine key, e.g. 'payment_recorded', 'reminder_sent'
        description: Human-readable line shown in the feed
        student_id: Optional link to the student involved
        commit: If True, commit immediately. Usually left False so the caller
                commits it in the same transaction as the underlying action.

    Returns:
        The created ActivityLog (staged, and committed if commit=True)
    """
    entry = ActivityLog(
        school_id=school_id,
        student_id=student_id,
        action=action,
        description=description,
    )
    db.add(entry)

    if commit:
        db.commit()
        db.refresh(entry)

    logger.info(f"Activity logged: [{action}] {description}")
    return entry
