"""The scrub catches what has a shape and leaves ordinary numbers and words alone."""

import pytest

from imcp.pii import luhn_valid, scrub, scrub_name


@pytest.mark.parametrize("text, expected", [
    ("write to jordan@example.com or ops.team+x@sub.example.co.uk", "write to [email] or [email]"),
    ("call +1 614 555 0100 or (020) 7946 0958", "call [phone] or [phone]"),
    ("IBAN NL91 ABNA 0417 1643 00 and DE89370400440532013000", "IBAN [iban] and [iban]"),
    ("test card 4111 1111 1111 1111 and 5500-0000-0000-0004", "test card [card] and [card]"),
    ("api key AQEyhmfxK4LPaBdEw0m_live_abc123XYZ789qwerty", "api key [key]"),
    ("token sk-live-0123456789abcdefABCDEF", "token [key]"),
])
def test_shaped_data_is_replaced(text, expected):
    assert scrub(text) == expected


@pytest.mark.parametrize("text", [
    "about 1,000,000 transactions a month",
    "order 1234567890123 shipped",  # 13 digits, not Luhn-valid
    "go-live 2026-10-24, terminals 250, stores 1200",
    "merchant account AcmeECOM and store code S-00042",
    "the Terminal API over Wi-Fi with offline processing",
    "PSP reference 8515131751004933",  # 16 digits, not Luhn-valid
])
def test_ordinary_numbers_and_words_are_left_alone(text):
    assert scrub(text) == text


def test_luhn():
    assert luhn_valid("4111111111111111") and not luhn_valid("4111111111111112")


def test_merchant_name():
    assert scrub_name("Acme Pizza wants Capital; ACME PIZZA has 40 stores", "Acme Pizza") == \
        "the merchant wants Capital; the merchant has 40 stores"
    assert scrub_name("AB wants Capital", "AB") == "AB wants Capital"  # too short to replace safely
