"""
Database migration script to transition fee types from raw term strings to normalized term records.
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
