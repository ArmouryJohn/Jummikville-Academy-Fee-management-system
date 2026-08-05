"""
Auth dependencies — the gate that protects data endpoints.

HOW A PROTECTED REQUEST FLOWS:
1. Browser sends its session cookie automatically (it's httpOnly, set at login).
2. get_current_user reads that cookie, verifies the JWT signature + expiry.
3. If valid, it loads the User from the DB and — crucially — re-issues the
   cookie with a fresh expiry. This is the "sliding session": every request
   you make pushes the idle-timeout further out, so active users never get
   logged out mid-work, but 30 minutes of inactivity ends the session.
4. If the cookie is missing/expired/invalid, it raises 401 and the frontend
   bounces the user to the login screen.

WHY A COOKIE (not an Authorization header):
The token lives in an httpOnly cookie, so JavaScript literally cannot read it.
That means an XSS bug can't steal the session token. The browser attaches it
automatically on same-origin requests, which is exactly our setup.
"""

import logging

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
from app.services.security import decode_session_token, create_session_token

logger = logging.getLogger(__name__)

# The name of the cookie that holds the session token.
SESSION_COOKIE_NAME = "jummikville_session"


def _set_session_cookie(response: Response, token: str) -> None:
    """
    Write the session token into an httpOnly cookie on the response.

    Flags explained:
    - httponly=True  → JavaScript can't read it (XSS protection)
    - samesite="lax" → cookie isn't sent on cross-site POSTs (CSRF mitigation)
    - secure=<prod>  → only sent over HTTPS in production (in dev we allow HTTP
                       so localhost works without certificates)
    - max_age        → browser drops the cookie after the idle window too
    """
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=settings.session_timeout_minutes * 60,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    """Remove the session cookie — used on logout."""
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


def get_current_user(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency: require a logged-in user, or raise 401.

    Add `current_user: User = Depends(get_current_user)` to any endpoint to
    protect it. The endpoint then also gets the authenticated user for free.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    payload = decode_session_token(token)
    if not payload:
        # Expired or tampered — force a fresh login.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
        )

    user_id = int(payload.get("sub", 0))
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account not found or disabled.",
        )

    # Sliding session: refresh the cookie so active use keeps the session alive.
    fresh = create_session_token(user_id=user.id, email=user.email, role=user.role)
    _set_session_cookie(response, fresh)

    return user


def require_director(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    FastAPI dependency: require a logged-in user with Director privileges.

    Raises HTTP 403 Forbidden if the user is a Staff Admin.
    """
    if not current_user.is_director:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Director role required to perform this action.",
        )
    return current_user
