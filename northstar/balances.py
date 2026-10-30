"""Entering balances. Plain functions, no web code."""

import re
import sqlite3
from datetime import date

from northstar import accounts, staleness
from northstar.errors import ValidationError
from northstar.money import parse_cents

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)


class EntryErrors(ValidationError):
    """One or more amounts in a batch were bad. by_account maps account id to its message."""

    def __init__(self, message: str, by_account: dict[int, str]):
        super().__init__(message)
        self.by_account = by_account


def parse_date(text: str | None, today: date) -> date:
    """A YYYY-MM-DD calendar date that is not in the future."""
    text = (text or "").strip()
    try:
        if not _ISO_DATE.fullmatch(text):
            raise ValueError
        parsed = date.fromisoformat(text)
    except ValueError:
        raise ValidationError("Enter a valid date.") from None
    if parsed > today:
        raise ValidationError("The date can't be in the future.")
    return parsed


def record_balance(conn: sqlite3.Connection, account_id: int, as_of: date, cents: int,
                   note: str | None = None) -> str:
    """Save one balance. Returns 'added', 'updated' or 'unchanged'. Closed accounts are refused."""
    account = accounts.get_account(conn, account_id)
    if not account["is_open"]:
        raise ValidationError(f"{account['name']} is closed. Reopen it before entering a balance.")
    existing = conn.execute(
        "SELECT id, amount_cents FROM balances WHERE account_id = ? AND as_of_date = ?",
        (account_id, as_of.isoformat()),
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO balances (account_id, as_of_date, amount_cents, note) VALUES (?, ?, ?, ?)",
            (account_id, as_of.isoformat(), cents, note),
        )
        return "added"
    if existing["amount_cents"] == cents:
        return "unchanged"
    conn.execute(
        "UPDATE balances SET amount_cents = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
        "WHERE id = ?",
        (cents, existing["id"]),
    )
    return "updated"


def update_rows(conn: sqlite3.Connection, as_of: date, today: date) -> list[dict]:
    """Every open account with what the Update screen shows: its latest balance, how old that
    is, whether that is stale for its type, and any balance already saved on the chosen date."""
    rows = conn.execute(
        "SELECT a.id, a.name, c.name AS class_name, t.name AS type_name, t.stale_after_days, "
        "  (SELECT b.as_of_date FROM balances b WHERE b.account_id = a.id "
        "     ORDER BY b.as_of_date DESC LIMIT 1) AS last_date, "
        "  (SELECT b.amount_cents FROM balances b WHERE b.account_id = a.id "
        "     ORDER BY b.as_of_date DESC LIMIT 1) AS last_cents, "
        "  (SELECT b.amount_cents FROM balances b WHERE b.account_id = a.id "
        "     AND b.as_of_date = ?) AS existing_cents "
        "FROM accounts a "
        "JOIN account_classes c ON c.id = a.class_id "
        "JOIN account_types t ON t.id = a.type_id "
        "WHERE a.is_open = 1 "
        "ORDER BY a.class_id, t.name COLLATE NOCASE, a.name COLLATE NOCASE",
        (as_of.isoformat(),),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["days_since"] = staleness.days_since(row["last_date"], today)
        item["stale"] = staleness.is_stale(row["last_date"], today, row["stale_after_days"])
        result.append(item)
    return result


def save_update(conn: sqlite3.Connection, date_text: str | None,
                amounts: dict[int, str | None], today: date) -> dict[str, int]:
    """Save one date's amounts for the open accounts, all or nothing.

    Blank amounts are skipped. If any amount is bad, nothing is saved and EntryErrors says which.
    Returns how many balances were added, updated and left unchanged.
    """
    as_of = parse_date(date_text, today)
    open_ids = [r["id"] for r in update_rows(conn, as_of, today)]
    entered: dict[int, int] = {}
    errors: dict[int, str] = {}
    for account_id in open_ids:
        text = (amounts.get(account_id) or "").strip()
        if not text:
            continue
        try:
            entered[account_id] = parse_cents(text)
        except ValidationError as err:
            errors[account_id] = str(err)
    if errors:
        raise EntryErrors("Some amounts need fixing. Nothing was saved.", errors)

    counts = {"added": 0, "updated": 0, "unchanged": 0}
    conn.execute("BEGIN")
    try:
        for account_id, cents in entered.items():
            counts[record_balance(conn, account_id, as_of, cents)] += 1
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return counts
