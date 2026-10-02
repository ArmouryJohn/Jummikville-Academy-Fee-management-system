"""
Security middleware — HTTP hardening headers applied to every response.

These headers tell browsers to:
- Only load content from our own domain (CSP)
- Always use HTTPS (HSTS)
- Refuse to be embedded in iframes (clickjacking protection)
- Block MIME-type sniffing attacks
- Control referrer information leakage
- Disable dangerous browser features

None of these break normal app behaviour — they only restrict what
third-party/malicious code can do in a user's browser.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Inject security headers on every HTTP response.

    Applied before the CORS middleware so headers are always present.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # ── Clickjacking protection ─────────────────────────────────────────
        # Refuses to load the page inside an <iframe> — prevents attackers
        # from overlaying our login form inside their own page.
        response.headers["X-Frame-Options"] = "DENY"

        # ── MIME sniffing protection ────────────────────────────────────────
        # Tells the browser to trust the Content-Type we declare, not guess.
        # Prevents an attacker who can upload a file from tricking the browser
        # into executing it as a script.
        response.headers["X-Content-Type-Options"] = "nosniff"

        # ── Referrer policy ────────────────────────────────────────────────
        # When a user clicks a link to an external site, don't leak the full
        # URL in the Referer header (could contain student IDs, etc.).
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # ── Permissions policy ─────────────────────────────────────────────
        # Explicitly disable browser features this app never needs.
        # Prevents malicious injected JS from accessing camera/microphone/GPS.
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), "
            "payment=(), usb=(), bluetooth=()"
        )

        # ── Content Security Policy ────────────────────────────────────────
        # The most powerful header: tells the browser exactly which sources
        # of scripts/styles/images are allowed. Anything else is blocked.
        #
        # Breakdown:
        #   default-src 'self'         → only load from our own origin by default
        #   script-src  'self' + CDNs  → allow our app.js + Tailwind/Alpine/Chart
        #   style-src   'self' 'unsafe-inline' + Google Fonts
        #                              → Tailwind generates inline styles; Google
        #                                Fonts uses a stylesheet
        #   font-src    'self' + Google Fonts
        #   img-src     'self' data:   → allow our images + data URIs (Chart.js
        #                                uses data URIs for chart exports)
        #   connect-src 'self'         → only our own API (no external fetch)
        #   frame-ancestors 'none'     → same as X-Frame-Options DENY, belt+braces
        #   base-uri 'self'            → prevent <base> tag injection
        #   form-action 'self'         → forms can only POST to our own origin
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' "
            "https://cdn.tailwindcss.com "
            "https://cdn.jsdelivr.net "
            "https://cdn.jsdelivr.net/npm/alpinejs@3.14.1/dist/cdn.min.js "
            "https://cdn.jsdelivr.net/npm/chart.js; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
        )

        # ── HSTS (production only) ─────────────────────────────────────────
        # Once a browser has visited our HTTPS site, it will ONLY use HTTPS
        # for the next year — even if the user types "http://". Prevents
        # SSL-stripping attacks. Never set on localhost (breaks dev).
        if "https" in request.url.scheme or request.headers.get("x-forwarded-proto") == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response
