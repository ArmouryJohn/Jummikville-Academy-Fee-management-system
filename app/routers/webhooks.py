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
from app.models import WebhookEvent
from app.services.paystack import (
    verify_webhook_signature,
    parse_fee_record_id_from_reference,
    verify_transaction,
)
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
    # A forged request never gets stored — we reject it before touching the DB,
    # so the webhook_events audit log only ever holds genuinely-signed deliveries.
    if not verify_webhook_signature(raw_body, signature):
        logger.warning(
            f"Webhook signature verification failed. "
            f"IP: {request.client.host if request.client else 'unknown'}"
        )
        raise HTTPException(
            status_code=403,
            detail="Invalid signature"
        )

    # ---- Step 3: Store the raw event (audit log) ----
    # One row per delivery — genuine, duplicate, or unrecognised — created up
    # front so we ALWAYS have a record of what Paystack sent, even if processing
    # below decides to skip it. We fill in processed/verified/error as we go.
    event = WebhookEvent(
        provider="paystack",
        signature=signature,
        raw_body=raw_body.decode("utf-8", errors="replace"),
        verified=True,  # signature already checked above
    )
    db.add(event)

    # ---- Step 4: Parse the event ----
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.error("Webhook body is not valid JSON")
        event.processing_error = "Invalid JSON body"
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("event")
    event.event_type = event_type
    logger.info(f"Paystack webhook received: event={event_type}")

    # ---- Step 5: Handle charge.success ----
    if event_type == "charge.success":
        data = payload.get("data", {})
        reference = data.get("reference")
        claimed_amount_kobo = data.get("amount")
        event.reference = reference

        if not reference or not claimed_amount_kobo:
            logger.error(f"Webhook missing reference or amount: {data}")
            event.processing_error = "Missing reference or amount"
            db.commit()
            return {"status": "error", "message": "Missing reference or amount"}

        # Idempotency: duplicate deliveries never double-credit. We still keep
        # THIS delivery's audit row — we just don't record another payment.
        if check_duplicate_reference(db, reference):
            logger.info(f"Duplicate webhook for reference {reference} — skipping")
            event.processing_error = "Duplicate — already processed"
            db.commit()
            return {"status": "ok", "message": "Already processed"}

        # Extract the fee_record_id from our custom reference format
        fee_record_id = parse_fee_record_id_from_reference(reference)
        if fee_record_id is None:
            logger.warning(f"Unknown reference format: {reference}")
            event.processing_error = "Unknown reference format"
            db.commit()
            return {"status": "ok", "message": "Unknown reference format"}

        # ---- Re-verify with Paystack before crediting ----
        # The signed body can't be forged, but we still confirm the transaction
        # against Paystack's own API — it's the authoritative source of BOTH the
        # success state and the real amount. We credit the verified amount, never
        # the claimed one.
        try:
            verified = await verify_transaction(reference)
        except Exception as e:
            logger.error(f"Paystack verify call failed for {reference}: {e}")
            event.processing_error = f"Verify call failed: {e}"
            db.commit()
            # Return 200 so Paystack retries later; the audit row records the miss.
            return {"status": "error", "message": "Verification failed"}

        if verified.get("status") != "success":
            logger.warning(
                f"Paystack reports {reference} not successful: {verified.get('status')}"
            )
            event.processing_error = f"Not successful per Paystack: {verified.get('status')}"
            db.commit()
            return {"status": "ok", "message": "Transaction not successful"}

        verified_amount_kobo = verified.get("amount")
        if verified_amount_kobo != claimed_amount_kobo:
            # Body and Paystack disagree on the amount — trust Paystack, and flag it.
            logger.warning(
                f"Amount mismatch for {reference}: body={claimed_amount_kobo}, "
                f"verified={verified_amount_kobo} — crediting verified amount"
            )

        # Record the payment (this also generates the receipt + sends WhatsApp)
        try:
            record_payment(
                db=db,
                fee_record_id=fee_record_id,
                amount_kobo=verified_amount_kobo,
                method="paystack",
                paystack_reference=reference,
            )
            event.processed = True
            db.commit()
            logger.info(
                f"Paystack payment recorded: ref={reference}, "
                f"amount={verified_amount_kobo} kobo, fee_record={fee_record_id}"
            )
        except ValueError as e:
            logger.error(f"Payment processing error: {e}")
            event.processing_error = str(e)
            db.commit()
            return {"status": "error", "message": str(e)}
    else:
        # Not an event we act on — recorded for audit, acknowledged, ignored.
        event.processing_error = "Event type not handled"
        db.commit()

    # Always return 200 so Paystack doesn't retry
    return {"status": "ok"}
