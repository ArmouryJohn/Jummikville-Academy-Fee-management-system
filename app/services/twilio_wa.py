"""
Twilio WhatsApp service — sends payment confirmations and fee reminders.

MESSAGE PHILOSOPHY:
These messages go to real Nigerian parents. The tone should be:
- Warm and respectful (not corporate or cold)
- Acknowledging that school fees are a real stretch for many families
- Grateful (not demanding)
- Clear about numbers (amount paid, balance remaining)
- Professional but human

SANDBOX NOTE:
Currently uses Twilio's WhatsApp Sandbox (whatsapp:+14155238886).
When you get a verified WhatsApp Business number, change TWILIO_WHATSAPP_NUMBER
in your .env file. That's it — no code changes needed.

SANDBOX LIMITATION:
The sandbox only delivers messages to numbers that have opted in by
texting "join <keyword>" to the sandbox number. For production,
this restriction goes away.
"""

import logging

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

from app.config import settings
from app.utils.formatting import kobo_to_naira, whatsapp_number

logger = logging.getLogger(__name__)


def _get_twilio_client() -> Client:
    """Create a Twilio client. Separated for easy mocking in tests."""
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


def send_whatsapp_message(to_phone: str, body: str) -> str | None:
    """
    Send a WhatsApp message via Twilio.

    Args:
        to_phone: Recipient's phone number (any Nigerian format — will be normalized)
        body: The message text

    Returns:
        The Twilio message SID if successful, None if failed

    NOTE: In sandbox mode, the recipient must have opted in first.
    """
    try:
        client = _get_twilio_client()
        message = client.messages.create(
            from_=settings.twilio_whatsapp_from,
            to=whatsapp_number(to_phone),
            body=body,
        )
        logger.info(f"WhatsApp sent to {to_phone}: SID={message.sid}")
        return message.sid

    except TwilioRestException as e:
        logger.error(f"Twilio error sending to {to_phone}: {e}")
        return None


def send_payment_confirmation(
    parent_name: str,
    student_name: str,
    parent_phone: str,
    amount_paid_kobo: int,
    fee_name: str,
    fee_term: str,
    total_paid_kobo: int,
    balance_kobo: int,
    school_name: str = "Jummikville Academy",
) -> str | None:
    """
    Send a payment confirmation message via WhatsApp.

    This is called after ANY payment (Paystack, cash, POS, transfer)
    goes through the pipeline successfully.

    Args:
        parent_name: e.g. "Mrs. Okon"
        student_name: e.g. "Emmanuel Okon"
        parent_phone: Parent's phone number
        amount_paid_kobo: Amount of THIS specific payment
        fee_name: e.g. "Tuition"
        fee_term: e.g. "Term 1 2025/2026"
        total_paid_kobo: Total amount paid so far (including this payment)
        balance_kobo: Remaining balance after this payment
        school_name: Name of the school

    Returns:
        Twilio message SID if successful, None if failed
    """
    # Build the balance line — show congratulations if fully paid!
    if balance_kobo <= 0:
        balance_line = "🎉 Fully paid! No remaining balance."
    else:
        balance_line = f"Remaining Balance: {kobo_to_naira(balance_kobo)}"

    message = (
        f"✅ Payment Received — {school_name}\n"
        f"\n"
        f"Dear {parent_name},\n"
        f"\n"
        f"We've received your payment of {kobo_to_naira(amount_paid_kobo)} "
        f"for {fee_name} ({fee_term}) for your child, {student_name}.\n"
        f"\n"
        f"Amount Paid So Far: {kobo_to_naira(total_paid_kobo)}\n"
        f"{balance_line}\n"
        f"\n"
        f"Thank you for your continued support of your child's education. "
        f"God bless you. 🙏\n"
        f"\n"
        f"— {school_name}, Uyo"
    )

    return send_whatsapp_message(parent_phone, message)


def send_completion_message(
    parent_name: str,
    student_name: str,
    parent_phone: str,
    amount_paid_kobo: int,
    fee_name: str,
    fee_term: str,
    total_paid_kobo: int,
    school_name: str = "Jummikville Academy",
) -> str | None:
    """
    Send a celebratory "thank you for completing your child's fees" message.

    Sent when a payment brings a fee record EXACTLY to fully paid (status
    'paid'). This is warmer than the generic confirmation — it marks the fee
    as done and thanks the parent for completing it.
    """
    message = (
        f"🎉 Fees Completed — {school_name}\n"
        f"\n"
        f"Dear {parent_name},\n"
        f"\n"
        f"We've received your payment of {kobo_to_naira(amount_paid_kobo)} "
        f"for {fee_name} ({fee_term}) for your child, {student_name}.\n"
        f"\n"
        f"This completes the fees in full — total paid: "
        f"{kobo_to_naira(total_paid_kobo)}. There's no remaining balance.\n"
        f"\n"
        f"Thank you for completing your child's fees. We're grateful for your "
        f"commitment to {student_name}'s education. God bless you. 🙏\n"
        f"\n"
        f"— {school_name}, Uyo"
    )

    return send_whatsapp_message(parent_phone, message)


def send_overpaid_message(
    parent_name: str,
    student_name: str,
    parent_phone: str,
    amount_paid_kobo: int,
    fee_name: str,
    fee_term: str,
    total_paid_kobo: int,
    overpaid_kobo: int,
    school_name: str = "Jummikville Academy",
) -> str | None:
    """
    Send an overpayment notice: the parent has paid MORE than the fee, and the
    excess will be refunded.

    Sent when a payment pushes a fee record past its total (status 'overpaid').
    Honest and reassuring — we flag the excess and promise to return it.
    """
    message = (
        f"💚 Payment Received — {school_name}\n"
        f"\n"
        f"Dear {parent_name},\n"
        f"\n"
        f"We've received your payment of {kobo_to_naira(amount_paid_kobo)} "
        f"for {fee_name} ({fee_term}) for your child, {student_name}.\n"
        f"\n"
        f"This means the fees are fully paid — and we noticed an overpayment "
        f"of {kobo_to_naira(overpaid_kobo)}. Not to worry: we'll return the "
        f"extra {kobo_to_naira(overpaid_kobo)} to you. Someone from the school "
        f"will reach out to arrange it.\n"
        f"\n"
        f"Thank you for your commitment to {student_name}'s education. "
        f"God bless you. 🙏\n"
        f"\n"
        f"— {school_name}, Uyo"
    )

    return send_whatsapp_message(parent_phone, message)


def send_fee_reminder(
    parent_name: str,
    student_name: str,
    parent_phone: str,
    fee_name: str,
    fee_term: str,
    balance_kobo: int,
    payment_link: str | None = None,
    school_name: str = "Jummikville Academy",
) -> str | None:
    """
    Send a warm, respectful fee reminder via WhatsApp.

    The tone deliberately acknowledges that fees are a real financial stretch
    for many families. We're not debt collectors — we're a school that cares.

    Args:
        parent_name: e.g. "Mrs. Okon"
        student_name: e.g. "Emmanuel Okon"
        parent_phone: Parent's phone number
        fee_name: e.g. "Tuition"
        fee_term: e.g. "Term 1 2025/2026"
        balance_kobo: Outstanding balance
        payment_link: Optional Paystack payment URL
        school_name: Name of the school

    Returns:
        Twilio message SID if successful, None if failed
    """
    # Build the payment link section (only if we have a link)
    payment_section = ""
    if payment_link:
        payment_section = (
            f"\nIf you're able to make a payment, you can use this secure link:\n"
            f"{payment_link}\n"
        )

    message = (
        f"📚 Gentle Reminder — {school_name}\n"
        f"\n"
        f"Dear {parent_name},\n"
        f"\n"
        f"We hope this message finds you well. We understand that school "
        f"fees can be a real stretch for families, and we truly appreciate "
        f"your commitment to {student_name}'s education.\n"
        f"\n"
        f"Your current balance for {fee_name} ({fee_term}) is "
        f"{kobo_to_naira(balance_kobo)}.\n"
        f"{payment_section}\n"
        f"If you have any questions or need to discuss a payment plan, "
        f"please don't hesitate to reach out. We're here to help.\n"
        f"\n"
        f"With warm regards,\n"
        f"{school_name}, Uyo 🏫"
    )

    return send_whatsapp_message(parent_phone, message)
