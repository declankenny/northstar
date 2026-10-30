"""Money is integer cents. Text in, text out, no floating point anywhere."""

import re

from northstar.errors import ValidationError

# About $100 billion, in cents. Stops a typo from overflowing the database.
MAX_CENTS = 99_999_999_999_99

_AMOUNT = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)?(?:\.(\d{1,2}))?", re.ASCII)


def parse_cents(text: str | None) -> int:
    """Turn typed text such as '1,234.56', '$25' or '-$25.00' into integer cents."""
    s = (text or "").strip().replace(" ", "")
    negative = s.startswith("-")
    if negative:
        s = s[1:]
    if s.startswith("$"):
        s = s[1:]
    match = _AMOUNT.fullmatch(s)
    if not s or match is None or (match.group(1) is None and match.group(2) is None):
        raise ValidationError("Enter an amount like 1234.56 or -25.00.")
    whole = int((match.group(1) or "0").replace(",", ""))
    cents = whole * 100 + int((match.group(2) or "0").ljust(2, "0"))
    if cents > MAX_CENTS:
        raise ValidationError("That amount is too large.")
    return -cents if negative else cents


def format_cents(cents: int) -> str:
    """For display: $1,234.56 or -$25.00."""
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) // 100:,}.{abs(cents) % 100:02d}"


def cents_to_input(cents: int) -> str:
    """For an input box: 1234.56 or -25.00, with nothing the parser would have to strip."""
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"
