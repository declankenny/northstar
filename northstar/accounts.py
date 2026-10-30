"""Account rules. Plain functions, no web code."""

import sqlite3
from datetime import date

from northstar import staleness
from northstar.errors import ValidationError

_SELECT = (
    "SELECT a.id, a.name, a.class_id, c.name AS class_name, a.type_id, t.name AS type_name, "
    "       a.is_open, a.notes, "
    "       (SELECT COUNT(*) FROM balances b WHERE b.account_id = a.id) AS balance_count "
    "FROM accounts a "
    "JOIN account_classes c ON c.id = a.class_id "
    "JOIN account_types t ON t.id = a.type_id "
)


def list_accounts(conn: sqlite3.Connection, closed: bool = False) -> list[sqlite3.Row]:
    """Open accounts, or closed ones, grouped by class and type."""
    return conn.execute(
        _SELECT + "WHERE a.is_open = ? ORDER BY a.class_id, t.name COLLATE NOCASE, a.name COLLATE NOCASE",
        (0 if closed else 1,),
    ).fetchall()


def get_account(conn: sqlite3.Connection, account_id: int) -> sqlite3.Row:
    row = conn.execute(_SELECT + "WHERE a.id = ?", (account_id,)).fetchone()
    if row is None:
        raise ValidationError("That account no longer exists.")
    return row


def account_summary(conn: sqlite3.Connection, account_id: int, today: date) -> dict:
    """The account plus what its page shows: balance count, earliest date, latest balance,
    its age in days and whether that is stale for the account's type."""
    summary = dict(get_account(conn, account_id))
    summary["stale_after_days"] = conn.execute(
        "SELECT stale_after_days FROM account_types WHERE id = ?", (summary["type_id"],)
    ).fetchone()[0]
    summary["earliest_date"] = conn.execute(
        "SELECT MIN(as_of_date) FROM balances WHERE account_id = ?", (account_id,)
    ).fetchone()[0]
    latest = conn.execute(
        "SELECT as_of_date, amount_cents FROM balances WHERE account_id = ? "
        "ORDER BY as_of_date DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    summary["last_date"] = latest["as_of_date"] if latest else None
    summary["last_cents"] = latest["amount_cents"] if latest else None
    summary["days_since"] = staleness.days_since(summary["last_date"], today)
    # Closed accounts are never flagged: their last balance is meant to be old.
    summary["stale"] = bool(summary["is_open"]) and staleness.is_stale(
        summary["last_date"], today, summary["stale_after_days"])
    return summary


def balance_history(conn: sqlite3.Connection, account_id: int) -> list[sqlite3.Row]:
    """Every balance of the account, newest date first."""
    return conn.execute(
        "SELECT id, as_of_date, amount_cents, note, source FROM balances "
        "WHERE account_id = ? ORDER BY as_of_date DESC",
        (account_id,),
    ).fetchall()


def get_class_by_slug(conn: sqlite3.Connection, slug: str | None) -> sqlite3.Row:
    """Look a class up by its lowercase name, such as 'asset' or 'liability'."""
    row = conn.execute(
        "SELECT id, name FROM account_classes WHERE lower(name) = ?", ((slug or "").lower(),)
    ).fetchone()
    if row is None:
        raise ValidationError("Choose Asset or Liability.")
    return row


def other_class(conn: sqlite3.Connection, class_id: int) -> sqlite3.Row:
    return conn.execute(
        "SELECT id, name FROM account_classes WHERE id != ?", (class_id,)
    ).fetchone()


def types_for_class(conn: sqlite3.Connection, class_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, name FROM account_types WHERE class_id = ? ORDER BY id", (class_id,)
    ).fetchall()


def _clean_name(name: str | None) -> str:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Name is required.")
    return name


def _clean_notes(notes: str | None) -> str | None:
    return (notes or "").strip() or None


def _check_type(conn: sqlite3.Connection, type_id: int | None, class_id: int) -> int:
    """The type must exist and belong to the class."""
    if type_id is None or not conn.execute(
        "SELECT 1 FROM account_types WHERE id = ? AND class_id = ?", (type_id, class_id)
    ).fetchone():
        raise ValidationError("Choose a type from the list.")
    return type_id


def add_account(conn: sqlite3.Connection, name: str | None, class_id: int,
                type_id: int | None, notes: str | None = None) -> int:
    name = _clean_name(name)
    type_id = _check_type(conn, type_id, class_id)
    return conn.execute(
        "INSERT INTO accounts (name, class_id, type_id, notes) VALUES (?, ?, ?, ?)",
        (name, class_id, type_id, _clean_notes(notes)),
    ).lastrowid


def update_account(conn: sqlite3.Connection, account_id: int, name: str | None,
                   type_id: int | None, notes: str | None = None) -> None:
    """Rename, re-type within the account's own class, and edit notes."""
    account = get_account(conn, account_id)
    name = _clean_name(name)
    type_id = _check_type(conn, type_id, account["class_id"])
    conn.execute(
        "UPDATE accounts SET name = ?, type_id = ?, notes = ? WHERE id = ?",
        (name, type_id, _clean_notes(notes), account_id),
    )


def class_change_impact(conn: sqlite3.Connection, account_id: int) -> dict:
    """What a class change would touch: how many balances, and the earliest date."""
    get_account(conn, account_id)
    count, earliest = conn.execute(
        "SELECT COUNT(*), MIN(as_of_date) FROM balances WHERE account_id = ?", (account_id,)
    ).fetchone()
    return {"balance_count": count, "earliest_date": earliest}


def change_class(conn: sqlite3.Connection, account_id: int, new_type_id: int | None) -> None:
    """Move the account to the class of the chosen type. Class and type change together."""
    account = get_account(conn, account_id)
    row = conn.execute(
        "SELECT class_id FROM account_types WHERE id = ?", (new_type_id,)
    ).fetchone() if new_type_id is not None else None
    if row is None:
        raise ValidationError("Choose a type from the list.")
    if row["class_id"] == account["class_id"]:
        raise ValidationError("Choose a type in the other class.")
    conn.execute(
        "UPDATE accounts SET class_id = ?, type_id = ? WHERE id = ?",
        (row["class_id"], new_type_id, account_id),
    )


def close_account(conn: sqlite3.Connection, account_id: int) -> None:
    """Close an account whose latest balance is zero, or that has no balances."""
    account = get_account(conn, account_id)
    if not account["is_open"]:
        raise ValidationError("That account is already closed.")
    latest = conn.execute(
        "SELECT amount_cents FROM balances WHERE account_id = ? ORDER BY as_of_date DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    if latest is not None and latest["amount_cents"] != 0:
        raise ValidationError(
            f"The latest balance for {account['name']} is not zero. "
            "Enter a final zero balance first, then close the account."
        )
    conn.execute("UPDATE accounts SET is_open = 0 WHERE id = ?", (account_id,))


def reopen_account(conn: sqlite3.Connection, account_id: int) -> None:
    account = get_account(conn, account_id)
    if account["is_open"]:
        raise ValidationError("That account is already open.")
    conn.execute("UPDATE accounts SET is_open = 1 WHERE id = ?", (account_id,))


def delete_account(conn: sqlite3.Connection, account_id: int) -> int:
    """Delete the account and all its balances. Returns how many balances went with it."""
    count = get_account(conn, account_id)["balance_count"]
    conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    return count
