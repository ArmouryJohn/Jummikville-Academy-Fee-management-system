"""
Term management endpoints — the admin-managed list of academic terms.

A term ("First Term 2025/2026") is the spine everything else keys off: fee types,
reports, expenses, and payroll all belong to a term. These endpoints let an admin
create terms, edit their names/dates, and mark exactly one as the CURRENT term
(the default target for new fee types and reports).

The "exactly one current term per school" invariant lives in
term_service.set_current_term — this router never flips is_current by hand.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Term, School, FeeType
from app.schemas.term import TermCreate, TermUpdate, TermResponse
from app.services.term_service import set_current_term

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/terms", tags=["Terms"])


def _to_response(db: Session, term: Term) -> TermResponse:
    """Build a TermResponse, counting the fee types that reference the term."""
    count = db.query(FeeType).filter(FeeType.term_id == term.id).count()
    return TermResponse(
        id=term.id,
        school_id=term.school_id,
        name=term.name,
        start_date=term.start_date,
        end_date=term.end_date,
        is_current=term.is_current,
        created_at=term.created_at,
        fee_type_count=count,
    )


@router.get("", response_model=list[TermResponse])
def list_terms(
    school_id: int = Query(..., description="Filter by school"),
    db: Session = Depends(get_db),
):
    """List a school's terms, newest first, current term flagged."""
    terms = (
        db.query(Term)
        .filter(Term.school_id == school_id)
        .order_by(Term.created_at.desc())
        .all()
    )
    return [_to_response(db, t) for t in terms]


@router.post("", response_model=TermResponse, status_code=201)
def create_term(data: TermCreate, db: Session = Depends(get_db)):
    """
    Create a new term. Name must be unique within the school. If is_current is
    set, it becomes the current term and clears the flag on all others.
    """
    school = db.query(School).filter(School.id == data.school_id).first()
    if not school:
        raise HTTPException(status_code=404, detail="School not found")

    name = data.name.strip()
    if data.start_date and data.end_date and data.end_date < data.start_date:
        raise HTTPException(status_code=400, detail="end_date cannot be before start_date")

    existing = (
        db.query(Term)
        .filter(Term.school_id == data.school_id, Term.name.ilike(name))
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"A term named '{name}' already exists")

    term = Term(
        school_id=data.school_id,
        name=name,
        start_date=data.start_date,
        end_date=data.end_date,
    )
    db.add(term)
    db.flush()  # assign an id so set_current_term can exclude it

    if data.is_current:
        set_current_term(db, term)

    db.commit()
    db.refresh(term)
    logger.info(f"Term created: {term.name} (current={term.is_current})")
    return _to_response(db, term)


@router.patch("/{term_id}", response_model=TermResponse)
def update_term(term_id: int, data: TermUpdate, db: Session = Depends(get_db)):
    """Edit a term's name and/or dates. Does not change is_current."""
    term = db.query(Term).filter(Term.id == term_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")

    if data.name is not None:
        new_name = data.name.strip()
        clash = (
            db.query(Term)
            .filter(
                Term.school_id == term.school_id,
                Term.id != term.id,
                Term.name.ilike(new_name),
            )
            .first()
        )
        if clash:
            raise HTTPException(status_code=409, detail=f"A term named '{new_name}' already exists")
        term.name = new_name

    # Resolve the effective start/end after applying whichever were provided.
    new_start = data.start_date if data.start_date is not None else term.start_date
    new_end = data.end_date if data.end_date is not None else term.end_date
    if new_start and new_end and new_end < new_start:
        raise HTTPException(status_code=400, detail="end_date cannot be before start_date")
    if data.start_date is not None:
        term.start_date = data.start_date
    if data.end_date is not None:
        term.end_date = data.end_date

    db.commit()
    db.refresh(term)
    logger.info(f"Term updated: {term.name}")
    return _to_response(db, term)


@router.post("/{term_id}/set-current", response_model=TermResponse)
def make_current(term_id: int, db: Session = Depends(get_db)):
    """Mark this term as the school's current term (clears the flag on all others)."""
    term = db.query(Term).filter(Term.id == term_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")

    set_current_term(db, term)
    db.commit()
    db.refresh(term)
    logger.info(f"Current term set: {term.name} (school {term.school_id})")
    return _to_response(db, term)


@router.delete("/{term_id}", status_code=200)
def delete_term(term_id: int, db: Session = Depends(get_db)):
    """
    Delete a term — only if no fee type references it, so we never orphan a fee
    type (whose displayed term reads through to this row).
    """
    term = db.query(Term).filter(Term.id == term_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")

    in_use = db.query(FeeType).filter(FeeType.term_id == term_id).count()
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Can't delete '{term.name}' — {in_use} fee type(s) belong to it. "
                "Remove those fee types first."
            ),
        )

    db.delete(term)
    db.commit()
    logger.info(f"Term deleted: id={term_id}")
    return {"deleted": True, "id": term_id}
