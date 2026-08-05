"""
One-time migration for the "Term is a real row, not a free-text string" change.

RUN ONCE, with the server stopped, after pulling this code:
    python migrate_terms.py

BACKGROUND — WHAT CHANGED IN THE CODE:
  Before: fee_types.term was a free-text VARCHAR column ("First Term 2025/2026").
          A typo silently split one term's money into two buckets, and there was
          nowhere to store term dates or a "current term" flag.
  After:  There is a real `terms` table. FeeType.term_id points at it, and
          FeeType.term is a read-only property returning term_obj.name. The old
          free-text column is DROPPED — term_id is the single source of truth.

WHY THE COLUMN MUST BE DROPPED (not left in place):
  fee_types.term is NOT NULL with no default. New code inserts fee types with
  only term_id, never the string. While the old column exists, every insert would
  fail with 'NOT NULL constraint failed: fee_types.term' — the exact bug we hit
  before with fee_records.amount_paid_kobo. So we backfill, then drop it.

WHAT THIS SCRIPT DOES (all idempotent):
  1. create_all() — creates the new `terms` table.
  2. ADD COLUMN fee_types.term_id (nullable) if it's missing.
  3. BACKFILL: for each distinct (school_id, term string) still in fee_types,
     get-or-create a Term row and point every matching fee_type at it via term_id.
  4. Ensure each school has exactly one current term (mark the most recent if none).
  5. DROP the legacy fee_types.term column.

IDEMPOTENT: a second run finds the term column already gone (step 3/5 skip) and the
terms already present, so it does nothing.
"""

import logging

from sqlalchemy import text, inspect

from app.database import SessionLocal, engine, Base
from app.models import Term

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("migrate_terms")


def _fee_types_columns() -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("fee_types")}


def _legacy_term_column_exists() -> bool:
    """True if fee_types still has the old free-text `term` column."""
    return "term" in _fee_types_columns()


def _ensure_term_id_column() -> None:
    """Add fee_types.term_id if missing. Cheap metadata-only change on SQLite."""
    if "term_id" in _fee_types_columns():
        logger.info("fee_types.term_id already present.")
        return
    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE fee_types ADD COLUMN term_id INTEGER REFERENCES terms(id)")
        )
    logger.info("Added fee_types.term_id column.")


def _drop_legacy_term_column() -> None:
    """Drop the dead NOT NULL fee_types.term column (SQLite >= 3.35)."""
    if not _legacy_term_column_exists():
        logger.info("fee_types.term already dropped — nothing to do.")
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE fee_types DROP COLUMN term"))
    logger.info("Dropped dead column fee_types.term.")


def migrate():
    # ---- 1. Ensure the terms table + term_id column exist ----
    logger.info("Ensuring schema (new terms table + fee_types.term_id)...")
    Base.metadata.create_all(bind=engine)
    _ensure_term_id_column()

    if not _legacy_term_column_exists():
        logger.info(
            "No legacy fee_types.term column — schema already migrated. "
            "Nothing to backfill."
        )
        _ensure_current_terms()
        return

    db = SessionLocal()
    try:
        # ---- 2. Read the OLD (school_id, term) pairs via raw SQL ----
        # The ORM no longer maps the `term` column, so query it directly.
        rows = db.execute(
            text("SELECT id, school_id, term FROM fee_types")
        ).fetchall()

        # ---- 3. Get-or-create a Term per (school_id, name), then link rows ----
        term_cache: dict[tuple[int, str], int] = {}
        created_terms = 0
        linked = 0
        for fee_type_id, school_id, term_name in rows:
            name = (term_name or "").strip() or "Unspecified Term"
            key = (school_id, name)
            term_id = term_cache.get(key)
            if term_id is None:
                term = (
                    db.query(Term)
                    .filter(Term.school_id == school_id, Term.name == name)
                    .first()
                )
                if not term:
                    term = Term(school_id=school_id, name=name)
                    db.add(term)
                    db.flush()
                    created_terms += 1
                term_id = term.id
                term_cache[key] = term_id

            db.execute(
                text("UPDATE fee_types SET term_id = :tid WHERE id = :fid"),
                {"tid": term_id, "fid": fee_type_id},
            )
            linked += 1

        db.commit()
        logger.info(
            f"Backfill complete: {created_terms} term(s) created, "
            f"{linked} fee type(s) linked."
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        db.close()

    # ---- 4. Ensure each school has a current term ----
    _ensure_current_terms()

    # ---- 5. Drop the dead legacy column ----
    _drop_legacy_term_column()


def _ensure_current_terms() -> None:
    """
    Guarantee each school has exactly one current term. Where none is marked
    current (e.g. right after backfill), pick the most recently created term as a
    sensible default; the admin can change it from the Terms screen.
    """
    db = SessionLocal()
    try:
        school_ids = [sid for (sid,) in db.query(Term.school_id).distinct().all()]
        fixed = 0
        for sid in school_ids:
            current = (
                db.query(Term)
                .filter(Term.school_id == sid, Term.is_current == True)  # noqa: E712
                .count()
            )
            if current >= 1:
                continue
            latest = (
                db.query(Term)
                .filter(Term.school_id == sid)
                .order_by(Term.created_at.desc())
                .first()
            )
            if latest:
                latest.is_current = True
                fixed += 1
        if fixed:
            db.commit()
            logger.info(f"Marked a current term for {fixed} school(s).")
        else:
            logger.info("Current-term flag already set where terms exist.")
    except Exception:
        db.rollback()
        logger.exception("Failed to ensure current terms.")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
