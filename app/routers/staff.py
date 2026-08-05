"""
Staff Management Router — Director-only CRUD for school staff records.

ENDPOINTS:
- GET    /api/v1/staff — List staff members (filterable by role, class, status)
- POST   /api/v1/staff — Create a new staff member with bank details & classes
- PATCH  /api/v1/staff/{staff_id} — Update staff details
- DELETE /api/v1/staff/{staff_id} — Soft delete / deactivate staff member
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Staff, User, ActivityLog
from app.schemas.staff import StaffCreate, StaffUpdate, StaffResponse
from app.services.auth_deps import require_director

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/staff", tags=["staff"])



@router.get("", response_model=List[StaffResponse])
def list_staff(
    school_id: int = Query(1, description="School ID"),
    role_title: Optional[str] = Query(None, description="Filter by role/title"),
    class_taught: Optional[str] = Query(None, description="Filter by class taught"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    db: Session = Depends(get_db),
    actor: User = Depends(require_director),
):
    """
    List staff records for the school. Filterable by role, class taught, or active status.
    """
    query = db.query(Staff).filter(Staff.school_id == school_id)

    if is_active is not None:
        query = query.filter(Staff.is_active == is_active)

    if role_title:
        query = query.filter(Staff.role_title.ilike(f"%{role_title}%"))

    results = query.order_by(Staff.full_name.asc()).all()

    if class_taught:
        # Filter JSON array in Python
        results = [
            s for s in results
            if s.classes_taught and class_taught in s.classes_taught
        ]

    return results


@router.post("", response_model=StaffResponse, status_code=status.HTTP_201_CREATED)
def create_staff(
    data: StaffCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_director),
):
    """
    Create a new staff member record with bank details & assigned classes.
    """
    staff = Staff(
        school_id=data.school_id,
        full_name=data.full_name.strip(),
        role_title=data.role_title.strip(),
        phone_number=data.phone_number.strip(),
        email=data.email.strip() if data.email else None,
        bank_name=data.bank_name.strip() if data.bank_name else None,
        account_number=data.account_number.strip() if data.account_number else None,
        account_name=data.account_name.strip() if data.account_name else None,
        classes_taught=data.classes_taught or [],
        is_active=True,
    )
    db.add(staff)
    db.commit()
    db.refresh(staff)

    # Activity audit log
    db.add(ActivityLog(
        school_id=data.school_id,
        action="staff_created",
        description=f"Staff member {staff.full_name} ({staff.role_title}) added by Director {actor.email}.",
    ))
    db.commit()

    return staff


@router.patch("/{staff_id}", response_model=StaffResponse)
def update_staff(
    staff_id: int,
    data: StaffUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_director),
):
    """
    Update staff record details.
    """
    staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found")

    if data.full_name is not None:
        staff.full_name = data.full_name.strip()
    if data.role_title is not None:
        staff.role_title = data.role_title.strip()
    if data.phone_number is not None:
        staff.phone_number = data.phone_number.strip()
    if data.email is not None:
        staff.email = data.email.strip() if data.email else None
    if data.bank_name is not None:
        staff.bank_name = data.bank_name.strip() if data.bank_name else None
    if data.account_number is not None:
        staff.account_number = data.account_number.strip() if data.account_number else None
    if data.account_name is not None:
        staff.account_name = data.account_name.strip() if data.account_name else None
    if data.classes_taught is not None:
        staff.classes_taught = data.classes_taught
    if data.is_active is not None:
        staff.is_active = data.is_active

    db.commit()
    db.refresh(staff)
    return staff


@router.delete("/{staff_id}")
def delete_staff(
    staff_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_director),
):
    """
    Soft-delete / deactivate a staff member after confirmation.
    Preserves historical payroll records.
    """
    staff = db.query(Staff).filter(Staff.id == staff_id).first()
    if not staff:
        raise HTTPException(status_code=404, detail="Staff member not found")

    staff.is_active = False
    db.commit()

    db.add(ActivityLog(
        school_id=staff.school_id,
        action="staff_deactivated",
        description=f"Staff member {staff.full_name} deactivated by Director {actor.email}. Payroll history preserved.",
    ))
    db.commit()

    return {"status": "ok", "message": f"Staff member '{staff.full_name}' deactivated."}
