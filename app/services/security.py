"""
Password hashing and JWT session token utilities.
"""

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

_PBKDF2_ALGORITHM = "sha256"
_PBKDF2_ITERATIONS = 200_000
_SALT_BYTES = 16

_JWT_ALGORITHM = "HS256"


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------
def hash_password(plain_password: str) -> str:
    """
    Hash a plain-text password for storage.

    Returns a single string of the form:
        pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
    Everything needed to verify later (algorithm, iterations, salt) is packed
    in, so we never store the plain password anywhere.
    """
    salt = os.urandom(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        _PBKDF2_ALGORITHM, plain_password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(plain_password: str, stored_hash: str) -> bool:
    """
    Check a plain-text password against a stored hash.

    Uses hmac.compare_digest for a constant-time comparison, so an attacker
    can't learn the hash by timing how long the comparison takes.
    """
    try:
        algorithm, iterations, salt_hex, hash_hex = stored_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        derived = hashlib.pbkdf2_hmac(
            _PBKDF2_ALGORITHM,
            plain_password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(derived.hex(), hash_hex)
    except (ValueError, TypeError):
        # Malformed hash string — treat as a failed match, never crash.
        return False


# --------------------------------------------------------------------------
# Session tokens (JWT)
# --------------------------------------------------------------------------
def create_session_token(user_id: int, email: str, role: str) -> str:
    """
    Create a signed session token for a logged-in user.

    The token expires after settings.session_timeout_minutes. Because we
    re-issue it on every authenticated request (see the auth dependency),
    active users stay logged in and only idle sessions expire.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),      # subject — who this token is for
        "email": email,
        "role": role,
        "iat": now,               # issued-at
        "exp": now + timedelta(minutes=settings.session_timeout_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM)


def decode_session_token(token: str) -> dict | None:
    """
    Verify and decode a session token.

    Returns the payload dict if the token is valid and not expired, or None if
    it's invalid, tampered with, or expired (PyJWT raises in all those cases).
    """
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
