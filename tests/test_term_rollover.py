"""
Task 6 — term rollover: preserve prior term, carry unpaid balances, idempotent.
"""

from app.models import Term, FeeType, FeeRecord
from app.services.payment_service import record_payment
from app.services.term_service import rollover_term, ARREARS_CATEGORY_NAME

# from_term is the `term` fixture's name (see conftest). to_term is a brand-new
# term string that rollover get-or-creates as a real Term row.
TO_TERM = "Second Term 2025/2026"


def _t2_records(db, student_id):
    """Fee records for a student in the TO_TERM, resolved via the Term row."""
    return (
        db.query(FeeRecord)
        .join(FeeRecord.fee_type)
        .join(FeeType.term_obj)
        .filter(FeeRecord.student_id == student_id, Term.name == TO_TERM)
        .all()
    )


def test_rollover_clones_catalog_and_creates_records(db, school, term, student, fee_record):
    summary = rollover_term(db, school.id, term.name, TO_TERM)

    assert summary["fee_types_cloned"] == 1
    assert summary["records_created"] >= 1
    # A new fee type exists in the target term with the same amount.
    new_ft = (
        db.query(FeeType)
        .join(FeeType.term_obj)
        .filter(Term.name == TO_TERM, FeeType.section == "Primary")
        .first()
    )
    assert new_ft is not None
    assert new_ft.amount_kobo == 7_500_000
    # The to_term was created as a real Term row.
    assert db.query(Term).filter(Term.school_id == school.id, Term.name == TO_TERM).count() == 1


def test_rollover_never_touches_prior_term(db, school, term, student, fee_record):
    # Pay part of the old-term fee.
    record_payment(
        db=db, fee_record_id=fee_record.id, amount_kobo=5_000_000,
        method="cash", send_confirmation=False,
    )
    rollover_term(db, school.id, term.name, TO_TERM)
    db.refresh(fee_record)

    # The prior-term record is unchanged: same total, same payments.
    assert fee_record.fee_type.term == term.name
    assert fee_record.total_fees_kobo == 7_500_000
    assert fee_record.amount_paid_kobo == 5_000_000


def test_unpaid_balance_carried_as_arrears(db, school, term, student, fee_record):
    # ₦50,000 paid of ₦75,000 → ₦25,000 should carry forward.
    record_payment(
        db=db, fee_record_id=fee_record.id, amount_kobo=5_000_000,
        method="cash", send_confirmation=False,
    )
    summary = rollover_term(db, school.id, term.name, TO_TERM, carry_forward=True)

    assert summary["arrears_carried"] == 1
    assert summary["arrears_total_kobo"] == 2_500_000

    arrears = [
        r for r in _t2_records(db, student.id)
        if r.fee_type.name == ARREARS_CATEGORY_NAME
    ]
    assert len(arrears) == 1
    assert arrears[0].total_fees_kobo == 2_500_000


def test_no_carry_forward_when_disabled(db, school, term, student, fee_record):
    record_payment(
        db=db, fee_record_id=fee_record.id, amount_kobo=5_000_000,
        method="cash", send_confirmation=False,
    )
    summary = rollover_term(db, school.id, term.name, TO_TERM, carry_forward=False)
    assert summary["arrears_carried"] == 0


def test_fully_paid_carries_nothing(db, school, term, student, fee_record):
    record_payment(
        db=db, fee_record_id=fee_record.id, amount_kobo=7_500_000,
        method="cash", send_confirmation=False,
    )
    summary = rollover_term(db, school.id, term.name, TO_TERM)
    assert summary["arrears_carried"] == 0


def test_rollover_from_unknown_term_does_nothing(db, school, term, student, fee_record):
    """Rolling from a term that doesn't exist is a safe no-op, not a crash."""
    summary = rollover_term(db, school.id, "No Such Term", TO_TERM)
    assert summary["fee_types_cloned"] == 0
    assert summary["records_created"] == 0


def test_rollover_is_idempotent(db, school, term, student, fee_record):
    # Fully pay the prior-term fee so nothing carries as arrears — this isolates
    # the idempotency behaviour from the (separately tested) arrears carry.
    record_payment(
        db=db, fee_record_id=fee_record.id, amount_kobo=7_500_000,
        method="cash", send_confirmation=False,
    )

    first = rollover_term(db, school.id, term.name, TO_TERM)
    records_after_first = len(_t2_records(db, student.id))
    second = rollover_term(db, school.id, term.name, TO_TERM)

    assert first["records_created"] >= 1
    assert first["arrears_carried"] == 0  # fully paid, nothing to carry
    assert second["records_created"] == 0
    assert second["students_skipped"] >= 1
    # No duplicate records created by the second run.
    assert len(_t2_records(db, student.id)) == records_after_first
