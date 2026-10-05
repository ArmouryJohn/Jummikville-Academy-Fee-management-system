"""
Tests for academic term management, active term tracking, and fee type term resolution.
"""

from app.models import Term, FeeType, FeeCategory
from app.services.term_service import (
    get_current_term,
    set_current_term,
    get_or_create_term,
)


def test_set_current_term_is_exclusive(db, school):
    """Making one term current clears is_current on every other term."""
    t1 = Term(school_id=school.id, name="First Term", is_current=True)
    t2 = Term(school_id=school.id, name="Second Term")
    t3 = Term(school_id=school.id, name="Third Term")
    db.add_all([t1, t2, t3])
    db.commit()

    set_current_term(db, t2)
    db.commit()

    currents = db.query(Term).filter(Term.school_id == school.id, Term.is_current == True).all()  # noqa: E712
    assert len(currents) == 1
    assert currents[0].id == t2.id
    assert get_current_term(db, school.id).id == t2.id


def test_set_current_term_scoped_per_school(db):
    """Setting the current term for one school never touches another school's."""
    from app.models import School
    a = School(name="A", slug="a")
    b = School(name="B", slug="b")
    db.add_all([a, b])
    db.commit()

    a_term = Term(school_id=a.id, name="A Term", is_current=True)
    b_term = Term(school_id=b.id, name="B Term", is_current=True)
    db.add_all([a_term, b_term])
    db.commit()

    # Add a second term for A and make it current.
    a_term2 = Term(school_id=a.id, name="A Term 2")
    db.add(a_term2)
    db.commit()
    set_current_term(db, a_term2)
    db.commit()

    # B's current term is untouched.
    db.refresh(b_term)
    assert b_term.is_current is True
    assert get_current_term(db, b.id).id == b_term.id
    # A now has exactly one current, the new one.
    assert get_current_term(db, a.id).id == a_term2.id


def test_get_or_create_term_is_idempotent(db, school):
    """Resolving the same name twice returns the same row, not a duplicate."""
    first = get_or_create_term(db, school.id, "First Term 2025/2026")
    db.commit()
    second = get_or_create_term(db, school.id, "  First Term 2025/2026  ")  # trimmed
    db.commit()

    assert first.id == second.id
    assert (
        db.query(Term)
        .filter(Term.school_id == school.id, Term.name == "First Term 2025/2026")
        .count()
        == 1
    )


def test_fee_type_term_property_reads_through(db, school):
    """FeeType.term returns the linked Term's name (keeps existing callers working)."""
    term = Term(school_id=school.id, name="First Term 2025/2026")
    cat = FeeCategory(school_id=school.id, name="Tuition Fee")
    db.add_all([term, cat])
    db.flush()
    ft = FeeType(
        school_id=school.id, category_id=cat.id, section="Primary",
        term_id=term.id, amount_kobo=7_500_000,
    )
    db.add(ft)
    db.commit()
    db.refresh(ft)

    assert ft.term == "First Term 2025/2026"

    # Renaming the term flows through — one source of truth.
    term.name = "First Term (Renamed)"
    db.commit()
    db.refresh(ft)
    assert ft.term == "First Term (Renamed)"


def test_fee_type_term_property_empty_when_unlinked(db, school):
    """An unlinked fee type reports an empty term rather than raising."""
    cat = FeeCategory(school_id=school.id, name="Tuition Fee")
    db.add(cat)
    db.flush()
    ft = FeeType(
        school_id=school.id, category_id=cat.id, section="Primary",
        term_id=None, amount_kobo=7_500_000,
    )
    db.add(ft)
    db.commit()
    db.refresh(ft)
    assert ft.term == ""
