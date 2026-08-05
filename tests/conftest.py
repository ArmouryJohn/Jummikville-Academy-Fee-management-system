"""
Shared pytest fixtures.

These are REAL unit tests (unlike the legacy top-level test_api.py / test_whatsapp.py
scripts, which hit a live server). Everything here runs against a fresh in-memory
SQLite database per test, so there's no server to start and no data to clean up.

Twilio and Paystack network calls are stubbed via fixtures so nothing leaves the
process.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import School, Student, FeeCategory, Term, FeeType, FeeRecord


@pytest.fixture()
def db():
    """A fresh in-memory SQLite session with all tables created."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def school(db):
    s = School(name="Jummikville Academy", slug="jummikville")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.fixture()
def term(db, school):
    """The school's current term."""
    t = Term(
        school_id=school.id,
        name="First Term 2025/2026",
        is_current=True,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture()
def tuition_type(db, school, term):
    """A ₦75,000 Primary tuition fee type in the current term."""
    cat = FeeCategory(school_id=school.id, name="Tuition Fee")
    db.add(cat)
    db.flush()
    ft = FeeType(
        school_id=school.id,
        category_id=cat.id,
        section="Primary",
        term_id=term.id,
        amount_kobo=7_500_000,
    )
    db.add(ft)
    db.commit()
    db.refresh(ft)
    return ft


@pytest.fixture()
def student(db, school):
    st = Student(
        school_id=school.id,
        student_name="Emmanuel Okon",
        section="Primary",
        class_name="Primary 4",
        parent_name="Mrs. Okon",
        parent_phone="+2348012345678",
        parent_email="okon@example.com",
    )
    db.add(st)
    db.commit()
    db.refresh(st)
    return st


@pytest.fixture()
def fee_record(db, student, tuition_type):
    """A fee record for the student owing ₦75,000, nothing paid yet."""
    r = FeeRecord(
        student_id=student.id,
        fee_type_id=tuition_type.id,
        total_fees_kobo=7_500_000,
        status="unpaid",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """
    Stub out every outbound integration so unit tests never touch the network.
    - Twilio sends become no-ops that return a fake SID.
    - Receipt generation becomes a no-op (fpdf2 may not be installed in CI).
    """
    from app.services import twilio_wa, receipt_service

    for fn in (
        "send_payment_confirmation",
        "send_completion_message",
        "send_overpaid_message",
        "send_fee_reminder",
    ):
        if hasattr(twilio_wa, fn):
            monkeypatch.setattr(twilio_wa, fn, lambda *a, **k: "SM_fake_sid")

    # Stash the REAL generator so the receipt tests can exercise it directly,
    # then stub the module-level name so the payment pipeline is a no-op by default.
    receipt_service._real_generate_receipt = receipt_service.generate_receipt
    monkeypatch.setattr(
        receipt_service, "generate_receipt", lambda payment: "/tmp/fake-receipt.pdf"
    )
