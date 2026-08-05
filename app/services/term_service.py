"""
Term rollover service — start a new term WITHOUT destroying the old one.

WHAT "ROLLOVER" MEANS HERE:
At the end of a term the school opens a new one (e.g. "Term 1 2025/2026" →
"Term 2 2025/2026"). Rollover copies the fee CATALOG forward and gives every
active student fresh fee records for the new term, so staff don't re-enter
everything by hand.

THE LOAD-BEARING RULES (why this service is explicit, not automatic):
1. NOTHING in the old term is ever mutated or deleted. Prior-term FeeTypes and
   FeeRecords — and their payment history — stay exactly as they were. History is
   immutable.
2. Unpaid balances are CARRIED FORWARD as arrears. The paid portion stays with the
   old term (it happened there); only the still-owed remainder follows the student
   into the new term, as one record under an "Outstanding (Prior Term)" fee type so
   it stays visible and collectable.
3. It is IDEMPOTENT and never runs on its own. Running it twice for the same
   (from_term → to_term) does nothing the second time — students that already have
   to_term records are skipped. There is no auto-rollover on a date; a human triggers
   it via POST /api/v1/fees/terms/rollover.
"""

import logging

from sqlalchemy.orm import Session

from app.models import Student, FeeType, FeeRecord, FeeCategory, Term

logger = logging.getLogger(__name__)

# The category that holds carried-forward arrears. Created on demand the first
# time a rollover carries a balance, then reused.
ARREARS_CATEGORY_NAME = "Outstanding (Prior Term)"


# --------------------------------------------------------------------------
# Term registry helpers — one place that owns the "exactly one current term"
# invariant and term lookup/creation, so routers never duplicate it.
# --------------------------------------------------------------------------

def get_current_term(db: Session, school_id: int) -> Term | None:
    """The school's current term, or None if none is marked current yet."""
    return (
        db.query(Term)
        .filter(Term.school_id == school_id, Term.is_current == True)  # noqa: E712
        .first()
    )


def set_current_term(db: Session, term: Term) -> None:
    """
    Make `term` the school's current term, clearing the flag on every other term
    in the same school. Caller commits. This is the single writer of is_current,
    so the "exactly one current term per school" invariant can't be violated.
    """
    (
        db.query(Term)
        .filter(Term.school_id == term.school_id, Term.id != term.id)
        .update({Term.is_current: False}, synchronize_session=False)
    )
    term.is_current = True


def get_or_create_term(db: Session, school_id: int, name: str) -> Term:
    """
    Fetch a term by (school, name), creating it if missing. Used by rollover so a
    brand-new to_term string becomes a real Term row. Does not flip is_current.
    """
    name = name.strip()
    term = (
        db.query(Term)
        .filter(Term.school_id == school_id, Term.name == name)
        .first()
    )
    if not term:
        term = Term(school_id=school_id, name=name)
        db.add(term)
        db.flush()
    return term


def _ensure_arrears_category(db: Session, school_id: int) -> FeeCategory:
    """Fetch (or create) the school's arrears category used for carried balances."""
    cat = (
        db.query(FeeCategory)
        .filter(
            FeeCategory.school_id == school_id,
            FeeCategory.name.ilike(ARREARS_CATEGORY_NAME),
        )
        .first()
    )
    if not cat:
        cat = FeeCategory(school_id=school_id, name=ARREARS_CATEGORY_NAME)
        db.add(cat)
        db.flush()
    return cat


def _ensure_arrears_fee_type(
    db: Session, school_id: int, section: str, to_term_id: int
) -> FeeType:
    """
    Fetch (or create) the arrears FeeType for a section in the new term.

    The FeeType is just a catalog label — the real carried amount lives on each
    student's arrears FeeRecord (total_fees_kobo), since every student carries a
    different balance. amount_kobo is left at 0 on the type.
    """
    cat = _ensure_arrears_category(db, school_id)
    ft = (
        db.query(FeeType)
        .filter(
            FeeType.school_id == school_id,
            FeeType.category_id == cat.id,
            FeeType.section == section,
            FeeType.term_id == to_term_id,
        )
        .first()
    )
    if not ft:
        ft = FeeType(
            school_id=school_id,
            category_id=cat.id,
            section=section,
            term_id=to_term_id,
            amount_kobo=0,
        )
        db.add(ft)
        db.flush()
    return ft


def rollover_term(
    db: Session,
    school_id: int,
    from_term: str,
    to_term: str,
    section: str | None = None,
    carry_forward: bool = True,
) -> dict:
    """
    Roll the fee catalog + student records forward from one term to the next.

    Args:
        db: Database session
        school_id: Which school
        from_term: The term to roll FROM (source catalog + outstanding balances)
        to_term: The new term to create records IN
        section: Optional — restrict the rollover to a single section
        carry_forward: When True, carry each student's unpaid prior-term balance
            into the new term as an arrears record. When False, the new term starts
            clean and prior balances stay only in the old term.

    Returns:
        Summary counts: fee types cloned, records created, students skipped, and
        arrears records carried.
    """
    summary = {
        "from_term": from_term,
        "to_term": to_term,
        "fee_types_cloned": 0,
        "records_created": 0,
        "students_skipped": 0,
        "arrears_carried": 0,
        "arrears_total_kobo": 0,
    }

    # ---- 0. Resolve term strings to real Term rows ----
    # The source term must already exist (you can't roll from a term that has no
    # catalog). The destination is created on demand so "start Term 2" just works.
    from_term_obj = (
        db.query(Term)
        .filter(Term.school_id == school_id, Term.name == from_term.strip())
        .first()
    )
    if not from_term_obj:
        # Nothing to roll from — no matching term. Return the empty summary so the
        # caller sees zero work rather than crashing.
        logger.warning(
            f"Rollover: from_term '{from_term}' not found for school {school_id}; "
            f"nothing to roll."
        )
        return summary
    to_term_obj = get_or_create_term(db, school_id, to_term)

    # ---- 1. Clone the catalog (FeeTypes) into the new term ----
    src_types_query = db.query(FeeType).filter(
        FeeType.school_id == school_id,
        FeeType.term_id == from_term_obj.id,
    )
    if section:
        src_types_query = src_types_query.filter(FeeType.section == section)
    source_fee_types = src_types_query.all()

    # Map each source fee type → its equivalent in the new term (existing or new).
    cloned_by_source: dict[int, FeeType] = {}
    for src in source_fee_types:
        existing = (
            db.query(FeeType)
            .filter(
                FeeType.school_id == school_id,
                FeeType.category_id == src.category_id,
                FeeType.section == src.section,
                FeeType.term_id == to_term_obj.id,
            )
            .first()
        )
        if existing:
            cloned_by_source[src.id] = existing
            continue
        new_ft = FeeType(
            school_id=school_id,
            category_id=src.category_id,
            section=src.section,
            term_id=to_term_obj.id,
            amount_kobo=src.amount_kobo,
        )
        db.add(new_ft)
        db.flush()
        cloned_by_source[src.id] = new_ft
        summary["fee_types_cloned"] += 1

    # ---- 2. Fresh records for each active student ----
    student_query = db.query(Student).filter(
        Student.school_id == school_id,
        Student.is_active == True,  # noqa: E712
    )
    if section:
        student_query = student_query.filter(Student.section == section)
    students = student_query.all()

    for student in students:
        # Idempotency guard: if this student already has ANY record in the new
        # term, we've already rolled them over — skip entirely (no double records,
        # no double arrears).
        already = (
            db.query(FeeRecord)
            .join(FeeRecord.fee_type)
            .filter(
                FeeRecord.student_id == student.id,
                FeeType.term_id == to_term_obj.id,
            )
            .first()
        )
        if already:
            summary["students_skipped"] += 1
            continue

        # New records against the cloned catalog for this student's section.
        for src in source_fee_types:
            if src.section != student.section:
                continue
            new_ft = cloned_by_source[src.id]
            db.add(
                FeeRecord(
                    student_id=student.id,
                    fee_type_id=new_ft.id,
                    total_fees_kobo=new_ft.amount_kobo,
                    status="unpaid",
                )
            )
            summary["records_created"] += 1

        # ---- 3. Carry forward this student's unpaid prior-term balance ----
        if carry_forward:
            prior_records = (
                db.query(FeeRecord)
                .join(FeeRecord.fee_type)
                .filter(
                    FeeRecord.student_id == student.id,
                    FeeType.term_id == from_term_obj.id,
                )
                .all()
            )
            # Only the UNPAID remainder carries — paid money stays in the old term.
            carried_kobo = sum(r.remaining_kobo for r in prior_records)
            if carried_kobo > 0:
                arrears_ft = _ensure_arrears_fee_type(
                    db, school_id, student.section, to_term_obj.id
                )
                db.add(
                    FeeRecord(
                        student_id=student.id,
                        fee_type_id=arrears_ft.id,
                        total_fees_kobo=carried_kobo,
                        status="unpaid",
                    )
                )
                summary["arrears_carried"] += 1
                summary["arrears_total_kobo"] += carried_kobo

    db.commit()

    logger.info(
        f"Term rollover {from_term} -> {to_term} (school {school_id}, "
        f"section={section or 'ALL'}): "
        f"{summary['fee_types_cloned']} fee types cloned, "
        f"{summary['records_created']} records created, "
        f"{summary['students_skipped']} students skipped, "
        f"{summary['arrears_carried']} arrears carried "
        f"({summary['arrears_total_kobo']} kobo)."
    )
    return summary
