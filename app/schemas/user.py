"""
Pydantic schemas for admin account creation and management (Director-only).
"""

from datetime import datetime
from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    """Payload to invite/create a new admin account (Director or Staff Admin)."""
    email: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=6, max_length=100)
    role: str = Field("staff_admin", description="'director' or 'staff_admin'")
    school_id: int = Field(1, description="School ID")


class UserUpdate(BaseModel):
    """Payload to update an existing admin account."""
    email: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


class UserResponse(BaseModel):
    """Public representation of an admin user."""
    id: int
    school_id: int
    email: str
    role: str
    is_active: bool
    created_at: datetime
    last_login: datetime | None = None

    model_config = {"from_attributes": True}
