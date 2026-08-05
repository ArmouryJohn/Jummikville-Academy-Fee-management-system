"""
Paystack service — webhook signature verification and transaction initialization.

SECURITY:
This is the most security-critical file in the whole system. The webhook endpoint
is publicly accessible (Paystack needs to reach it), so we MUST verify that
incoming webhooks actually came from Paystack, not from an attacker trying to
fake a "payment received" event.

HOW WEBHOOK VERIFICATION WORKS:
1. Paystack signs every webhook with your secret key using HMAC-SHA512
2. The signature is sent in the 'x-paystack-signature' header
3. We compute our own HMAC-SHA512 of the raw request body using our secret key
4. If the two match, the webhook is genuine; if not, it's fake/tampered

WHY HMAC AND NOT JUST CHECKING THE SECRET KEY:
HMAC proves two things at once:
- The sender has the secret key (authentication)
- The request body wasn't modified in transit (integrity)
"""

import hashlib
import hmac
import logging
from datetime import datetime, timezone

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def verify_webhook_signature(raw_body: bytes, signature: str | None) -> bool:
    """
    Verify that a Paystack webhook request is genuine.

    Args:
        raw_body: The raw bytes of the request body (NOT parsed JSON — the raw bytes
                  matter because even a tiny difference in whitespace changes the hash)
        signature: The value of the 'x-paystack-signature' header

    Returns:
        True if the signature is valid, False otherwise

    SECURITY DETAILS:
    - Uses hmac.compare_digest() instead of == to prevent timing attacks
      (an attacker can't figure out the right signature by measuring response times)
    - Uses HMAC-SHA512 because that's what Paystack uses
    """
    if not signature:
        logger.warning("Webhook received with no signature header")
        return False

    # Compute what the signature SHOULD be
    expected_signature = hmac.new(
        key=settings.paystack_secret_key.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha512,
    ).hexdigest()

    # Timing-safe comparison
    is_valid = hmac.compare_digest(expected_signature, signature)

    if not is_valid:
        logger.warning("Webhook signature verification FAILED — possible forgery attempt")

    return is_valid


async def initialize_transaction(
    email: str,
    amount_kobo: int,
    reference: str,
    metadata: dict | None = None,
    callback_url: str | None = None,
) -> dict:
    """
    Initialize a Paystack transaction to generate a payment link.

    Args:
        email: Customer's email (required by Paystack)
        amount_kobo: Amount in kobo (₦5,000 = 500000)
        reference: Our custom reference string (encodes fee_record_id for webhook lookup)
        metadata: Extra data to attach to the transaction (e.g., student name)
        callback_url: URL to redirect to after payment (optional)

    Returns:
        Paystack API response dict containing:
        - authorization_url: The payment link to send to the parent
        - access_code: Paystack's internal code
        - reference: The reference we provided

    Raises:
        httpx.HTTPStatusError: If Paystack returns a non-200 response
    """
    # Check if using placeholder credentials
    if "placeholder" in settings.paystack_secret_key.lower():
        logger.warning(f"Using placeholder Paystack key — returning local mock checkout link for ref={reference}")
        return {
            "authorization_url": f"/api/v1/payments/mock-checkout-page/{reference}?amount={amount_kobo}",
            "access_code": f"demo_access_code_{reference}",
            "reference": reference,
        }

    url = "https://api.paystack.co/transaction/initialize"
    headers = {
        "Authorization": f"Bearer {settings.paystack_secret_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "email": email,
        "amount": amount_kobo,
        "reference": reference,
        "currency": "NGN",
    }

    if metadata:
        payload["metadata"] = metadata
    if callback_url:
        payload["callback_url"] = callback_url

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=30.0)
            response.raise_for_status()
            data = response.json()

        if not data.get("status"):
            logger.error(f"Paystack initialize failed: {data.get('message')}")
            raise ValueError(f"Paystack error: {data.get('message')}")

        logger.info(f"Paystack transaction initialized: ref={reference}")
        return data["data"]
    except Exception as e:
        if not settings.is_production:
            logger.warning(f"Paystack API call failed ({e}) — returning local mock checkout link for ref={reference}")
            return {
                "authorization_url": f"/api/v1/payments/mock-checkout-page/{reference}?amount={amount_kobo}",
                "access_code": f"demo_access_code_{reference}",
                "reference": reference,
            }
        raise


async def verify_transaction(reference: str) -> dict:
    """
    Ask Paystack to confirm a transaction by reference (server-to-server).

    The webhook body tells us what Paystack CLAIMS was paid, but the only
    authoritative source is Paystack's own API. Before we credit money we call
    this to re-confirm the transaction succeeded and how much was actually paid —
    so a replayed or tampered body (even one that somehow passed signature check)
    can't credit an amount Paystack never received.

    Args:
        reference: Our transaction reference (e.g. "JMK-42-1706547200")

    Returns:
        The `data` object from Paystack's verify response, which includes
        `status` ('success'/'failed'/...) and `amount` (in kobo).

    Raises:
        httpx.HTTPStatusError: If Paystack returns a non-200 response
        ValueError: If Paystack reports the verify call itself failed
    """
    url = f"https://api.paystack.co/transaction/verify/{reference}"
    headers = {
        "Authorization": f"Bearer {settings.paystack_secret_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, timeout=30.0)
        response.raise_for_status()
        data = response.json()

    if not data.get("status"):
        logger.error(f"Paystack verify failed: {data.get('message')}")
        raise ValueError(f"Paystack verify error: {data.get('message')}")

    logger.info(f"Paystack transaction verified: ref={reference}")
    return data["data"]


def generate_reference(fee_record_id: int) -> str:
    """
    Generate a unique Paystack reference that encodes the fee_record_id.

    Format: JMK-{fee_record_id}-{timestamp}
    Example: JMK-42-1706547200

    WHY THIS FORMAT:
    - JMK prefix identifies it as our transaction (useful in Paystack dashboard)
    - fee_record_id lets us find the right record when the webhook fires
    - Timestamp ensures uniqueness (same student can pay multiple times)
    """
    timestamp = int(datetime.now(timezone.utc).timestamp())
    return f"JMK-{fee_record_id}-{timestamp}"


def parse_fee_record_id_from_reference(reference: str) -> int | None:
    """
    Extract the fee_record_id from a Paystack reference.

    Args:
        reference: e.g. "JMK-42-1706547200"

    Returns:
        The fee_record_id (e.g., 42), or None if the format is unrecognized
    """
    try:
        parts = reference.split("-")
        if len(parts) >= 3 and parts[0] == "JMK":
            return int(parts[1])
    except (ValueError, IndexError):
        pass

    logger.warning(f"Could not parse fee_record_id from reference: {reference}")
    return None
