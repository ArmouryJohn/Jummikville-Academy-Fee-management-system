"""
Database setup — creates the SQLAlchemy engine and session factory.

HOW THIS WORKS:
- SQLAlchemy "engine" is the connection to your database
- "SessionLocal" is a factory that creates database sessions (like opening a transaction)
- "Base" is the parent class all your models inherit from
- "get_db" is a FastAPI dependency that gives each request its own session and cleans up after

WHY SQLAlchemy:
- Write Python classes instead of raw SQL
- Automatic protection against SQL injection
- Switch between SQLite (dev) and PostgreSQL (prod) by changing one URL
- Handles connection pooling, transactions, and cleanup for you
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.config import settings


# --------------------------------------------------------------------------
# Engine: the actual connection to the database
# --------------------------------------------------------------------------
# check_same_thread=False is only needed for SQLite (it's single-threaded
# by default, but FastAPI uses multiple threads). PostgreSQL doesn't need this.
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    # Echo SQL statements to console in development (helpful for learning)
    echo=(not settings.is_production),
)

# --------------------------------------------------------------------------
# Session factory: creates new database sessions
# --------------------------------------------------------------------------
# autocommit=False means you control when changes are saved
# autoflush=False means SQLAlchemy won't auto-write to DB mid-query
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# --------------------------------------------------------------------------
# Base class: all models inherit from this
# --------------------------------------------------------------------------
class Base(DeclarativeBase):
    """
    Every database model (School, Student, etc.) inherits from this.
    SQLAlchemy uses this to track all your models and create tables.
    """
    pass


# --------------------------------------------------------------------------
# FastAPI dependency: gives each API request its own DB session
# --------------------------------------------------------------------------
def get_db():
    """
    Usage in a FastAPI route:
        @app.get("/students")
        def list_students(db: Session = Depends(get_db)):
            ...

    This creates a fresh session for each request, and automatically
    closes it when the request is done (even if there's an error).
    """
    db = SessionLocal()
    try:
        yield db  # The route function gets the session here
    finally:
        db.close()  # Always clean up, even on errors
