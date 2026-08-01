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
from app.models import School, Student, FeeCategory, FeeType, FeeRecord
from app.utils.formatting import normalize_phone

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
            phone="+2348012345678",  # Replace with real school phone
            email="info@jummikvilleacademy.com",
            address="Uyo, Akwa Ibom State, Nigeria",
        )
        db.add(school)
        db.flush()  # Get the school.id without committing
        print(f"[OK] School created: {school.name} (id={school.id})")

        # ---- 2. Seed the default fee categories ----
        for name in DEFAULT_FEE_CATEGORIES:
            _ensure_category(db, school.id, name)
        db.flush()
        print(f"[OK] Fee categories seeded: {len(DEFAULT_FEE_CATEGORIES)}")

        tuition_cat = _ensure_category(db, school.id, "Tuition Fee")
        textbook_cat = _ensure_category(db, school.id, "Textbook Fee")

        # ---- 3. Create sample fee types (category + section + term + amount) ----
        tuition = FeeType(
            school_id=school.id,
            category_id=tuition_cat.id,
            section="Primary",
            term="Term 1 2025/2026",
            amount_kobo=7_500_000,  # ₦75,000
        )
        books = FeeType(
            school_id=school.id,
            category_id=textbook_cat.id,
            section="Primary",
            term="Term 1 2025/2026",
            amount_kobo=1_500_000,  # ₦15,000
        )
        db.add_all([tuition, books])
        db.flush()
        print("[OK] Fee types created:")
        print(f"   - {tuition.name} ({tuition.section}): NGN {tuition.amount_kobo / 100:,.2f}")
        print(f"   - {books.name} ({books.section}): NGN {books.amount_kobo / 100:,.2f}")

        # ---- 4. Create sample students ----
        # Replace these with real student/parent data
        sample_students = [
            {
                "student_name": "Emmanuel Okon",
                "section": "Primary",
                "class_name": "Primary 4",
                "parent_name": "Mrs. Okon",
                "parent_phone": "08012345678",  # Replace with real number
                "parent_email": "okon.parent@email.com",
            },
            {
                "student_name": "Grace Udoh",
                "section": "Primary",
                "class_name": "Primary 4",
                "parent_name": "Mr. Udoh",
                "parent_phone": "08098765432",  # Replace with real number
                "parent_email": "udoh.parent@email.com",
            },
            {
                "student_name": "David Essien",
                "section": "Secondary",
                "class_name": "JSS 1",
                "parent_name": "Mrs. Essien",
                "parent_phone": "07011223344",  # Replace with real number
                "parent_email": "essien.parent@email.com",
            },
        ]

        students = []
        for data in sample_students:
            student = Student(
                school_id=school.id,
                student_name=data["student_name"],
                section=data["section"],
                class_name=data["class_name"],
                parent_name=data["parent_name"],
                parent_phone=normalize_phone(data["parent_phone"]),
                parent_email=data["parent_email"],
            )
            db.add(student)
            students.append(student)

        db.flush()
        print(f"[OK] Students created: {len(students)}")
        for s in students:
            print(f"   - {s.student_name} ({s.section} / {s.class_name}) - Parent: {s.parent_name}")

        # ---- 5. Assign the Primary tuition fee to the Primary students ----
        primary_students = [s for s in students if s.section == "Primary"]
        for student in primary_students:
            record = FeeRecord(
                student_id=student.id,
                fee_type_id=tuition.id,
                total_fees_kobo=tuition.amount_kobo,
                amount_paid_kobo=0,
                status="unpaid",
            )
            db.add(record)

        db.flush()
        print(f"[OK] Tuition fee assigned to {len(primary_students)} Primary students")

        # ---- 6. Simulate a partial payment for one student ----
        # This makes the test data more realistic
        if primary_students:
            first_record = (
                db.query(FeeRecord)
                .filter(
                    FeeRecord.student_id == primary_students[0].id,
                    FeeRecord.fee_type_id == tuition.id,
                )
                .first()
            )
            if first_record:
                first_record.amount_paid_kobo = 5_000_000  # ₦50,000 paid
                first_record.recalculate_status()
                print(
                    f"[OK] Simulated partial payment for {primary_students[0].student_name}: "
                    f"NGN 50,000 paid, NGN 25,000 remaining"
                )

        # ---- Commit everything ----
        db.commit()
        print("\n[DONE] Seed complete! Your database is ready.")
        print("\nNext steps:")
        print("  1. Copy .env.example to .env and fill in your real API keys")
        print("  2. Run: uvicorn app.main:app --reload --port 8000")
        print("  3. Visit: http://localhost:8000/docs")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Seed failed: {e}")
        raise

    finally:
        db.close()


if __name__ == "__main__":
    seed()
