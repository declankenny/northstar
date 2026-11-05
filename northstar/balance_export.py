"""Exporting one account's balances as a CSV file. Plain functions, no web code.

The file is the four columns below, one row per balance, oldest first. It is written so that importing it back into the
same account reads as all unchanged (see csvparse's header names): dates as YYYY-MM-DD and amounts as plain decimals.
"""

import csv
import io
import re
import sqlite3
from datetime import date

from northstar import accounts, currencies
from northstar.money import format_plain

HEADER = ["Account ID", "Account Name", "Balance Date", "Balance Amount"]


def format_cents(cents: int, minor_units: int = 2) -> str:
    """An amount as a plain decimal in the account's own precision, such as 1234.56, -80.00, 1235 or 1.235, with no symbol and
    no thousands separators."""
    return format_plain(cents, minor_units)


def export_csv(conn: sqlite3.Connection, account_id: int) -> str:
    """The account's balances as CSV text. An unknown or deleted account is a NotFoundError."""
    account = accounts.get_account(conn, account_id)
    minor_units = currencies.account_currency(conn, account_id).minor_units
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(HEADER)
    for row in conn.execute(
        "SELECT as_of_date, amount_cents FROM live_balances WHERE account_id = ? ORDER BY as_of_date", (account_id,)
    ):
        writer.writerow([account["id"], account["name"], row["as_of_date"], format_cents(row["amount_cents"], minor_units)])
    return out.getvalue()


def file_name(name: str, today: date) -> str:
    """northstar-balances-<account name>-<date>.csv, with the name cut down to letters, digits and hyphens."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")
    return "-".join(part for part in ("northstar-balances", slug, today.isoformat()) if part) + ".csv"
