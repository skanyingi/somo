"""
Phone number normalization for Kenyan numbers.
Keeps every stored/looked-up phone number in a single consistent
E.164-ish format: +254XXXXXXXXX.
"""

import re


def normalize_phone(raw):
    """Return the number as +254XXXXXXXXX, or None if it doesn't look valid."""
    if not raw:
        return None

    phone = re.sub(r"\s+", "", raw.strip())

    if re.fullmatch(r"\+254\d{9}", phone):
        return phone
    if re.fullmatch(r"254\d{9}", phone):
        return "+" + phone
    if re.fullmatch(r"0\d{9}", phone):
        return "+254" + phone[1:]
    if re.fullmatch(r"7\d{8}", phone):
        return "+254" + phone
    if re.fullmatch(r"1\d{8}", phone):
        return "+254" + phone

    return None
