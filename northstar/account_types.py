"""Account type rules. Plain functions, no web code."""

import sqlite3

from northstar import locales, system_properties, writer
from northstar.errors import NotFoundError, ValidationError
from northstar.writer import Operation


STALE_DAYS_PROPERTY = "system.balance.stale_days"   # the system property that says how many stale-after days a new type starts with


def default_stale_after_days(conn: sqlite3.Connection) -> int:
    """What the Add type form starts the stale-after days at: the system's setting, not a number in the code."""
    return system_properties.get_value(conn, STALE_DAYS_PROPERTY)


def list_types(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """All account types with their class and the number of accounts using each, and how many deleted accounts still do."""
    return conn.execute(
        "SELECT t.id, t.name, t.class_id, c.name AS class_name, t.stale_after_days, "
        "       (SELECT COUNT(*) FROM live_accounts a WHERE a.type_id = t.id) AS account_count, "
        "       (SELECT COUNT(*) FROM accounts a WHERE a.type_id = t.id AND a.deleted = 1) AS deleted_account_count "
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
        raise NotFoundError("That account type no longer exists.")
    return row


def count_accounts(conn: sqlite3.Connection, type_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM live_accounts WHERE type_id = ?", (type_id,)).fetchone()[0]


def count_deleted_accounts(conn: sqlite3.Connection, type_id: int) -> int:
    """Deleted accounts keep their type until they can be restored, and the database refuses to delete a type any account
    row uses, so they count as using it."""
    return conn.execute("SELECT COUNT(*) FROM accounts WHERE type_id = ? AND deleted = 1", (type_id,)).fetchone()[0]


def _in_use_message(live: int, deleted: int) -> str:
    """Why a type in use cannot be deleted, saying so when only deleted accounts are holding it."""
    say = locales.speaking()
    if not deleted:
        return f"{say.integer(live)} {'account uses' if live == 1 else 'accounts use'} this type. Change their type first."
    if not live:
        return (f"{say.integer(deleted)} deleted {'account uses' if deleted == 1 else 'accounts use'} this type. "
                "Restoring deleted accounts isn't possible yet.")
    return (f"{say.integer(live + deleted)} accounts use this type, {say.integer(deleted)} of them deleted. "
            "Restoring deleted accounts isn't possible yet.")


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


def add_type(op: Operation, name: str | None, class_id: int | None,
             stale_after_days: int | str | None) -> int:
    conn = op.conn
    name = _clean_name(conn, name)
    class_id = _check_class(conn, class_id)
    days = _clean_days(stale_after_days)
    return writer.insert(op, "account_types", {"name": name, "class_id": class_id, "stale_after_days": days})


def update_type(op: Operation, type_id: int, name: str | None,
                stale_after_days: int | str | None, class_id: int | None = None) -> None:
    """Rename a type and change its stale days. The class changes only while no account uses it."""
    conn = op.conn
    current = get_type(conn, type_id)
    name = _clean_name(conn, name, exclude_id=type_id)
    days = _clean_days(stale_after_days)
    new_class = current["class_id"] if class_id is None else _check_class(conn, class_id)
    if new_class != current["class_id"] and (count_accounts(conn, type_id) or count_deleted_accounts(conn, type_id)):
        raise ValidationError("The class can't change while accounts use this type.")
    writer.update(op, "account_types", type_id, {"name": name, "class_id": new_class, "stale_after_days": days})


def delete_type(op: Operation, type_id: int) -> None:
    """Delete a type that no account uses."""
    conn = op.conn
    get_type(conn, type_id)
    live, deleted = count_accounts(conn, type_id), count_deleted_accounts(conn, type_id)
    if live or deleted:
        raise ValidationError(_in_use_message(live, deleted))
    writer.delete(op, "account_types", type_id)
