"""The currency catalog, the system currency and the currency of an account. Plain functions, no web code.

The catalog is the `currencies` table, loaded by a migration from ISO 4217. The system currency is the system property
`system.currency`: a code that is a row of the catalog, chosen once and locked. An account's currency is set when it is
created and never changes. A currency is usable for a new account when it is the system currency or is enabled. Nothing
enables a currency yet (that arrives with exchange rates), so for now every account is in the system currency.
"""

import sqlite3
from dataclasses import dataclass

from northstar import system_properties
from northstar.errors import NotFoundError, ValidationError

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
    """Whether a new account may use the currency: it is the system currency, or it is enabled."""
    system = system_currency(conn)
    if system is not None and system.id == currency_id:
        return True
    return conn.execute("SELECT 1 FROM currencies WHERE id = ? AND is_enabled = 1", (currency_id,)).fetchone() is not None


def catalog(conn: sqlite3.Connection) -> list[dict]:
    """Every currency, by code, for the picker."""
    return [dict(row) for row in conn.execute("SELECT code, name, minor_units FROM currencies ORDER BY code")]


def account_currency(conn: sqlite3.Connection, account_id: int) -> Currency:
    """The currency of an account that is not deleted."""
    row = conn.execute(
        "SELECT c.id, c.code, c.name, c.minor_units FROM live_accounts a JOIN currencies c ON c.id = a.currency_id "
        "WHERE a.id = ?", (account_id,)).fetchone()
    if row is None:
        raise NotFoundError("That account no longer exists.")
    return _currency(row)
