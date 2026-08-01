"""
Paystack webhook endpoint — the most security-critical route in the system.

HOW THIS WORKS:
1. Parent pays via a Paystack link (which we generated earlier)
2. Paystack's servers send a POST to this endpoint with payment details
3. We verify the signature to prove it's really from Paystack
4. We extract the reference, find the matching fee record, record the payment
5. The payment pipeline sends a WhatsApp confirmation automatically

SECURITY LAYERS:
- HMAC-SHA512 signature verification (rejects forged requests)
- Idempotency check (prevents double-crediting from webhook retries)
- Raw body reading (signature is computed against raw bytes, not parsed JSON)
"""

import json
import logging

from fastapi import APIRouter, Request, HTTPException

from sqlalchemy.orm import Session
from fastapi import Depends

from app.database import get_db
from app.services.paystack import verify_webhook_signature, parse_fee_record_id_from_reference
from app.services.payment_service import record_payment, check_duplicate_reference

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhooks"])


@router.post("/paystack")
async def paystack_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Handle Paystack webhook events.

    Paystack sends various event types, but we only care about 'charge.success'
    (a successful payment). Everything else is acknowledged but ignored.

    Returns 200 OK quickly — Paystack will retry if it doesn't get a fast response.
    """
    # ---- Step 1: Read the RAW body BEFORE parsing ----
    # This is critical: the signature is computed against the exact bytes
    # that Paystack sent. If we parse to JSON first and re-serialize,
    # whitespace might change and the signature won't match.
    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature")

    # ---- Step 2: Verify the signature ----
    if not verify_webhook_signature(raw_body, signature):
        logger.warning(
            f"Webhook signature verification failed. "
            f"IP: {request.client.host if request.client else 'unknown'}"
        )
        raise HTTPException(
            status_code=403,
            detail="Invalid signature"
        )

    # ---- Step 3: Parse the event ----
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("Webhook body is not valid JSON")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("event")
    logger.info(f"Paystack webhook received: event={event_type}")

    # ---- Step 4: Handle charge.success ----
    if event_type == "charge.success":
        data = payload.get("data", {})
        reference = data.get("reference")
        amount_kobo = data.get("amount")

        if not reference or not amount_kobo:
            logger.error(f"Webhook missing reference or amount: {data}")
            return {"status": "error", "message": "Missing reference or amount"}

        # Check for duplicate (idempotency)
        if check_duplicate_reference(db, reference):
            logger.info(f"Duplicate webhook for reference {reference} — skipping")
            return {"status": "ok", "message": "Already processed"}

        # Extract the fee_record_id from our custom reference format
        fee_record_id = parse_fee_record_id_from_reference(reference)
        if fee_record_id is None:
            logger.warning(f"Unknown reference format: {reference}")
            return {"status": "ok", "message": "Unknown reference format"}

        # Record the payment (this also sends WhatsApp confirmation)
        try:
            record_payment(
                db=db,
                fee_record_id=fee_record_id,
                amount_kobo=amount_kobo,
                method="paystack",
                paystack_reference=reference,
            )
            logger.info(
                f"Paystack payment recorded: ref={reference}, "
                f"amount={amount_kobo} kobo, fee_record={fee_record_id}"
            )
        except ValueError as e:
            logger.error(f"Payment processing error: {e}")
            return {"status": "error", "message": str(e)}

    # Always return 200 so Paystack doesn't retry
    return {"status": "ok"}
