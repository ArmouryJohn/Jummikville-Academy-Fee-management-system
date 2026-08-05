"""
Seed script — populates the database with initial data for Jummikville Academy.

RUN THIS ONCE after setting up the database:
    python seed.py

This creates:
1. Jummikville Academy as a school
2. The default fee categories (if not already seeded by the app on startup)
3. A couple of sample fee types (category + section + term + amount)
4. Sample students (each in a section) with parent contact info
5. Fee records assigned to each student

After running this, you can test the system with real API calls.
"""

from app.database import SessionLocal, engine, Base
from app.models import School, FeeCategory

# The default categories the school starts with. Mirrors the list the app seeds
# on startup — kept here so `python seed.py` on a bare database is self-sufficient.
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


def _ensure_category(db, school_id: int, name: str) -> FeeCategory:
    """Fetch a category by name (case-insensitive), creating it if missing."""
    cat = (
        db.query(FeeCategory)
        .filter(FeeCategory.school_id == school_id, FeeCategory.name.ilike(name))
        .first()
    )
    if not cat:
        cat = FeeCategory(school_id=school_id, name=name)
        db.add(cat)
        db.flush()
    return cat


def seed():
    """Populate the database with initial data."""
    # Create tables
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    try:
        # Check if data already exists
        existing_school = db.query(School).filter(School.slug == "jummikville").first()
        if existing_school:
            print("[SKIP] Data already exists! Skipping seed.")
            print(f"   School: {existing_school.name} (id={existing_school.id})")
            return

        # ---- 1. Create the school ----
        school = School(
            name="Jummikville Academy",
            slug="jummikville",
            phone="08082060202, 08023548624, 08034438032",
            email="jummikvilleacademy@gmail.com",
            address=(
                "29c Udo Ekot Street, Mbiaobong Ikot Antem, "
                "Uyo, Akwa Ibom State, Nigeria."
            ),
        )
        db.add(school)
        db.flush()  # Get the school.id without committing
        print(f"[OK] School created: {school.name} (id={school.id})")

        # ---- 2. Seed the default fee categories ----
        for name in DEFAULT_FEE_CATEGORIES:
            _ensure_category(db, school.id, name)
        db.flush()
        print(f"[OK] Fee categories seeded: {len(DEFAULT_FEE_CATEGORIES)}")

        # ---- Commit everything ----
        # NOTE: we intentionally seed ONLY the school, admin (seeded by the app
        # on startup) and the fee-category catalog — NO sample students, fee
        # types, records or payments. Real students and fees are entered through
        # the app UI. (The old demo students/partial-payment block was removed.)
        db.commit()
        print("\n[DONE] Seed complete! Clean school ready — add students via the UI.")
        print("\nNext steps:")
        print("  1. Copy .env.example to .env and fill in your real API keys")
        print("  2. Run: uvicorn app.main:app --reload --port 8000")
        print("  3. Visit: http://localhost:8000/  → Setup to add fees & students")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Seed failed: {e}")
        raise

    finally:
        db.close()


if __name__ == "__main__":
    seed()
