"""
Paystack integration service for transaction initialization and webhook verification.
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
    Validate Paystack HMAC-SHA512 webhook signature against the raw payload.
    """
    if not signature:
        logger.warning("Webhook received with no signature header")
        return False

    expected_signature = hmac.new(
        key=settings.paystack_secret_key.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha512,
    ).hexdigest()

    is_valid = hmac.compare_digest(expected_signature, signature)

    if not is_valid:
        logger.warning("Webhook signature verification failed")

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
    Verify transaction status directly with Paystack API.
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
    Generate transaction reference containing the fee record id and timestamp.
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
