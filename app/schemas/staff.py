"""
Pydantic schemas for Staff member profile management.
"""

from datetime import datetime
from pydantic import BaseModel, Field


class StaffCreate(BaseModel):
    """Payload to create a new staff member."""
    school_id: int = Field(1, description="School ID")
    full_name: str = Field(..., min_length=2, max_length=100)
    role_title: str = Field("Teacher", description="Staff title/role")
    phone_number: str = Field(..., min_length=5, max_length=50)
    email: str | None = None
    bank_name: str | None = None
    account_number: str | None = None
    account_name: str | None = None
    classes_taught: list[str] = Field(default_factory=list, description="List of classes assigned")


class StaffUpdate(BaseModel):
    """Payload to update an existing staff member."""
    full_name: str | None = None
    role_title: str | None = None
    phone_number: str | None = None
    email: str | None = None
    bank_name: str | None = None
    account_number: str | None = None
    account_name: str | None = None
    classes_taught: list[str] | None = None
    is_active: bool | None = None


class StaffResponse(BaseModel):
    """View of a staff record."""
    id: int
    school_id: int
    full_name: str
    role_title: str
    phone_number: str
    email: str | None = None
    bank_name: str | None = None
    account_number: str | None = None
    account_name: str | None = None
    classes_taught: list[str] = []
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
