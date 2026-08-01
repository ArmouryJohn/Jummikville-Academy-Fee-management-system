"""
Fee management endpoints — create fee types and assign fees to students.

WORKFLOW:
1. Admin creates a FeeType: "Tuition — Term 1 2025/2026" at ₦75,000
2. Admin assigns it to students (individually or in bulk)
3. Each assignment creates a FeeRecord tracking that student's payment progress
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import FeeType, FeeRecord, Student, School, FeeCategory
from app.schemas.fee import (
    FeeCategoryCreate,
    FeeCategoryResponse,
    FeeTypeCreate,
    FeeTypeResponse,
    FeeRecordCreate,
    FeeRecordResponse,
    BulkFeeAssign,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/fees", tags=["Fees"])


# --------------------------------------------------------------------------
# Fee Category endpoints (the permanent, staff-managed master list)
# --------------------------------------------------------------------------

@router.post("/categories", response_model=FeeCategoryResponse, status_code=201)
def create_fee_category(
    data: FeeCategoryCreate,
    db: Session = Depends(get_db),
):
    """
    Add a new fee category (e.g. "Uniform Fee").

    Categories are the permanent master list every fee type hangs off. Eight are
    seeded at startup; staff can add more here without a code change.
    """
    school = db.query(School).filter(School.id == data.school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="School not found")

    name = data.name.strip()

    # No duplicate names within a school (case-insensitive).
    existing = (
        db.query(FeeCategory)
        .filter(
            FeeCategory.school_id == data.school_id,
            FeeCategory.name.ilike(name),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"A category named '{name}' already exists",
        )

    category = FeeCategory(school_id=data.school_id, name=name)
    db.add(category)
    db.commit()
    db.refresh(category)

    logger.info(f"Fee category created: {category.name}")
    return category


@router.get("/categories", response_model=list[FeeCategoryResponse])
def list_fee_categories(
    school_id: int = Query(..., description="Filter by school"),
    db: Session = Depends(get_db),
):
    """List all fee categories for a school."""
    return (
        db.query(FeeCategory)
        .filter(FeeCategory.school_id == school_id)
        .order_by(FeeCategory.name)
        .all()
    )


@router.delete("/categories/{category_id}", status_code=200)
def delete_fee_category(category_id: int, db: Session = Depends(get_db)):
    """
    Delete a fee category — only if no fee types still reference it, so we never
    orphan a fee type whose display name reads through to the category.
    """
    category = db.query(FeeCategory).filter(FeeCategory.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    in_use = (
        db.query(FeeType).filter(FeeType.category_id == category_id).count()
    )
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Can't delete '{category.name}' — {in_use} fee type(s) use it. "
                "Remove those fee types first."
            ),
        )

    db.delete(category)
    db.commit()
    logger.info(f"Fee category deleted: {category.name}")
    return {"deleted": True, "id": category_id}


# --------------------------------------------------------------------------
# Fee Type endpoints (the catalog)
# --------------------------------------------------------------------------

@router.post("/types", response_model=FeeTypeResponse, status_code=201)
def create_fee_type(
    data: FeeTypeCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new fee type: a category + section + term + amount, e.g.
    "Tuition Fee · Primary · Term 1 2025/2026 · ₦75,000".

    Fee types define WHAT a school charges. They're shared across students.
    """
    school = db.query(School).filter(School.id == data.school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="School not found")

    category = (
        db.query(FeeCategory)
        .filter(
            FeeCategory.id == data.category_id,
            FeeCategory.school_id == data.school_id,
        )
        .first()
    )
    if not category:
        raise HTTPException(status_code=404, detail="Fee category not found")

    fee_type = FeeType(
        school_id=data.school_id,
        category_id=data.category_id,
        section=data.section,
        term=data.term,
        amount_kobo=data.amount_kobo,
    )
    db.add(fee_type)
    db.commit()
    db.refresh(fee_type)

    logger.info(
        f"Fee type created: {fee_type.name} · {fee_type.section} · {fee_type.term}"
    )
    return fee_type


@router.get("/types", response_model=list[FeeTypeResponse])
def list_fee_types(
    school_id: int = Query(..., description="Filter by school"),
    section: str | None = Query(None, description="Filter by section"),
    db: Session = Depends(get_db),
):
    """List all fee types for a school, optionally filtered by section."""
    query = (
        db.query(FeeType)
        .options(joinedload(FeeType.category))
        .filter(FeeType.school_id == school_id)
    )
    if section:
        query = query.filter(FeeType.section == section)
    return query.order_by(FeeType.term.desc(), FeeType.section).all()


@router.delete("/types/{fee_type_id}", status_code=200)
def delete_fee_type(fee_type_id: int, db: Session = Depends(get_db)):
    """
    Delete a fee type — only if no student has it assigned, so we never leave a
    FeeRecord pointing at a fee type that no longer exists.
    """
    fee_type = db.query(FeeType).filter(FeeType.id == fee_type_id).first()
    if not fee_type:
        raise HTTPException(status_code=404, detail="Fee type not found")

    in_use = (
        db.query(FeeRecord).filter(FeeRecord.fee_type_id == fee_type_id).count()
    )
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Can't delete this fee type — {in_use} student(s) have it assigned."
            ),
        )

    db.delete(fee_type)
    db.commit()
    logger.info(f"Fee type deleted: id={fee_type_id}")
    return {"deleted": True, "id": fee_type_id}


# --------------------------------------------------------------------------
# Fee Record endpoints (per-student tracking)
# --------------------------------------------------------------------------

@router.post("/records", response_model=FeeRecordResponse, status_code=201)
def assign_fee_to_student(
    data: FeeRecordCreate,
    db: Session = Depends(get_db),
):
    """
    Assign a fee to a specific student.

    Creates a FeeRecord that tracks what this student owes and has paid.
    """
    student = db.query(Student).filter(Student.id == data.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    fee_type = db.query(FeeType).filter(FeeType.id == data.fee_type_id).first()
    if not fee_type:
        raise HTTPException(status_code=404, detail="Fee type not found")

    # Check for duplicate assignment
    existing = (
        db.query(FeeRecord)
        .filter(
            FeeRecord.student_id == data.student_id,
            FeeRecord.fee_type_id == data.fee_type_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail="This fee is already assigned to this student"
        )

    record = FeeRecord(
        student_id=data.student_id,
        fee_type_id=data.fee_type_id,
        total_fees_kobo=data.total_fees_kobo,
        amount_paid_kobo=0,
        status="unpaid",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    logger.info(
        f"Fee assigned: {fee_type.name} → {student.student_name} "
        f"(₦{data.total_fees_kobo / 100:,.2f})"
    )
    return record


@router.post("/records/bulk", status_code=201)
def bulk_assign_fees(
    data: BulkFeeAssign,
    db: Session = Depends(get_db),
):
    """
    Assign a fee type to multiple students at once.

    Useful when assigning "Tuition Term 1" to all students in a class.
    Skips students who already have this fee assigned (no duplicates).
    """
    fee_type = db.query(FeeType).filter(FeeType.id == data.fee_type_id).first()
    if not fee_type:
        raise HTTPException(status_code=404, detail="Fee type not found")

    amount = data.total_fees_kobo or fee_type.amount_kobo

    created = 0
    skipped = 0

    for student_id in data.student_ids:
        # Check if already assigned
        existing = (
            db.query(FeeRecord)
            .filter(
                FeeRecord.student_id == student_id,
                FeeRecord.fee_type_id == data.fee_type_id,
            )
            .first()
        )
        if existing:
            skipped += 1
            continue

        # Verify student exists
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            skipped += 1
            continue

        record = FeeRecord(
            student_id=student_id,
            fee_type_id=data.fee_type_id,
            total_fees_kobo=amount,
            amount_paid_kobo=0,
            status="unpaid",
        )
        db.add(record)
        created += 1

    db.commit()

    logger.info(f"Bulk fee assignment: {created} created, {skipped} skipped")
    return {
        "created": created,
        "skipped": skipped,
        "fee_type": fee_type.name,
        "amount_kobo": amount,
    }


@router.get("/records", response_model=list[FeeRecordResponse])
def list_fee_records(
    student_id: int | None = Query(None, description="Filter by student"),
    school_id: int | None = Query(None, description="Filter by school"),
    status: str | None = Query(None, description="Filter by status: unpaid, partial, paid"),
    db: Session = Depends(get_db),
):
    """
    List fee records, with optional filters.

    At least one of student_id or school_id must be provided.
    """
    if not student_id and not school_id:
        raise HTTPException(
            status_code=400,
            detail="Provide at least student_id or school_id"
        )

    query = db.query(FeeRecord).options(joinedload(FeeRecord.fee_type))

    if student_id:
        query = query.filter(FeeRecord.student_id == student_id)

    if school_id:
        query = query.join(FeeRecord.student).filter(Student.school_id == school_id)

    if status:
        query = query.filter(FeeRecord.status == status)

    return query.all()


@router.get("/records/{record_id}", response_model=FeeRecordResponse)
def get_fee_record(record_id: int, db: Session = Depends(get_db)):
    """Get a single fee record with its payment history."""
    record = (
        db.query(FeeRecord)
        .options(joinedload(FeeRecord.fee_type))
        .filter(FeeRecord.id == record_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Fee record not found")
    return record
