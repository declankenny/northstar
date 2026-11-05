"""Money is an integer count of a currency's minor unit (cents for US dollars, whole yen, fils for Kuwaiti dinars). Typed
text in, an integer out, no floating point anywhere."""

import re

from northstar.errors import ValidationError

# About 10^13 minor units, whatever the currency: $100 billion, 100 billion kuwaiti dinars' worth of fils is smaller still.
# Stops a typo from overflowing the database, and stays inside the range JavaScript represents exactly.
MAX_MINOR = 99_999_999_999_99
MAX_CENTS = MAX_MINOR       # the name from before there were other currencies

_INTEGER = re.compile(r"\d{1,3}(?:,\d{3})+|\d+", re.ASCII)


def _example(minor_units: int) -> str:
    return "1234" if minor_units == 0 else "1234." + "5678"[:minor_units]


def parse_amount(text: str | None, minor_units: int, dollar_sign: bool = False) -> int:
    """Turn typed text such as '1,234.56', '$25' or '-25.00' into an integer count of minor units, refusing more decimal
    places than the currency has (never rounding). A leading '$' is accepted only when `dollar_sign` is true."""
    s = (text or "").strip().replace(" ", "")
    negative = s.startswith("-")
    if negative:
        s = s[1:]
    if dollar_sign and s.startswith("$"):
        s = s[1:]
    whole_text, point, fraction = s.partition(".")
    whole_ok = whole_text == "" or _INTEGER.fullmatch(whole_text) is not None
    fraction_ok = not point or (
        minor_units > 0 and 1 <= len(fraction) <= minor_units and fraction.isascii() and fraction.isdigit())
    if not s or not whole_ok or not fraction_ok:
        if minor_units == 0:
            raise ValidationError("Enter a whole amount like 1234 or -25. This currency has no decimal places.")
        raise ValidationError(f"Enter an amount like {_example(minor_units)} or -25.{'0' * minor_units}.")
    whole = int(whole_text.replace(",", "") or "0")
    amount = whole * 10**minor_units + (int(fraction.ljust(minor_units, "0")) if fraction else 0)
    if amount > MAX_MINOR:
        raise ValidationError("That amount is too large.")
    return -amount if negative else amount


def parse_cents(text: str | None) -> int:
    """US dollars, in cents: the importer's reading of an amount until it learns an account's currency."""
    return parse_amount(text, 2, dollar_sign=True)


def format_plain(amount: int, minor_units: int) -> str:
    """An integer count of minor units as a plain decimal such as 1234.56, -80 or 1.234, with no symbol and no thousands
    separators."""
    sign = "-" if amount < 0 else ""
    whole, rest = divmod(abs(amount), 10**minor_units)
    return f"{sign}{whole}" + (f".{rest:0{minor_units}d}" if minor_units else "")
