"""
Pydantic schemas for authentication requests and responses.

Kept deliberately small: a login takes an email + password, and the only thing
we ever send back about a user is safe, non-secret profile info (never the
password hash).
"""

from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """What the login form submits."""
    # Plain str (not EmailStr) to avoid the extra email-validator dependency —
    # login just needs to match what's stored; we normalise case on both sides.
    email: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=1, max_length=200)


class UserResponse(BaseModel):
    """Safe, public-facing view of a user — no password hash, ever."""
    id: int
    school_id: int
    email: str
    role: str
    is_active: bool
    last_login: datetime | None

    model_config = {"from_attributes": True}
