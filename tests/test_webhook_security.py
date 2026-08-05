"""
Task 2 — Paystack webhook security: HMAC signature verification, reference
round-tripping, and the WebhookEvent audit row.
"""

import hashlib
import hmac

import pytest

from app.config import settings
from app.services.paystack import (
    verify_webhook_signature,
    generate_reference,
    parse_fee_record_id_from_reference,
)


@pytest.fixture(autouse=True)
def _known_secret(monkeypatch):
    """Pin a known Paystack secret so we can compute signatures deterministically."""
    monkeypatch.setattr(settings, "paystack_secret_key", "sk_test_known_secret")


def _sign(body: bytes) -> str:
    return hmac.new(
        key=settings.paystack_secret_key.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha512,
    ).hexdigest()


def test_valid_signature_passes():
    body = b'{"event":"charge.success","data":{"reference":"JMK-1-123"}}'
    assert verify_webhook_signature(body, _sign(body)) is True


def test_tampered_body_fails():
    body = b'{"event":"charge.success","data":{"amount":7500000}}'
    sig = _sign(body)
    tampered = b'{"event":"charge.success","data":{"amount":9999999}}'
    assert verify_webhook_signature(tampered, sig) is False


def test_missing_signature_fails():
    assert verify_webhook_signature(b"{}", None) is False


def test_wrong_key_fails():
    body = b'{"event":"charge.success"}'
    bad_sig = hmac.new(b"sk_test_attacker", body, hashlib.sha512).hexdigest()
    assert verify_webhook_signature(body, bad_sig) is False


def test_reference_round_trips_the_fee_record_id():
    ref = generate_reference(42)
    assert ref.startswith("JMK-42-")
    assert parse_fee_record_id_from_reference(ref) == 42


def test_unknown_reference_format_returns_none():
    assert parse_fee_record_id_from_reference("random-ref-123") is None
    assert parse_fee_record_id_from_reference("") is None
