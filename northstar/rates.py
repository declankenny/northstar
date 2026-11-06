"""Exchange rates. Plain functions, no web code. See docs/design/currency/design.md and the design on issue #130.

One rate means 1 unit of a currency = `rate` units of the system currency on the date the rate is for. It is stored as the text
of an exact decimal ("1.0850"), never as a float. An administrator adds a rate and corrects its value. A rate is never deleted,
and its currency and date never change (the database enforces that), so a correction can change what a past date was worth and
nothing else. The conversion itself is in networth.py.
"""

import re
import sqlite3
from datetime import date

from northstar import currencies, db, locales, money, system_properties, writer
from northstar.errors import NotFoundError, ValidationError
from northstar.writer import Operation

MAX_SIGNIFICANT = 12     # digits that are not leading zeros
MAX_DECIMALS = 12
STALE_DAYS = "currency.rate.stale_days"
MAX_WHOLE = 9            # a rate below 1,000,000,000: far beyond any pair of real currencies


def parse_rate(text: str | None, locale=None) -> str:
    """Typed text such as '1.0850' or '1,0850' (read with the person's decimal mark and group mark) as the canonical text of
    the decimal: digits, a point where there are decimals, no group marks and no leading zeros. The digits after the point are
    kept as typed. Refused: nothing, zero, a negative, more than 12 significant digits or 12 decimals, and anything too large."""
    locale = locale or money._US
    decimal, group = locale.decimal_mark, locale.group_mark
    s = (text or "").strip()
    for aliases in money.GROUP_ALIASES:
        if group in aliases:
            s = "".join(group if c in aliases else c for c in s)
    whole_text, point, fraction = s.partition(decimal)
    grouped = re.compile(rf"\d{{1,3}}(?:{re.escape(group)}\d{{3}})+|\d+", re.ASCII)
    if not whole_text or not grouped.fullmatch(whole_text) or (point and not (fraction.isascii() and fraction.isdigit())):
        raise ValidationError(f"Enter a rate like 1{decimal}0850.")
    whole = whole_text.replace(group, "").lstrip("0") or "0"
    if not any(c in "123456789" for c in whole + fraction):
        raise ValidationError("Enter a rate greater than zero.")
    if len(whole) > MAX_WHOLE:
        raise ValidationError("That rate is too large.")
    if len(fraction) > MAX_DECIMALS or len((whole + fraction).lstrip("0")) > MAX_SIGNIFICANT:
        raise ValidationError(f"Use at most {MAX_SIGNIFICANT} significant digits and {MAX_DECIMALS} decimal places.")
    return whole + (f".{fraction}" if fraction else "")


def _day(text: str | None, today: date) -> str:
    try:
        day = date.fromisoformat((text or "").strip())
    except ValueError:
        raise ValidationError("Enter the date the rate is for.") from None
    if day > today:
        raise ValidationError("A rate cannot be dated after today.")
    return day.isoformat()


def _rateable(conn: sqlite3.Connection, code: str) -> sqlite3.Row:
    """The currency, if rates can be entered for it: it is not the system currency, and it is enabled or has accounts."""
    row = conn.execute("SELECT id, code, is_enabled FROM currencies WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise NotFoundError("That currency doesn't exist.")
    system = currencies.system_currency(conn)
    if system is not None and system.id == row["id"]:
        raise ValidationError(f"{code} is the system currency, so it needs no rates.")
    has_accounts = conn.execute("SELECT 1 FROM live_accounts WHERE currency_id = ? LIMIT 1", (row["id"],)).fetchone()
    if not row["is_enabled"] and not has_accounts:
        raise ValidationError(f"Switch on {code} before adding rates.")
    return row


def has_rate(conn: sqlite3.Connection, currency_id: int) -> bool:
    return conn.execute("SELECT 1 FROM exchange_rates WHERE currency_id = ? LIMIT 1", (currency_id,)).fetchone() is not None


def add_rate(op: Operation, code: str, rate_date: str | None, text: str | None, today: date,
             locale_tag: str | None = None) -> int:
    """Add the rate for one date. A date that already has a rate is refused: that rate is corrected, not added again."""
    conn = op.conn
    with db.write_transaction(conn):
        locale = locales.reading_locale(conn, op.actor_id, locale_tag)
        currency = _rateable(conn, code)
        day = _day(rate_date, today)
        rate = parse_rate(text, locale)
        if conn.execute("SELECT 1 FROM exchange_rates WHERE currency_id = ? AND rate_date = ?", (currency["id"], day)).fetchone():
            raise ValidationError(f"A rate for {locales.speaking().date(day)} already exists. Use Correct to change it.")
        return writer.insert(op, "exchange_rates", {
            "currency_id": currency["id"], "rate_date": day, "rate": rate, "source": "manual"})


def correct_rate(op: Operation, code: str, rate_id: int, text: str | None, locale_tag: str | None = None) -> None:
    """Change the value of a rate. Its date and currency stay, and its source becomes manual."""
    conn = op.conn
    with db.write_transaction(conn):
        locale = locales.reading_locale(conn, op.actor_id, locale_tag)
        currency = _rateable(conn, code)
        if conn.execute("SELECT 1 FROM exchange_rates WHERE id = ? AND currency_id = ?", (rate_id, currency["id"])).fetchone() is None:
            raise NotFoundError("That rate no longer exists.")
        writer.update(op, "exchange_rates", rate_id, {"rate": parse_rate(text, locale), "source": "manual"})


def list_rates(conn: sqlite3.Connection, currency_id: int) -> list[dict]:
    """The rates of a currency, newest first. `until` is the date of the next newer rate, or None for the newest: a correction
    changes net worth from the rate's date up to that date."""
    rows = conn.execute(
        "SELECT id, rate_date, rate, source, updated_at FROM exchange_rates WHERE currency_id = ? ORDER BY rate_date DESC",
        (currency_id,)).fetchall()
    return [{"id": row["id"], "date": row["rate_date"], "rate": row["rate"], "source": row["source"],
             "changed": row["updated_at"][:10], "until": rows[i - 1]["rate_date"] if i else None}
            for i, row in enumerate(rows)]


def currency_page(conn: sqlite3.Connection, code: str, today: date) -> dict:
    """What the currency page shows: the currency, whether rates can be added, its rates, and a stale warning when the newest
    rate is older than `currency.rate.stale_days` and the currency has an open account."""
    row = conn.execute("SELECT id, code, name, minor_units, is_enabled, rates_start FROM currencies WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise NotFoundError("That currency doesn't exist.")
    system = currencies.system_currency(conn)
    is_system = system is not None and system.id == row["id"]
    counts = conn.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(is_open), 0) AS open FROM live_accounts WHERE currency_id = ?",
        (row["id"],)).fetchone()
    rates = list_rates(conn, row["id"])
    stale = None
    if rates and counts["open"]:
        days = (today - date.fromisoformat(rates[0]["date"])).days
        threshold = system_properties.get_value(conn, STALE_DAYS)
        if days > threshold:
            stale = {"last_date": rates[0]["date"], "days": days, "threshold": threshold}
    return {
        "code": row["code"], "name": row["name"], "minor_units": row["minor_units"], "is_enabled": bool(row["is_enabled"]),
        "is_system": is_system, "system_code": None if system is None else system.code,
        "rates_start": row["rates_start"], "default_rates_start": system_properties.get_value(conn, currencies.RATES_START_DEFAULT),
        "account_count": counts["total"], "open_account_count": counts["open"],
        "can_add_rates": not is_system and (bool(row["is_enabled"]) or counts["total"] > 0),
        "rates": rates, "stale": stale}
