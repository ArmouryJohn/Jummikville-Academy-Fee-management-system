"""
Reminder endpoint — triggers fee reminders for a school's parents.

Currently triggered manually via API call. In the future, you could:
- Add a scheduled job (e.g., every Monday at 8am)
- Add a button in an admin dashboard
- Trigger from an n8n workflow
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import School
from app.services.reminder_service import send_reminders

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/reminders", tags=["Reminders"])


@router.post("/send")
async def trigger_reminders(
    school_id: int = Query(..., description="Which school to send reminders for"),
    section: str | None = Query(None, description="Filter by section (e.g. 'Primary')"),
    class_name: str | None = Query(None, description="Filter by class (e.g. 'Primary 3')"),
    fee_type_id: int | None = Query(None, description="Filter by specific fee type"),
    student_id: int | None = Query(None, description="Send to only this one student's parent"),
    include_payment_link: bool = Query(
        True, description="Whether to include a Paystack payment link in each reminder"
    ),
    db: Session = Depends(get_db),
):
    """
    Send fee reminders to all parents with outstanding balances.

    Sends WhatsApp messages to every parent whose balance > 0 at the
    specified school. Optionally filter by class, fee type, or a single student.

    Returns a summary of how many messages were sent, failed, or skipped.
    """
    # Verify the school exists
    school = db.query(School).filter(School.id == school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="School not found")

    results = await send_reminders(
        db=db,
        school_id=school_id,
        section=section,
        class_name=class_name,
        fee_type_id=fee_type_id,
        student_id=student_id,
        include_payment_link=include_payment_link,
    )

    return {
        "school": school.name,
        "results": results,
        "message": (
            f"Sent {results['sent']} reminders, "
            f"{results['failed']} failed, "
            f"{results['skipped']} skipped"
        ),
    }
