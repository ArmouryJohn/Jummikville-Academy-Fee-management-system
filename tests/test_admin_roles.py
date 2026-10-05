"""
Tests for user role-based permissions and director-only operations.
"""

import pytest
from fastapi import HTTPException
from app.models import User, Student
from app.services.auth_deps import require_director
from app.routers.users import list_users, create_user, UserCreate
from app.routers.students import delete_student


@pytest.fixture()
def director_user(db, school):
    u = User(
        school_id=school.id,
        email="director@jummikville.sch",
        hashed_password="hash",
        role="director",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture()
def staff_admin_user(db, school):
    u = User(
        school_id=school.id,
        email="bursar@jummikville.sch",
        hashed_password="hash",
        role="staff_admin",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_require_director_dependency(director_user, staff_admin_user):
    """require_director allows Director and raises 403 on Staff Admin."""
    assert require_director(director_user) == director_user

    with pytest.raises(HTTPException) as exc_info:
        require_director(staff_admin_user)
    assert exc_info.value.status_code == 403
    assert "Director role required" in exc_info.value.detail


def test_staff_admin_cannot_list_users(db, school, staff_admin_user, director_user):
    """Staff Admin calling list_users raises 403."""
    with pytest.raises(HTTPException) as exc:
        list_users(school_id=school.id, db=db, actor=require_director(staff_admin_user))
    assert exc.value.status_code == 403


def test_director_can_create_and_list_users(db, school, director_user):
    """Director can list users and invite new admin accounts."""
    users_before = list_users(school_id=school.id, db=db, actor=require_director(director_user))
    count_before = len(users_before)

    # Director creates a new Staff Admin account
    new_data = UserCreate(email="newbursar@jummikville.sch", password="secretpassword", role="staff_admin", school_id=school.id)
    created = create_user(data=new_data, db=db, actor=require_director(director_user))

    assert created.email == "newbursar@jummikville.sch"
    assert created.role == "staff_admin"

    users_after = list_users(school_id=school.id, db=db, actor=require_director(director_user))
    assert len(users_after) == count_before + 1


def test_staff_admin_cannot_delete_student(db, school, student, staff_admin_user, director_user):
    """Staff Admin cannot delete/deactivate a student; Director can."""
    # Attempt delete as staff_admin -> 403
    with pytest.raises(HTTPException) as exc:
        delete_student(student_id=student.id, db=db, actor=require_director(staff_admin_user))
    assert exc.value.status_code == 403

    # Delete as director -> success
    res = delete_student(student_id=student.id, db=db, actor=require_director(director_user))
    assert res["status"] == "ok"

    db.refresh(student)
    assert student.is_active is False
