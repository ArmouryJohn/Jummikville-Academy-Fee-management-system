"""
Activity service — records actions into the ActivityLog for the frontend feed.

WHY THIS EXISTS:
The frontend has an "activity feed" that makes the system feel like a live agent
working in the background ("Reminder sent to Mrs. Okon", "Payment confirmed for
Emmanuel — ₦30,000 received"). Those lines have to come from somewhere.

Rather than sprinkle `db.add(ActivityLog(...))` across the codebase, every place
that does something worth showing calls ONE function: log_activity(). This keeps
the wording consistent and means there's a single place to change how activity
is recorded.

TRANSACTION NOTE:
This function only stages the log (db.add) — it does NOT commit by default. The
caller commits it together with whatever it was already doing (e.g. recording a
payment), so the activity entry and the real action succeed or fail as one unit.
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
