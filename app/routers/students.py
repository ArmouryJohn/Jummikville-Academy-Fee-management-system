"""
Student CRUD endpoints — create, list, get, update students.

These are straightforward REST endpoints for managing student records.
Phone numbers are automatically normalized to E.164 format (+234...) on creation.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Student, School, FeeRecord, Payment, ActivityLog
from app.schemas.student import StudentCreate, StudentUpdate, StudentResponse
from app.services.auth_deps import require_director
from app.utils.formatting import normalize_phone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/students", tags=["Students"])


@router.post("/", response_model=StudentResponse, status_code=201)
def create_student(
    data: StudentCreate,
    db: Session = Depends(get_db),
):
    """Create a new student record."""
    # Verify the school exists
    school = db.query(School).filter(School.id == data.school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="School not found")

    # Normalize the phone number to E.164 format
    normalized_phone = normalize_phone(data.parent_phone)

    student = Student(
        school_id=data.school_id,
        student_name=data.student_name,
        section=data.section,
        class_name=data.class_name,
        parent_name=data.parent_name,
        parent_phone=normalized_phone,
        parent_email=data.parent_email,
    )
    db.add(student)
    db.commit()
    db.refresh(student)

    logger.info(f"Student created: {student.student_name} (id={student.id})")
    return student


@router.get("/", response_model=list[StudentResponse])
def list_students(
    school_id: int = Query(..., description="Filter by school"),
    section: str | None = Query(None, description="Filter by section"),
    class_name: str | None = Query(None, description="Filter by class"),
    active_only: bool = Query(True, description="Only show active students"),
    db: Session = Depends(get_db),
):
    """List students, optionally filtered by school, section, class, or active status."""
    query = db.query(Student).filter(Student.school_id == school_id)

    if section:
        query = query.filter(Student.section == section)
    if class_name:
        query = query.filter(Student.class_name == class_name)
    if active_only:
        query = query.filter(Student.is_active == True)  # noqa: E712

    return query.order_by(Student.student_name).all()


@router.get("/{student_id}", response_model=StudentResponse)
def get_student(student_id: int, db: Session = Depends(get_db)):
    """Get a single student by ID."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


@router.patch("/{student_id}", response_model=StudentResponse)
def update_student(
    student_id: int,
    data: StudentUpdate,
    db: Session = Depends(get_db),
):
    """Update a student's information. Only provided fields are updated."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # Only update fields that were actually provided
    update_data = data.model_dump(exclude_unset=True)

    # Normalize phone if it's being updated
    if "parent_phone" in update_data:
        update_data["parent_phone"] = normalize_phone(update_data["parent_phone"])

    for field, value in update_data.items():
        setattr(student, field, value)

    db.commit()
    db.refresh(student)

    logger.info(f"Student updated: {student.student_name} (id={student.id})")
    return student


@router.delete("/{student_id}")
def delete_student(
    student_id: int,
    permanent: bool = False,
    db: Session = Depends(get_db),
    actor=Depends(require_director),
):
    """Deactivate or permanently delete a student record (Director only)."""
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    student_name = student.student_name
    parent_name = student.parent_name
    school_id = student.school_id

    if permanent:
        # 1. Clean up activity logs associated with this student
        db.query(ActivityLog).filter(ActivityLog.student_id == student_id).delete(synchronize_session=False)

        # 2. Delete payments belonging to the student's fee records explicitly
        fee_record_ids = [r.id for r in student.fee_records]
        if fee_record_ids:
            db.query(Payment).filter(Payment.fee_record_id.in_(fee_record_ids)).delete(synchronize_session=False)
            db.query(FeeRecord).filter(FeeRecord.id.in_(fee_record_ids)).delete(synchronize_session=False)

        # 3. Delete the student
        db.delete(student)

        # 4. Audit entry
        db.add(
            ActivityLog(
                school_id=school_id,
                student_id=None,
                action="student_deleted",
                description=f"Student record for '{student_name}' (Parent: {parent_name}) permanently deleted by Director {actor.email}",
            )
        )
        db.commit()
        logger.info(f"Student '{student_name}' (id={student_id}) permanently deleted by Director {actor.email}")
        return {"status": "ok", "message": f"Student '{student_name}' permanently deleted"}

    # Soft delete (deactivate)
    student.is_active = False
    db.add(
        ActivityLog(
            school_id=school_id,
            student_id=student.id,
            action="student_deactivated",
            description=f"Student record for '{student_name}' deactivated by Director {actor.email}",
        )
    )
    db.commit()
    logger.info(f"Student deactivated by Director {actor.email}: id={student_id}")
    return {"status": "ok", "message": f"Student '{student_name}' removed"}


@router.post("/reset-data")
def reset_student_data(
    db: Session = Depends(get_db),
    actor=Depends(require_director),
):
    """
    Clear all current student transactional data (students, fee records, payments, activity logs)
    so the system is fresh for real data entry.
    Keeps schools, fee categories, fee types, and user accounts intact.
    Director only.
    """
    p_count = db.query(Payment).delete(synchronize_session=False)
    fr_count = db.query(FeeRecord).delete(synchronize_session=False)
    s_count = db.query(Student).delete(synchronize_session=False)
    al_count = db.query(ActivityLog).delete(synchronize_session=False)
    db.commit()

    logger.info(f"Data reset by Director {actor.email}: {s_count} students, {fr_count} fee records, {p_count} payments, {al_count} logs cleared.")
    return {
        "status": "ok",
        "message": f"Cleared {s_count} students, {fr_count} fee records, and {p_count} payments. System is now fresh for new data.",
    }

