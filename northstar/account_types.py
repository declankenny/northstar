"""Account type rules. Plain functions, no web code."""

import sqlite3

from northstar.errors import ValidationError


def list_types(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """All account types with their class and the number of accounts using each."""
    return conn.execute(
        "SELECT t.id, t.name, t.class_id, c.name AS class_name, t.stale_after_days, "
        "       (SELECT COUNT(*) FROM accounts a WHERE a.type_id = t.id) AS account_count "
        "FROM account_types t JOIN account_classes c ON c.id = t.class_id "
        "ORDER BY t.class_id, t.id"
    ).fetchall()


def list_classes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT id, name FROM account_classes ORDER BY id").fetchall()


def get_type(conn: sqlite3.Connection, type_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, name, class_id, stale_after_days FROM account_types WHERE id = ?",
        (type_id,),
    ).fetchone()
    if row is None:
        raise ValidationError("That account type no longer exists.")
    return row


def count_accounts(conn: sqlite3.Connection, type_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM accounts WHERE type_id = ?", (type_id,)).fetchone()[0]


def _clean_name(conn: sqlite3.Connection, name: str | None, exclude_id: int | None = None) -> str:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Name is required.")
    # The name column ignores case when comparing, so this also catches "checking" vs "Checking".
    if conn.execute(
        "SELECT 1 FROM account_types WHERE name = ? AND id IS NOT ?", (name, exclude_id)
    ).fetchone():
        raise ValidationError(f"An account type named \"{name}\" already exists.")
    return name


def _clean_days(value: int | str | None) -> int:
    try:
        days = int(str(value).strip())
    except ValueError:
        days = 0
    if days < 1:
        raise ValidationError("Stale after days must be a whole number of at least 1.")
    return days


def _check_class(conn: sqlite3.Connection, class_id: int | None) -> int:
    if class_id is None or not conn.execute(
        "SELECT 1 FROM account_classes WHERE id = ?", (class_id,)
    ).fetchone():
        raise ValidationError("Choose Asset or Liability.")
    return class_id


def add_type(conn: sqlite3.Connection, name: str | None, class_id: int | None,
             stale_after_days: int | str | None) -> int:
    name = _clean_name(conn, name)
    class_id = _check_class(conn, class_id)
    days = _clean_days(stale_after_days)
    return conn.execute(
        "INSERT INTO account_types (name, class_id, stale_after_days) VALUES (?, ?, ?)",
        (name, class_id, days),
    ).lastrowid


def update_type(conn: sqlite3.Connection, type_id: int, name: str | None,
                stale_after_days: int | str | None, class_id: int | None = None) -> None:
    """Rename a type and change its stale days. The class changes only while no account uses it."""
    current = get_type(conn, type_id)
    name = _clean_name(conn, name, exclude_id=type_id)
    days = _clean_days(stale_after_days)
    new_class = current["class_id"] if class_id is None else _check_class(conn, class_id)
    if new_class != current["class_id"] and count_accounts(conn, type_id):
        raise ValidationError("The class can't change while accounts use this type.")
    conn.execute(
        "UPDATE account_types SET name = ?, class_id = ?, stale_after_days = ? WHERE id = ?",
        (name, new_class, days, type_id),
    )


def delete_type(conn: sqlite3.Connection, type_id: int) -> None:
    """Delete a type that no account uses."""
    get_type(conn, type_id)
    in_use = count_accounts(conn, type_id)
    if in_use:
        noun = "account uses" if in_use == 1 else "accounts use"
        raise ValidationError(f"{in_use} {noun} this type. Change their type first.")
    conn.execute("DELETE FROM account_types WHERE id = ?", (type_id,))
