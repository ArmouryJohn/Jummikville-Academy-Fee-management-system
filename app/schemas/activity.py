"""
Pydantic schema for activity-feed responses.
"""

from datetime import datetime

from pydantic import BaseModel


class ActivityItem(BaseModel):
    """A single line in the activity feed."""
    id: int
    action: str          # 'payment_recorded', 'reminder_sent', ...
    description: str      # human-readable line shown in the feed
    student_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
