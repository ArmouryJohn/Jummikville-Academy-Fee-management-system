"""Tests for derived balance calculations from payment records."""

from app.models import Payment
from app.services.payment_service import record_payment


def test_no_payments_means_zero_paid(fee_record):
    assert fee_record.amount_paid_kobo == 0
    assert fee_record.balance_kobo == 7_500_000
    assert fee_record.remaining_kobo == 7_500_000
    assert fee_record.overpaid_kobo == 0


def test_amount_paid_is_sum_of_payments(db, fee_record):
    db.add(Payment(fee_record_id=fee_record.id, amount_kobo=3_000_000, method="cash"))
    db.add(Payment(fee_record_id=fee_record.id, amount_kobo=2_000_000, method="pos"))
    db.commit()
    db.refresh(fee_record)

    assert fee_record.amount_paid_kobo == 5_000_000
    assert fee_record.balance_kobo == 2_500_000
    assert fee_record.remaining_kobo == 2_500_000


def test_record_payment_updates_derived_balance(db, fee_record):
    record_payment(
        db=db,
        fee_record_id=fee_record.id,
        amount_kobo=5_000_000,
        method="cash",
        recorded_by="Mrs. Aniefiok",
        send_confirmation=False,
    )
    db.refresh(fee_record)

    assert fee_record.amount_paid_kobo == 5_000_000
    assert fee_record.balance_kobo == 2_500_000
    assert fee_record.status == "partial"


def test_full_payment_marks_paid(db, fee_record):
    record_payment(
        db=db, fee_record_id=fee_record.id, amount_kobo=7_500_000,
        method="cash", send_confirmation=False,
    )
    db.refresh(fee_record)
    assert fee_record.status == "paid"
    assert fee_record.balance_kobo == 0


def test_overpayment_splits_into_overpaid(db, fee_record):
    record_payment(
        db=db, fee_record_id=fee_record.id, amount_kobo=8_000_000,
        method="cash", send_confirmation=False,
    )
    db.refresh(fee_record)
    assert fee_record.status == "overpaid"
    assert fee_record.overpaid_kobo == 500_000
    assert fee_record.remaining_kobo == 0


def test_balance_cannot_drift_from_payments(db, fee_record):
    """The whole point: the balance is always exactly total - sum(payments)."""
    for amt in (1_000_000, 1_500_000, 500_000):
        record_payment(
            db=db, fee_record_id=fee_record.id, amount_kobo=amt,
            method="cash", send_confirmation=False,
        )
    db.refresh(fee_record)
    payments_sum = sum(p.amount_kobo for p in fee_record.payments)
    assert fee_record.amount_paid_kobo == payments_sum == 3_000_000
    assert fee_record.balance_kobo == 7_500_000 - payments_sum
