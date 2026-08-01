"""
Auth endpoints — login, logout, and "who am I".

- POST /api/v1/auth/login   → check credentials, set the session cookie
- POST /api/v1/auth/logout  → clear the session cookie
- GET  /api/v1/auth/me      → return the current user (used by the frontend to
                              decide whether to show the login screen or the app)

SECURITY NOTES:
- We return the SAME error for "no such email" and "wrong password", so an
  attacker can't discover which emails are registered.
- The password is verified with a constant-time comparison (see security.py).
- On success we log the activity and stamp last_login.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas.auth import LoginRequest, UserResponse
from app.services.auth_deps import (
    get_current_user,
    clear_session_cookie,
    _set_session_cookie,
)
from app.services.security import verify_password, create_session_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


@router.post("/login", response_model=UserResponse)
def login(
    credentials: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Verify email + password and start a session."""
    email = credentials.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    # Same generic message whether the email is unknown or the password is wrong.
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password.",
    )

    if not user or not user.is_active:
        raise invalid
    if not verify_password(credentials.password, user.hashed_password):
        raise invalid

    # Success — issue the session cookie.
    token = create_session_token(user_id=user.id, email=user.email, role=user.role)
    _set_session_cookie(response, token)

    user.last_login = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    logger.info(f"Login successful: {user.email} (id={user.id})")
    return user


@router.post("/logout")
def logout(response: Response):
    """End the session by clearing the cookie."""
    clear_session_cookie(response)
    return {"status": "ok", "message": "Logged out"}


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    """
    Return the currently logged-in user.

    The frontend calls this on load: a 200 means "show the app", a 401 means
    "show the login screen".
    """
    return current_user
