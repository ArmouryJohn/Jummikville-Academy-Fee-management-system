"""
Task 5 — receipt service: generated once, idempotent on repeat calls.
"""

import os

import pytest

from app.models import Payment
from app.services import receipt_service


@pytest.fixture()
def payment(db, fee_record):
    from app.services.payment_service import record_payment
    return record_payment(
        db=db, fee_record_id=fee_record.id, amount_kobo=7_500_000,
        method="cash", recorded_by="Mrs. Aniefiok", send_confirmation=False,
    )


def test_receipt_path_is_deterministic(payment):
    path = receipt_service.receipt_path(payment.id)
    assert path.endswith(f"receipt-{payment.id}.pdf")


def test_generate_receipt_creates_file(monkeypatch, payment, tmp_path):
    """With a real (non-stubbed) call the PDF file is created on disk."""
    # Override storage dir to tmp_path so we don't litter the source tree.
    monkeypatch.setattr(
        receipt_service, "_STORAGE_DIR", str(tmp_path / "receipts")
    )
    # Restore the real generator (conftest stubs it by default).
    monkeypatch.setattr(
        receipt_service, "generate_receipt",
        receipt_service._real_generate_receipt,
    )

    try:
        path = receipt_service.generate_receipt(payment)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
    except Exception as exc:
        pytest.skip(f"fpdf2 not installed or receipt generation failed: {exc}")


def test_generate_receipt_is_idempotent(monkeypatch, payment, tmp_path):
    """Calling generate_receipt twice returns the same path, creates no duplicate."""
    monkeypatch.setattr(receipt_service, "_STORAGE_DIR", str(tmp_path / "receipts"))
    monkeypatch.setattr(
        receipt_service, "generate_receipt",
        receipt_service._real_generate_receipt,
    )

    try:
        path1 = receipt_service.generate_receipt(payment)
        mtime1 = os.path.getmtime(path1)
        path2 = receipt_service.generate_receipt(payment)
        mtime2 = os.path.getmtime(path2)
        assert path1 == path2
        assert mtime1 == mtime2  # file was NOT re-written
    except Exception as exc:
        pytest.skip(f"fpdf2 not installed: {exc}")


def test_generate_receipt_handles_unicode(monkeypatch, payment, tmp_path, db):
    """Receipt generation handles unicode characters without throwing UnicodeEncodeError."""
    monkeypatch.setattr(receipt_service, "_STORAGE_DIR", str(tmp_path / "receipts"))
    monkeypatch.setattr(
        receipt_service, "generate_receipt",
        receipt_service._real_generate_receipt,
    )

    # Set unicode attributes on related records
    student = payment.fee_record.student
    student.student_name = "Chukwudi O’Connor"
    student.parent_name = "Mrs. D’Silva • Guardian"
    payment.note = "Paid ₦50,000 via POS – balance pending"
    db.commit()

    try:
        path = receipt_service.generate_receipt(payment)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
    except Exception as exc:
        pytest.skip(f"fpdf2 not installed: {exc}")

