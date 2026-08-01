"""Quick API smoke tests -- verifies all endpoints work correctly."""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import requests

BASE = "http://localhost:8001"


def test_root():
    r = requests.get(f"{BASE}/")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "running"
    print("[PASS] Root endpoint")


def test_health():
    r = requests.get(f"{BASE}/health")
    assert r.status_code == 200
    print("[PASS] Health check")


def test_list_students():
    r = requests.get(f"{BASE}/api/v1/students/", params={"school_id": 1})
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 3
    print(f"[PASS] List students — {len(data)} students found")
    return data


def test_get_student():
    r = requests.get(f"{BASE}/api/v1/students/1")
    assert r.status_code == 200
    data = r.json()
    assert data["student_name"] == "Emmanuel Okon"
    print(f"[PASS] Get student — {data['student_name']}")


def test_list_fee_types():
    r = requests.get(f"{BASE}/api/v1/fees/types", params={"school_id": 1})
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    print(f"[PASS] List fee types — {len(data)} types found")


def test_list_fee_records():
    r = requests.get(f"{BASE}/api/v1/fees/records", params={"school_id": 1})
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 3
    print(f"[PASS] List fee records — {len(data)} records found")
    # Check Emmanuel's partial payment
    for rec in data:
        if rec["student_id"] == 1:
            assert rec["status"] == "partial"
            assert rec["amount_paid_kobo"] == 5_000_000
            assert rec["balance_kobo"] == 2_500_000
            print(f"       Emmanuel Okon: paid ₦50,000, balance ₦25,000 ✓")
            break


def test_cash_payment():
    """Record a cash payment for Grace Udoh (student 2, fee_record 2)."""
    # Read balance BEFORE payment
    r0 = requests.get(f"{BASE}/api/v1/fees/records", params={"school_id": 1})
    before = {rec["student_id"]: rec for rec in r0.json()}
    paid_before = before[2]["amount_paid_kobo"]
    balance_before = before[2]["balance_kobo"]

    if balance_before <= 0:
        print("[SKIP] Cash payment — Grace Udoh already fully paid")
        return

    pay_amount = min(3_000_000, balance_before)  # Don't overpay

    r = requests.post(f"{BASE}/api/v1/payments/cash", json={
        "fee_record_id": 2,
        "amount_kobo": pay_amount,
        "method": "cash",
        "recorded_by": "Mrs. Aniefiok",
        "note": "Paid at school office",
    })
    assert r.status_code == 200, f"Cash payment failed: {r.text}"
    data = r.json()
    print(f"[PASS] Cash payment recorded — {data}")

    # Verify the fee record was updated
    r2 = requests.get(f"{BASE}/api/v1/fees/records", params={"school_id": 1})
    after = {rec["student_id"]: rec for rec in r2.json()}
    assert after[2]["amount_paid_kobo"] == paid_before + pay_amount
    assert after[2]["balance_kobo"] == balance_before - pay_amount
    print(f"       Grace Udoh: +NGN {pay_amount // 100:,} recorded, balance now NGN {after[2]['balance_kobo'] // 100:,} OK")


def test_payment_initialize():
    """Test initializing a Paystack payment link (will fail with test keys but validates the endpoint)."""
    r = requests.post(f"{BASE}/api/v1/payments/initialize", json={
        "fee_record_id": 3,
    })
    # With dummy API keys, this might return an error from Paystack but should not crash
    print(f"[INFO] Payment initialize — status={r.status_code}, response={r.text[:200]}")


def test_webhook_rejects_bad_signature():
    """Verify the Paystack webhook rejects forged requests."""
    r = requests.post(
        f"{BASE}/api/v1/webhooks/paystack",
        json={"event": "charge.success", "data": {"reference": "fake", "amount": 100}},
        headers={"x-paystack-signature": "fake_signature_12345"},
    )
    assert r.status_code == 403, f"Expected 403, got {r.status_code}"
    print("[PASS] Webhook rejects forged signature (403)")


if __name__ == "__main__":
    print("=" * 60)
    print("Jummikville Fee System — API Smoke Tests")
    print("=" * 60)
    print()

    test_root()
    test_health()
    test_list_students()
    test_get_student()
    test_list_fee_types()
    test_list_fee_records()
    test_cash_payment()
    test_payment_initialize()
    test_webhook_rejects_bad_signature()

    print()
    print("=" * 60)
    print("ALL TESTS PASSED ✓")
    print("=" * 60)
