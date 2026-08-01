"""
Student CRUD endpoints — create, list, get, update students.

These are straightforward REST endpoints for managing student records.
Phone numbers are automatically normalized to E.164 format (+234...) on creation.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Student, School
from app.schemas.student import StudentCreate, StudentUpdate, StudentResponse
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
