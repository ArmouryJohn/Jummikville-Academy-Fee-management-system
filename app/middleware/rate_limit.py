"""
Rate limiting middleware — protect the login endpoint from brute-force attacks.

An attacker who can try unlimited passwords will eventually guess one.
This middleware tracks failed login attempts per IP address and temporarily
blocks IPs that exceed a threshold.

STRATEGY:
- Allow up to MAX_ATTEMPTS failures per IP within a rolling WINDOW_SECONDS.
- On the (MAX_ATTEMPTS+1)th failure, return 429 Too Many Requests for
  LOCKOUT_SECONDS regardless of the password supplied.
- After LOCKOUT_SECONDS with no new failures, the counter resets.
- Successful logins are NOT counted (so a user who guesses correctly after
  a few tries isn't locked out).

STORAGE: in-memory dict — simple, no Redis dependency, survives restarts
(restarts reset the counters, which is acceptable for a school system).
For a high-traffic multi-process deployment, swap to Redis.

APPLIED TO: POST /api/v1/auth/login only.
"""

import time
import threading
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse


# ── Tunable parameters ────────────────────────────────────────────────────────
MAX_ATTEMPTS    = 10       # failures before lockout kicks in
WINDOW_SECONDS  = 300      # 5-minute rolling window for counting
LOCKOUT_SECONDS = 600      # 10-minute lockout after too many failures

# Only rate-limit this path.
_LOGIN_PATH = "/api/v1/auth/login"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Brute-force protection for the login endpoint.

    Thread-safe in-memory counter keyed by client IP.
    """

    def __init__(self, app):
        super().__init__(app)
        # {ip: {"count": int, "window_start": float, "locked_until": float}}
        self._records: dict = defaultdict(lambda: {
            "count": 0,
            "window_start": time.monotonic(),
            "locked_until": 0.0,
        })
        self._lock = threading.Lock()

    def _get_ip(self, request: Request) -> str:
        """
        Return the real client IP, respecting the X-Forwarded-For header that
        Render (and other reverse proxies) inject.
        """
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next) -> Response:
        # Only rate-limit the login endpoint.
        if request.url.path != _LOGIN_PATH or request.method != "POST":
            return await call_next(request)

        ip = self._get_ip(request)
        now = time.monotonic()

        with self._lock:
            rec = self._records[ip]

            # Still within lockout period?
            if rec["locked_until"] > now:
                remaining = int(rec["locked_until"] - now)
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": (
                            f"Too many failed login attempts. "
                            f"Please wait {remaining} seconds before trying again."
                        )
                    },
                    headers={"Retry-After": str(remaining)},
                )

            # Roll the window if it's expired.
            if now - rec["window_start"] > WINDOW_SECONDS:
                rec["count"] = 0
                rec["window_start"] = now

        # Let the actual login endpoint run.
        response = await call_next(request)

        # Count failures (4xx from the login endpoint = bad credentials).
        if response.status_code in (401, 422):
            with self._lock:
                rec = self._records[ip]
                rec["count"] += 1
                if rec["count"] >= MAX_ATTEMPTS:
                    rec["locked_until"] = now + LOCKOUT_SECONDS
                    rec["count"] = 0          # reset for after the lockout
                    rec["window_start"] = now

        return response
