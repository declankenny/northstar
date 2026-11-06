"""The currency catalog, the system currency and the currency of an account. Plain functions, no web code.

The catalog is the `currencies` table, loaded by a migration from ISO 4217. The system currency is the system property
`system.currency`: a code that is a row of the catalog, chosen once and locked. An account's currency is set when it is
created and never changes. A currency is usable for a new account when it is enabled, and the system currency always is:
saving it enables it. An administrator enables any other currency on its page, with the date its rates start from, and then
adds its rates (see rates.py).
"""

import sqlite3
from dataclasses import dataclass
from datetime import date

from northstar import db, system_properties, writer
from northstar.errors import NotFoundError, ValidationError
from northstar.writer import Operation

SYSTEM_CURRENCY = "system.currency"


@dataclass(frozen=True)
class Currency:
    id: int
    code: str
    name: str
    minor_units: int


def _currency(row: sqlite3.Row | None) -> Currency | None:
    return None if row is None else Currency(row["id"], row["code"], row["name"], row["minor_units"])


def by_code(conn: sqlite3.Connection, code: str | None) -> Currency | None:
    return _currency(conn.execute("SELECT id, code, name, minor_units FROM currencies WHERE code = ?", (code,)).fetchone())


def get(conn: sqlite3.Connection, currency_id: int) -> Currency:
    row = conn.execute("SELECT id, code, name, minor_units FROM currencies WHERE id = ?", (currency_id,)).fetchone()
    if row is None:
        raise ValidationError("Choose a currency from the list.")
    return _currency(row)


def system_currency(conn: sqlite3.Connection) -> Currency | None:
    """The installation's currency, or None while an administrator has not chosen it yet."""
    return by_code(conn, system_properties.get_value(conn, SYSTEM_CURRENCY))


def system_currency_dict(conn: sqlite3.Connection) -> dict | None:
    """The system currency as the API shows it, or None while it is unset."""
    currency = system_currency(conn)
    return None if currency is None else {"code": currency.code, "name": currency.name, "minor_units": currency.minor_units}


def require_system_currency(conn: sqlite3.Connection) -> Currency:
    """The system currency, or a ValidationError that says what to do: no account can be created without it."""
    currency = system_currency(conn)
    if currency is None:
        raise ValidationError(
            "Choose the system currency first. An administrator sets it on the System properties page, "
            "and accounts cannot be created until it is set.")
    return currency


def is_usable(conn: sqlite3.Connection, currency_id: int) -> bool:
    """Whether a new account may use the currency: it is enabled (the system currency always is)."""
    return conn.execute("SELECT 1 FROM currencies WHERE id = ? AND is_enabled = 1", (currency_id,)).fetchone() is not None


def catalog(conn: sqlite3.Connection) -> list[dict]:
    """Every currency, by code, for the picker."""
    return [dict(row) for row in conn.execute("SELECT code, name, minor_units FROM currencies ORDER BY code")]


def list_with_counts(conn: sqlite3.Connection) -> list[dict]:
    """Every currency with its stored `is_enabled` flag and how many accounts use it, open or closed but not deleted, for the
    admin Currencies page. It reads only the catalog and the accounts: it does not know which currency is the system currency."""
    return [
        {"code": row["code"], "name": row["name"], "minor_units": row["minor_units"],
         "is_enabled": bool(row["is_enabled"]), "account_count": row["account_count"]}
        for row in conn.execute(
            "SELECT c.code, c.name, c.minor_units, c.is_enabled, "
            "       (SELECT COUNT(*) FROM live_accounts a WHERE a.currency_id = c.id) AS account_count "
            "FROM currencies c ORDER BY c.code")]


def account_currency(conn: sqlite3.Connection, account_id: int) -> Currency:
    """The currency of an account that is not deleted."""
    row = conn.execute(
        "SELECT c.id, c.code, c.name, c.minor_units FROM live_accounts a JOIN currencies c ON c.id = a.currency_id "
        "WHERE a.id = ?", (account_id,)).fetchone()
    if row is None:
        raise NotFoundError("That account no longer exists.")
    return _currency(row)


RATES_START_DEFAULT = "currency.rate.start.default"


def update_currency(op: Operation, code: str, is_enabled: bool | None, rates_start: str | None, today: date) -> None:
    """Switch a currency on or off and set the date its rates start from, in one write. `None` leaves a field as it is.

    Switching a currency on needs the date, either given or already kept from before. The date is an intent: it says how far
    back rates are wanted, and what is missing is shown, not refused. The system currency is always enabled and has no rates,
    so it can't be switched off and has no start date."""
    conn = op.conn
    with db.write_transaction(conn):
        row = conn.execute("SELECT id, code, is_enabled, rates_start FROM currencies WHERE code = ?", (code,)).fetchone()
        if row is None:
            raise NotFoundError("That currency doesn't exist.")
        system = system_currency(conn)
        changes: dict = {}
        if system is not None and system.id == row["id"]:
            if is_enabled is False:
                raise ValidationError(f"{code} is the system currency, so it can't be switched off.")
            if rates_start is not None:
                raise ValidationError(f"{code} is the system currency, so it needs no rates and has no start date.")
            return
        if rates_start is not None:
            try:
                start = date.fromisoformat(rates_start.strip())
            except ValueError:
                raise ValidationError("Enter the date rates start from.") from None
            if start > today:
                raise ValidationError("Rates cannot start after today.")
            changes["rates_start"] = start.isoformat()
        if is_enabled is not None:
            changes["is_enabled"] = int(is_enabled)
        if changes.get("is_enabled") == 1 and not (changes.get("rates_start") or row["rates_start"]):
            raise ValidationError("Enter the date rates start from.")
        writer.update(op, "currencies", row["id"], changes)
