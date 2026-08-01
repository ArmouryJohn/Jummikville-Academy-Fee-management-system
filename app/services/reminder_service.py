"""
Reminder service — finds parents who owe fees and sends them reminders.

DESIGN DECISIONS:
- Only sends to parents with balance > 0 (no point reminding someone who's paid)
- Only sends to active students (don't bother parents of withdrawn students)
- Can filter by class name or fee type (e.g., only remind JSS 2 parents)
- Returns a summary of how many messages were sent and any failures
- Generates a Paystack payment link for each parent so they can pay immediately
"""

import logging

from sqlalchemy.orm import Session, joinedload

from app.models import FeeRecord, Student
from app.services import twilio_wa
from app.services.activity_service import log_activity
from app.services.paystack import initialize_transaction, generate_reference
from app.utils.formatting import kobo_to_naira

logger = logging.getLogger(__name__)


async def send_reminders(
    db: Session,
    school_id: int,
    class_name: str | None = None,
    fee_type_id: int | None = None,
    student_id: int | None = None,
    include_payment_link: bool = True,
) -> dict:
    """
    Send fee reminders to all parents with outstanding balances.

    Args:
        db: Database session
        school_id: Which school's parents to remind
        class_name: Optional filter — only remind parents of this class
        fee_type_id: Optional filter — only remind about this specific fee
        student_id: Optional filter — only remind this ONE student's parent
        include_payment_link: Whether to generate a Paystack payment link

    Returns:
        Summary dict with counts of sent, failed, and skipped messages
    """
    # Build the query for unpaid/partially paid fee records
    query = (
        db.query(FeeRecord)
        .join(FeeRecord.student)
        .join(FeeRecord.fee_type)
        .options(
            joinedload(FeeRecord.student).joinedload(Student.school),
            joinedload(FeeRecord.fee_type),
        )
        .filter(
            Student.school_id == school_id,
            Student.is_active == True,  # noqa: E712 — SQLAlchemy requires == not 'is'
            FeeRecord.status.in_(["unpaid", "partial"]),
        )
    )

    # Apply optional filters
    if class_name:
        query = query.filter(Student.class_name == class_name)
    if fee_type_id:
        query = query.filter(FeeRecord.fee_type_id == fee_type_id)
    if student_id:
        query = query.filter(Student.id == student_id)

    fee_records = query.all()

    results = {"sent": 0, "failed": 0, "skipped": 0, "total": len(fee_records)}

    for record in fee_records:
        student = record.student
        fee_type = record.fee_type
        school = student.school
        balance = record.balance_kobo

        if balance <= 0:
            results["skipped"] += 1
            continue

        # Generate a payment link if requested
        payment_link = None
        if include_payment_link:
            try:
                reference = generate_reference(record.id)
                # Use parent email, or fallback to a placeholder
                email = student.parent_email or f"{student.id}@{school.slug}.sch"
                paystack_data = await initialize_transaction(
                    email=email,
                    amount_kobo=balance,
                    reference=reference,
                    metadata={
                        "student_name": student.student_name,
                        "parent_name": student.parent_name,
                        "fee_type": fee_type.name,
                        "fee_term": fee_type.term,
                    },
                )
                payment_link = paystack_data.get("authorization_url")
            except Exception as e:
                logger.error(
                    f"Failed to generate payment link for student {student.id}: {e}"
                )
                # Still send the reminder without a link

        # Send the WhatsApp reminder
        sid = twilio_wa.send_fee_reminder(
            parent_name=student.parent_name,
            student_name=student.student_name,
            parent_phone=student.parent_phone,
            fee_name=fee_type.name,
            fee_term=fee_type.term,
            balance_kobo=balance,
            payment_link=payment_link,
            school_name=school.name,
        )

        if sid:
            results["sent"] += 1
            logger.info(
                f"Reminder sent to {student.parent_name} ({student.parent_phone}) "
                f"for {fee_type.name}: balance={balance} kobo"
            )
            # Record it in the activity feed so staff can see the agent working
            log_activity(
                db=db,
                school_id=school.id,
                student_id=student.id,
                action="reminder_sent",
                description=(
                    f"Reminder sent to {student.parent_name} "
                    f"about {student.student_name} — "
                    f"balance {kobo_to_naira(balance)}"
                ),
            )
        else:
            results["failed"] += 1
            logger.warning(
                f"Reminder FAILED for {student.parent_name} ({student.parent_phone})"
            )

    logger.info(
        f"Reminder batch complete: {results['sent']} sent, "
        f"{results['failed']} failed, {results['skipped']} skipped "
        f"out of {results['total']} records"
    )

    # Persist all the activity-feed entries staged during this batch.
    db.commit()

    return results
