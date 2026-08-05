"""
Wipe DEMO transactional data and set the school's real details.

RUN with the server stopped:
    python reset_demo_data.py

WHAT IT DELETES (the seeded demo data):
    payments, fee_records, fee_types, students, activity_logs, webhook_events,
    and every generated receipt PDF under storage/receipts/.

WHAT IT KEEPS:
    - the School row (its identity is UPDATED to the real address/phone/email)
    - the fee-category catalog (the 8 default FeeCategory rows)
    - the admin User(s) — so your login still works.

Deletion order respects foreign keys: children before parents. Idempotent —
running it again on an already-clean DB just re-asserts the school details and
deletes nothing.
"""

import os
import logging

from app.database import SessionLocal
from app.models import (
    Student, FeeType, FeeRecord, Payment, ActivityLog, WebhookEvent, School,
)
from app.services.receipt_service import _STORAGE_DIR

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("reset_demo_data")

# The real school details (single-school system — Jummikville Academy).
SCHOOL_NAME = "Jummikville Academy"
SCHOOL_PHONE = "08082060202, 08023548624, 08034438032"
SCHOOL_EMAIL = "jummikvilleacademy@gmail.com"
SCHOOL_ADDRESS = (
    "29c Udo Ekot Street, Mbiaobong Ikot Antem, "
    "Uyo, Akwa Ibom State, Nigeria."
)


def _delete_receipt_files() -> int:
    """Remove generated receipt PDFs from disk. Returns count removed."""
    if not os.path.isdir(_STORAGE_DIR):
        return 0
    removed = 0
    for name in os.listdir(_STORAGE_DIR):
        if name.lower().endswith(".pdf"):
            try:
                os.remove(os.path.join(_STORAGE_DIR, name))
                removed += 1
            except OSError as exc:  # pragma: no cover - defensive
                logger.warning(f"Could not delete {name}: {exc}")
    return removed


def reset():
    db = SessionLocal()
    try:
        # ---- Delete transactional/demo data, children first ----
        # (fee_records cascade-delete their payments via the ORM relationship,
        # but we delete payments explicitly so a bulk delete needs no object load.)
        counts = {}
        for label, model in [
            ("payments", Payment),
            ("fee_records", FeeRecord),
            ("fee_types", FeeType),
            ("students", Student),
            ("activity_logs", ActivityLog),
            ("webhook_events", WebhookEvent),
        ]:
            counts[label] = db.query(model).delete(synchronize_session=False)
        db.commit()

        for label, n in counts.items():
            logger.info(f"Deleted {n:>4} {label}")

        # ---- Update the school to the real details ----
        school = db.query(School).filter(School.slug == "jummikville").first()
        if school is None:
            logger.warning("No 'jummikville' school found — nothing to update.")
        else:
            school.name = SCHOOL_NAME
            school.phone = SCHOOL_PHONE
            school.email = SCHOOL_EMAIL
            school.address = SCHOOL_ADDRESS
            db.commit()
            logger.info("Updated school details:")
            logger.info(f"  Address: {school.address}")
            logger.info(f"  Phone:   {school.phone}")
            logger.info(f"  Email:   {school.email}")

        # ---- Delete generated receipt PDFs ----
        removed = _delete_receipt_files()
        logger.info(f"Deleted {removed} receipt PDF file(s)")

        logger.info("")
        logger.info("Done. Admin login and fee categories preserved.")
        logger.info("Add real students & fees through the app UI.")

    except Exception as exc:
        db.rollback()
        logger.error(f"Reset failed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    reset()
