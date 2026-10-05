"""Tests for manual payment recording, audit trail logging, and idempotency."""

import pytest

from app.models import User, Payment, ActivityLog
from app.services.payment_service import record_payment


@pytest.fixture()
def admin(db, school):
    u = User(
        school_id=school.id,
        email="admin@jummikville.com",
        hashed_password="x",
        role="admin",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_manual_payment_captures_actor_and_method(db, fee_record, admin):
    payment = record_payment(
        db=db,
        fee_record_id=fee_record.id,
        amount_kobo=2_500_000,
        method="bank_transfer",
        recorded_by=admin.email,
        recorded_by_user_id=admin.id,
        note="Paid at the bank",
        send_confirmation=False,
    )

    assert payment.method == "bank_transfer"
    assert payment.recorded_by == admin.email
    assert payment.recorded_by_user_id == admin.id
    assert payment.note == "Paid at the bank"


def test_manual_payment_writes_activity_log(db, fee_record, admin):
    record_payment(
        db=db, fee_record_id=fee_record.id, amount_kobo=1_000_000,
        method="cash", recorded_by=admin.email, recorded_by_user_id=admin.id,
        send_confirmation=False,
    )
    logs = db.query(ActivityLog).filter(ActivityLog.action == "payment_recorded").all()
    assert len(logs) == 1
    assert admin.email in logs[0].description


def test_all_four_manual_methods_accepted(db, fee_record):
    for method in ("cash", "pos", "bank_transfer", "other"):
        p = record_payment(
            db=db, fee_record_id=fee_record.id, amount_kobo=100_000,
            method=method, send_confirmation=False,
        )
        assert p.method == method


def test_duplicate_paystack_reference_is_idempotent(db, fee_record):
    ref = "JMK-1-1706547200"
    first = record_payment(
        db=db, fee_record_id=fee_record.id, amount_kobo=7_500_000,
        method="paystack", paystack_reference=ref, send_confirmation=False,
    )
    # Second call with the same reference must NOT double-credit.
    second = record_payment(
        db=db, fee_record_id=fee_record.id, amount_kobo=7_500_000,
        method="paystack", paystack_reference=ref, send_confirmation=False,
    )
    db.refresh(fee_record)

    assert second.id == first.id
    assert db.query(Payment).filter(Payment.paystack_reference == ref).count() == 1
    assert fee_record.amount_paid_kobo == 7_500_000  # credited once, not twice


def test_invalid_amount_rejected(db, fee_record):
    with pytest.raises(ValueError):
        record_payment(
            db=db, fee_record_id=fee_record.id, amount_kobo=0,
            method="cash", send_confirmation=False,
        )
