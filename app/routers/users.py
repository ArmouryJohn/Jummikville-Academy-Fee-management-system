"""
User management endpoints for director-managed administrative accounts.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, School
from app.schemas.user import UserCreate, UserUpdate, UserResponse
from app.services.auth_deps import require_director
from app.services.security import hash_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/users", tags=["Users"])


@router.get("", response_model=list[UserResponse])
def list_users(
    school_id: int = Query(1, description="School ID"),
    db: Session = Depends(get_db),
    actor: User = Depends(require_director),
):
    """List all admin user accounts for a school (Director only)."""
    users = (
        db.query(User)
        .filter(User.school_id == school_id)
        .order_by(User.created_at.desc())
        .all()
    )
    return users


@router.post("", response_model=UserResponse, status_code=201)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_director),
):
    """
    Create/invite a new admin account (Director only).
    Role can be 'director' or 'staff_admin'.
    """
    school = db.query(School).filter(School.id == data.school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="School not found")

    email = data.email.strip().lower()
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An account with email '{email}' already exists.",
        )

    role = data.role.strip().lower()
    if role not in ("director", "staff_admin", "admin"):
        raise HTTPException(
            status_code=400,
            detail="Role must be either 'director' or 'staff_admin'.",
        )

    user = User(
        school_id=data.school_id,
        email=email,
        hashed_password=hash_password(data.password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info(f"Admin created by Director {actor.email}: {user.email} (role={user.role})")
    return user


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_director),
):
    """Edit an admin account (Director only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if data.email is not None:
        email = data.email.strip().lower()
        clash = db.query(User).filter(User.email == email, User.id != user_id).first()
        if clash:
            raise HTTPException(status_code=409, detail=f"Email '{email}' is already in use.")
        user.email = email

    if data.role is not None:
        role = data.role.strip().lower()
        if role not in ("director", "staff_admin", "admin"):
            raise HTTPException(status_code=400, detail="Role must be 'director' or 'staff_admin'.")
        user.role = role

    if data.is_active is not None:
        user.is_active = data.is_active

    if data.password:
        user.hashed_password = hash_password(data.password)

    db.commit()
    db.refresh(user)
    logger.info(f"User updated by Director {actor.email}: id={user.id}")
    return user


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_director),
):
    """Deactivate an admin account (Director only)."""
    if user_id == actor.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    db.commit()
    logger.info(f"User deactivated by Director {actor.email}: id={user_id}")
    return {"status": "ok", "message": "User deactivated"}
