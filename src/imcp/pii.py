"""Scrub personal and secret data from text before it leaves the server or enters the graph.

One module, shared by the scope commands (what our model found, on its way back to the IM's chat and
sheet) and the graph loaders (a page's title and description, before they are stored and embedded).
Regular expressions only: they catch what has a shape (email addresses, phone numbers, IBANs, card
numbers, keys and tokens). Names have no shape, so our model is told not to write them, and a
model-based name scrub is a later step for the reference proposals.

Each match is replaced by a bracketed word, so the reader sees that something was there.
"""

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Phone numbers in the usual written forms: +1 614 555 0100, (614) 555-0100, 614.555.0100, +44 20 7946 0958
PHONE = re.compile(r"(?<![\w-])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)\s?|\d{2,4}[\s.-])\d{3,4}[\s.-]\d{3,4}(?![\w-])")
# An IBAN: country code, two check digits, then 11 to 30 letters and digits, possibly in groups of four
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b")
# A run of 13 to 19 digits, with optional spaces or dashes between groups; kept only if Luhn-valid
CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")
# A key or token: 24 or more letters, digits, '_' or '-' in one run, with both letters and digits in it
KEY = re.compile(r"(?<![\w-])(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[A-Za-z0-9_-]{24,}(?![\w-])")


def luhn_valid(digits: str) -> bool:
    total, double = 0, False
    for ch in reversed(digits):
        n = int(ch)
        if double:
            n = n * 2 - 9 if n > 4 else n * 2
        total, double = total + n, not double
    return total % 10 == 0


def _card(match: re.Match) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return "[card]" if luhn_valid(digits) else match.group(0)


def scrub(text: str) -> str:
    """Email addresses, IBANs, card numbers, keys and phone numbers replaced by bracketed words."""
    text = EMAIL.sub("[email]", text)
    text = IBAN.sub("[iban]", text)
    text = CARD.sub(_card, text)
    text = KEY.sub("[key]", text)
    return PHONE.sub("[phone]", text)


def scrub_name(text: str, name: str | None) -> str:
    """Replaces the merchant's name with 'the merchant'. Names shorter than 3 characters are left alone."""
    if name and len(name.strip()) >= 3:
        text = re.sub(re.escape(name.strip()), "the merchant", text, flags=re.IGNORECASE)
    return text
