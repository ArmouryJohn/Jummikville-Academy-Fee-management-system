"""
Utility functions for formatting and data normalization.

These are small helper functions used across the app to keep
formatting consistent and avoid duplicating logic.
"""

import re


def kobo_to_naira(amount_kobo: int) -> str:
    """
    Convert an amount in kobo to formatted Naira (e.g. 500000 -> ₦5,000.00).
    """
    naira = amount_kobo / 100
    return f"₦{naira:,.2f}"


def normalize_phone(phone: str) -> str:
    """
    Normalize Nigerian phone number to E.164 format (+234...).
    """
    # Remove all spaces, dashes, and parentheses
    phone = re.sub(r"[\s\-\(\)]+", "", phone)

    # Remove leading + for processing
    if phone.startswith("+"):
        phone = phone[1:]

    # If it starts with 234, it's already in international format
    if phone.startswith("234"):
        return f"+{phone}"

    # If it starts with 0 (e.g., 08012345678), replace leading 0 with 234
    if phone.startswith("0"):
        return f"+234{phone[1:]}"

    # If it's just the local number (e.g., 8012345678), add 234
    if len(phone) == 10:
        return f"+234{phone}"

    # Fallback: return with + prefix (might be a non-Nigerian number)
    return f"+{phone}"


def whatsapp_number(phone: str) -> str:
    """
    Format a phone number for Twilio's WhatsApp API.

    Twilio requires the format: whatsapp:+234XXXXXXXXXX

    Examples:
        whatsapp_number("08012345678")    → "whatsapp:+2348012345678"
        whatsapp_number("+2348012345678") → "whatsapp:+2348012345678"
    """
    return f"whatsapp:{normalize_phone(phone)}"


def font_safe_text(text: str | None) -> str:
    """
    Sanitize text for fpdf2 standard fonts (Helvetica/Times/Courier) which require latin-1.
    Replaces common non-latin-1 unicode symbols with ASCII equivalents, then falls back
    to replacing unrepresentable characters safely so PDF generation never raises UnicodeEncodeError.
    """
    if text is None:
        return ""
    text = str(text)
    replacements = {
        "\u20a6": "NGN ",  # ₦
        "\u2018": "'",     # ‘
        "\u2019": "'",     # ’
        "\u201c": '"',     # “
        "\u201d": '"',     # ”
        "\u2013": "-",     # –
        "\u2014": "-",     # —
        "\u2026": "...",   # …
        "\u2022": "*",     # •
        "\u00a0": " ",     # Non-breaking space
    }
    for orig, rep in replacements.items():
        text = text.replace(orig, rep)
    return text.encode("latin-1", errors="replace").decode("latin-1")

