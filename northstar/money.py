"""Money is an integer count of a currency's minor unit (cents for US dollars, whole yen, fils for Kuwaiti dinars). Typed
text in, an integer out, no floating point anywhere.

Typed text is read in the person's locale (see locales.py and docs/design/locale.md): their decimal mark and group mark, and
nothing else. It interprets what is typed with the selected locale and never guesses another one.
"""

import re

from northstar.errors import ValidationError

# About 10^13 minor units, whatever the currency: $100 billion, 100 billion kuwaiti dinars' worth of fils is smaller still.
# Stops a typo from overflowing the database, and stays inside the range JavaScript represents exactly.
MAX_MINOR = 99_999_999_999_99
MAX_CENTS = MAX_MINOR       # the name from before there were other currencies

# Marks that look alike and are read as the same group mark when typed. A group mark in one of these sets also takes the
# others of its set, and nothing else: arbitrary whitespace is never removed and apostrophes are never replaced globally.
GROUP_ALIASES = ({" ", "\u00a0", "\u202f"}, {"'", "\u2019", "\u02bc"})


class _US:
    """US English, for a caller with no locale: the importer's own reading and the tests that predate locales."""
    decimal_mark = "."
    group_mark = ","


def _example(minor_units: int, decimal_mark: str) -> str:
    return "1234" if minor_units == 0 else "1234" + decimal_mark + "5678"[:minor_units]


def parse_amount(text: str | None, minor_units: int, locale=None, dollar_sign: bool = False) -> int:
    """Turn typed text such as '1,234.56', '$25' or '-25.00' into an integer count of minor units, refusing more decimal
    places than the currency has (never rounding). `locale` says which decimal mark and group mark are meant (US English when
    it is None). Group marks are optional and must be well formed: groups of three, none after the decimal mark. A leading
    '$' is accepted only when `dollar_sign` is true."""
    locale = locale or _US
    decimal, group = locale.decimal_mark, locale.group_mark
    s = (text or "").strip()
    negative = s.startswith("-")
    if negative:
        s = s[1:]
    if dollar_sign and s.startswith("$"):
        s = s[1:]
    for aliases in GROUP_ALIASES:                 # look-alikes of the group mark, and only of that mark
        if group in aliases:
            s = "".join(group if c in aliases else c for c in s)
    whole_text, point, fraction = s.partition(decimal)
    grouped = re.compile(rf"\d{{1,3}}(?:{re.escape(group)}\d{{3}})+|\d+", re.ASCII)
    whole_ok = whole_text == "" or grouped.fullmatch(whole_text) is not None
    fraction_ok = not point or (
        minor_units > 0 and 1 <= len(fraction) <= minor_units and fraction.isascii() and fraction.isdigit())
    if not s or not whole_ok or not fraction_ok:
        if minor_units == 0:
            raise ValidationError("Enter a whole amount like 1234 or -25. This currency has no decimal places.")
        other = "," if decimal == "." else "."
        if not whole_ok and other in whole_text:      # the other mark where this locale's grouping does not allow it
            raise ValidationError(f"Use {decimal} for decimals. Enter an amount like {_example(minor_units, decimal)} "
                                  f"or -25{decimal}{'0' * minor_units}.")
        raise ValidationError(f"Enter an amount like {_example(minor_units, decimal)} or -25{decimal}{'0' * minor_units}.")
    whole = int(whole_text.replace(group, "") or "0")
    amount = whole * 10**minor_units + (int(fraction.ljust(minor_units, "0")) if fraction else 0)
    if amount > MAX_MINOR:
        raise ValidationError("That amount is too large.")
    return -amount if negative else amount


def parse_cents(text: str | None) -> int:
    """US dollars, in cents, read as US English: the importer's reading of an amount until it learns an account's currency."""
    return parse_amount(text, 2, None, dollar_sign=True)


def format_plain(amount: int, minor_units: int) -> str:
    """An integer count of minor units as a plain decimal such as 1234.56, -80 or 1.234, with no symbol and no thousands
    separators. This is the canonical, locale-independent form used by the export."""
    sign = "-" if amount < 0 else ""
    whole, rest = divmod(abs(amount), 10**minor_units)
    return f"{sign}{whole}" + (f".{rest:0{minor_units}d}" if minor_units else "")
