"""
FastAPI application entry point.

This is the main file that brings everything together:
- Creates the FastAPI app
- Registers all routers (endpoints)
- Sets up database tables on startup
- Configures logging

TO RUN:
    uvicorn app.main:app --reload --port 8000

Then visit http://localhost:8000/docs for the interactive API documentation.
"""

import logging
import os
import secrets

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import engine, Base, SessionLocal
from app.config import settings
from app.constants import SECTION_CLASSES

# Import all models so SQLAlchemy knows about them
from app.models import School, Student, FeeCategory, Term, FeeType, FeeRecord, Payment, ActivityLog, User, WebhookEvent  # noqa: F401

# Import all routers
from app.routers import (
    webhooks, payments, reminders, students, fees, dashboard, activity, auth,
    terms, reports, expenses, users, payroll, staff,
)
from app.services.auth_deps import get_current_user
from app.services.security import hash_password

# --------------------------------------------------------------------------
# Configure logging
# --------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Create the FastAPI app
# --------------------------------------------------------------------------
app = FastAPI(
    title="Jummikville Fee Management System",
    description=(
        "Automated school fee tracking and WhatsApp notifications "
        "for Jummikville Academy, powered by CAR Hub."
    ),
    version="1.0.0",
    docs_url="/docs",      # Swagger UI at /docs
    redoc_url="/redoc",    # ReDoc at /redoc
)


# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------
# The frontend is served by this same app (see the static mount at the bottom),
# so same-origin requests work without CORS. But allowing all origins in
# development means you can ALSO open the HTML file directly, or point a
# separate dev server at this API, without hitting CORS errors while learning.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.is_production else [],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Startup event: create database tables
# --------------------------------------------------------------------------
@app.on_event("startup")
def on_startup():
    """
    Create all database tables when the app starts.

    This is safe to call multiple times — it only creates tables that
    don't exist yet (it won't delete or modify existing tables).

    For more complex schema changes, use Alembic migrations.
    """
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ready.")

    _seed_admin_user()
    _seed_fee_categories()


# The eight fee categories the school starts with. Staff can add more from the
# Setup screen — these are just sensible defaults so the system is usable on
# day one without hand-entering them. Categories are school-wide (not
# section-specific); a 'Tuition Fee' category covers Preschool, Primary, and
# Smart Skills High School alike.
DEFAULT_FEE_CATEGORIES = [
    "Tuition Fee",
    "Textbook Fee",
    "Lesson Fee",
    "Party Fee",
    "Vocational Fee",
    "PTA/Development Levy",
    "Sports/Games Fee",
    "Exam/Registration Fee",
]


def _seed_fee_categories():
    """
    Ensure the school has its default fee categories.

    Runs on every startup but only ever ADDS a category that's missing — it
    never deletes or renames existing ones, so a category staff added by hand
    (or renamed) is left untouched. New defaults are matched by name
    (case-insensitive) against what's already there.
    """
    db = SessionLocal()
    try:
        school = db.query(School).filter(School.slug == "jummikville").first()
        if not school:
            # No school yet — _seed_admin_user creates one; on the next startup
            # this will find it. Nothing to seed against right now.
            logger.info("No school found yet — skipping fee category seeding.")
            return

        existing_names = {
            name.lower()
            for (name,) in db.query(FeeCategory.name)
            .filter(FeeCategory.school_id == school.id)
            .all()
        }

        added = 0
        for name in DEFAULT_FEE_CATEGORIES:
            if name.lower() in existing_names:
                continue
            db.add(FeeCategory(school_id=school.id, name=name))
            added += 1

        if added:
            db.commit()
            logger.info(f"Seeded {added} default fee categories for {school.name}.")
        else:
            logger.info("Fee categories already present — nothing to seed.")
    except Exception:
        db.rollback()
        logger.exception("Failed to seed fee categories.")
    finally:
        db.close()


def _seed_admin_user():
    """
    Ensure there's at least one admin account to log in with.

    Runs on every startup but only ever CREATES the admin once — if the
    configured admin email already exists, we leave it untouched (so we never
    reset a password someone has since changed).

    Password precedence:
    1. ADMIN_PASSWORD from the environment/.env — used as-is.
    2. Otherwise a strong random password is generated and printed to the log
       ONCE. Grab it from the startup output, log in, and change it.
    """
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == settings.admin_email).first()
        if existing:
            logger.info(f"Admin account present: {existing.email} (id={existing.id})")
            return

        # The admin has to belong to a school. Reuse the seeded Jummikville
        # school if it's there; otherwise create a minimal default so login
        # works even on a fresh database that hasn't run seed.py.
        school = db.query(School).filter(School.slug == "jummikville").first()
        if not school:
            school = School(
                name="Jummikville Academy",
                slug="jummikville",
                email=settings.admin_email,
            )
            db.add(school)
            db.flush()
            logger.info(f"Created default school: {school.name} (id={school.id})")

        # Use the configured password, or mint a random one and show it once.
        generated = settings.admin_password is None
        password = settings.admin_password or secrets.token_urlsafe(12)

        admin = User(
            school_id=school.id,
            email=settings.admin_email,
            hashed_password=hash_password(password),
            role="admin",
            is_active=True,
        )
        db.add(admin)
        db.commit()

        logger.info(f"Seeded admin account: {admin.email}")
        if generated:
            # Printed once, and only when we generated it. Never log a password
            # the operator chose themselves.
            logger.warning(
                "=" * 68
                + f"\n  ADMIN LOGIN CREATED\n"
                + f"  Email:    {settings.admin_email}\n"
                + f"  Password: {password}\n"
                + "  Save this now — it will NOT be shown again. "
                + "Set ADMIN_PASSWORD in .env to choose your own.\n"
                + "=" * 68
            )
    except Exception:
        db.rollback()
        logger.exception("Failed to seed admin user.")
    finally:
        db.close()


# --------------------------------------------------------------------------
# Register routers
# --------------------------------------------------------------------------
# --- Public routers (no login required) ---
# auth: the login/logout/me endpoints themselves must be reachable logged-out.
# webhooks: called server-to-server by Paystack, which has no session cookie —
#           it's secured separately by verifying Paystack's signature.
app.include_router(auth.router)
app.include_router(webhooks.router)

# --- Protected routers (require a valid session cookie) ---
# Attaching the dependency here guards every endpoint in each router at once,
# so we can't forget to protect a new endpoint later.
_auth = [Depends(get_current_user)]
app.include_router(payments.router, dependencies=_auth)
app.include_router(reminders.router, dependencies=_auth)
app.include_router(students.router, dependencies=_auth)
app.include_router(fees.router, dependencies=_auth)
app.include_router(terms.router, dependencies=_auth)
app.include_router(reports.router, dependencies=_auth)
app.include_router(expenses.router, dependencies=_auth)
app.include_router(dashboard.router, dependencies=_auth)
app.include_router(activity.router, dependencies=_auth)
app.include_router(users.router, dependencies=_auth)
app.include_router(payroll.router, dependencies=_auth)
app.include_router(staff.router, dependencies=_auth)


# --------------------------------------------------------------------------
# API info endpoint
# --------------------------------------------------------------------------
# NOTE: this used to be at "/", but "/" now serves the frontend (see the static
# mount below). The same info is available here for scripts and health checks.
@app.get("/api")
def api_info():
    """API metadata / welcome endpoint."""
    return {
        "app": "Jummikville Fee Management System",
        "status": "running",
        "docs": "/docs",
        "powered_by": "CAR Hub",
    }


@app.get("/health")
def health():
    """Simple health check for monitoring."""
    return {"status": "ok"}


# --------------------------------------------------------------------------
# Serve the frontend (must be LAST so it doesn't shadow the API routes above)
# --------------------------------------------------------------------------
# The whole UI is a single static folder (frontend/). We mount it at the root
# so visiting http://localhost:8000/ opens the app, and the API lives under
# /api/v1/... on the same origin (no CORS needed in production).
_FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

if os.path.isdir(_FRONTEND_DIR):
    app.mount(
        "/",
        StaticFiles(directory=_FRONTEND_DIR, html=True),
        name="frontend",
    )
    logger.info(f"Frontend mounted from {_FRONTEND_DIR}")
else:
    logger.warning(
        f"Frontend directory not found at {_FRONTEND_DIR} — "
        f"API will run but the UI won't be served."
    )

    @app.get("/")
    def root_fallback():
        return {"message": "API running. Frontend folder not found.", "docs": "/docs"}
