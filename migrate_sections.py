"""
One-time migration: rename school sections and normalise class names.

RUN ONCE before restarting the server after updating the code:
    python migrate_sections.py

WHAT IT DOES:
  1. Renames 'Nursery'   → 'Preschool'               in students + fee_types
  2. Renames 'Secondary' → 'Smart Skills High School' in students + fee_types
  3. Normalises class_name values to the new enum
     (e.g. 'JSS 1' → 'JSS1', 'SS 1' → 'SS1')
  4. Prints a before/after report

IDEMPOTENT: safe to run more than once — nothing changes on a second run.
"""

from app.database import SessionLocal, engine, Base
from app.models import Student, FeeType

# --------------------------------------------------------------------------
# Section renames
# --------------------------------------------------------------------------
SECTION_RENAMES = {
    "Nursery":   "Preschool",
    "Secondary": "Smart Skills High School",
}

# --------------------------------------------------------------------------
# Class name normalisations (old free-text → new enum value)
# Maps old values that seed.py / manual entry might have produced.
# --------------------------------------------------------------------------
CLASS_RENAMES = {
    # Secondary → Smart Skills High School classes
    "JSS 1": "JSS1",
    "JSS 2": "JSS2",
    "JSS 3": "JSS3",
    "SS 1":  "SS1",
    "SS 2":  "SS2",
    "SS 3":  "SS3",
    # Nursery → Preschool classes (old free-text guesses)
    "Nursery 1":  "Preschool 1",
    "Nursery 2":  "Preschool 2",
    "Nursery 3":  "Preschool 3",
    "Preschool1": "Preschool 1",
    "Preschool2": "Preschool 2",
    "Preschool3": "Preschool 3",
    # Primary — these are already correct but include common variants
    "Primary1": "Primary 1",
    "Primary2": "Primary 2",
    "Primary3": "Primary 3",
    "Primary4": "Primary 4",
    "Primary5": "Primary 5",
    "Primary6": "Primary 6",
}


def migrate():
    db = SessionLocal()
    try:
        print("=" * 60)
        print("Jummikville Section Migration")
        print("=" * 60)

        # ------------------------------------------------------------------
        # 1. Student.section rename
        # ------------------------------------------------------------------
        student_section_changes = 0
        for old, new in SECTION_RENAMES.items():
            students = db.query(Student).filter(Student.section == old).all()
            for s in students:
                print(f"  [student] {s.student_name}: section '{old}' -> '{new}'")
                s.section = new
                student_section_changes += 1

        # ------------------------------------------------------------------
        # 2. FeeType.section rename
        # ------------------------------------------------------------------
        fee_type_changes = 0
        for old, new in SECTION_RENAMES.items():
            fee_types = db.query(FeeType).filter(FeeType.section == old).all()
            for ft in fee_types:
                print(f"  [fee_type id={ft.id}] section '{old}' -> '{new}'")
                ft.section = new
                fee_type_changes += 1

        # ------------------------------------------------------------------
        # 3. Student.class_name normalisation
        # ------------------------------------------------------------------
        class_changes = 0
        all_students = db.query(Student).all()
        for s in all_students:
            if s.class_name and s.class_name in CLASS_RENAMES:
                new_class = CLASS_RENAMES[s.class_name]
                print(f"  [class] {s.student_name}: class_name '{s.class_name}' -> '{new_class}'")
                s.class_name = new_class
                class_changes += 1

        # ------------------------------------------------------------------
        # Commit
        # ------------------------------------------------------------------
        db.commit()

        print()
        print("Migration complete:")
        print(f"  Student sections renamed:  {student_section_changes}")
        print(f"  Fee type sections renamed: {fee_type_changes}")
        print(f"  Class names normalised:    {class_changes}")
        print()
        print("Next steps:")
        print("  1. Delete jummikville.db and re-seed:  python seed.py")
        print("     (required because String(20) -> String(50) column change)")
        print("  2. Restart the server:  uvicorn app.main:app --reload --port 8000")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] Migration failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
