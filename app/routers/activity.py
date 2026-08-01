"""
Activity feed endpoint — reads the ActivityLog for the frontend's live feed.

This is the read side of the activity system. The write side lives in
activity_service.log_activity(), called from the payment and reminder flows.
Together they power the "agent working in the background" feel:
    "Reminder sent to Mrs. Okon about Grace — balance ₦75,000.00"
    "Payment confirmed for Emmanuel Okon — ₦30,000.00 received via cash"
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ActivityLog
from app.schemas.activity import ActivityItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/activity", tags=["Activity"])


@router.get("/", response_model=list[ActivityItem])
def list_activity(
    school_id: int = Query(..., description="Which school's activity to show"),
    student_id: int | None = Query(None, description="Optional: only this student"),
    limit: int = Query(50, ge=1, le=200, description="How many entries to return"),
    db: Session = Depends(get_db),
):
    """
    Return recent activity, newest first. Powers both the dashboard's mini-feed
    and the full Activity screen.
    """
    query = db.query(ActivityLog).filter(ActivityLog.school_id == school_id)

    if student_id is not None:
        query = query.filter(ActivityLog.student_id == student_id)

    return (
        query.order_by(ActivityLog.created_at.desc())
        .limit(limit)
        .all()
    )
