"""The one place that writes to the database. Every INSERT, UPDATE and DELETE the application makes is here, and a
test fails on any that is not (migrations excepted). See docs/design/v0.2-db-schema/design.md, "The write chokepoint".

A write belongs to an `Operation`: one user action, made once and passed to every write it causes. It carries the
connection and the actor, so a write cannot happen without saying who made it, and nothing is kept as hidden state on
the connection. The actor is not used yet; it is here so the change log and the audit columns (v0.2) can record it
without touching every caller again.

Table and column names are put into SQL text, so they are never taken from the caller's text: they are checked against
the live schema and an unknown one raises. Values are always parameters.
"""

import sqlite3
from dataclasses import dataclass

# Tables the application writes for itself (sign-in sessions, failed-login tracking). They hold no household data, so a
# write to them needs no operation. They become sys_sessions and sys_login_attempts in a later migration, and then the
# sys_ prefix is the rule.
SYSTEM_TABLES = frozenset({"sessions", "login_attempts"})

_CONDITIONS = {"=": "= ?", "!=": "!= ?", "<=": "<= ?", "IS": "IS ?"}


@dataclass(frozen=True)
class Operation:
    """One user action. `actor_id` is the signed-in user's id, or None for the command line, which has no user (it
    becomes the system user when that exists)."""
    conn: sqlite3.Connection
    actor_id: int | None


class _Now:
    """The current time in the database's own format. Used as a value in `update`, where it is applied together with the
    real changes and is not itself a change."""

    def __repr__(self) -> str:
        return "NOW"


NOW = _Now()
_NOW_SQL = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"


def _is_system(table: str) -> bool:
    return table in SYSTEM_TABLES or table.startswith("sys_")


def _columns(conn: sqlite3.Connection, table: str, *, system: bool) -> set[str]:
    """The columns of a table that exists and is of the right kind, or an error."""
    if _is_system(table) != system:
        raise ValueError(f"{table} cannot be written this way.")
    columns = {row[0] for row in conn.execute("SELECT name FROM pragma_table_info(?)", (table,))}
    if not columns:
        raise ValueError(f"There is no table {table}.")
    return columns


def _check_columns(table: str, known: set[str], names) -> None:
    unknown = sorted(set(names) - known)
    if unknown:
        raise ValueError(f"{table} has no column {', '.join(unknown)}.")


def insert(op: Operation, table: str, values: dict) -> int:
    """Add a row to a household table and return its id."""
    _check_columns(table, _columns(op.conn, table, system=False), values)
    return _insert(op.conn, table, values)


def update(op: Operation, table: str, record_id: int, changes: dict, *, only_if: dict | None = None) -> bool:
    """Change fields of one row. Returns False, and touches nothing, when the row is missing, when `only_if` (columns that
    must still hold the given values, so a concurrent change is not overwritten) does not match, or when no field would
    change. `NOW` among the changes is applied with the real ones and does not count as a change itself."""
    known = _columns(op.conn, table, system=False)
    only_if = only_if or {}
    _check_columns(table, known, [*changes, *only_if])
    current = op.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
    if current is None or any(current[column] != value for column, value in only_if.items()):
        return False
    real = {column: value for column, value in changes.items() if value is not NOW}
    if all(current[column] == value for column, value in real.items()):
        return False
    assignments = [f"{column} = {_NOW_SQL}" if value is NOW else f"{column} = ?" for column, value in changes.items()]
    op.conn.execute(f"UPDATE {table} SET {', '.join(assignments)} WHERE id = ?", [*real.values(), record_id])
    return True


def delete(op: Operation, table: str, record_id: int) -> None:
    """Remove a row from a household table."""
    _columns(op.conn, table, system=False)
    op.conn.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))


def sys_insert(conn: sqlite3.Connection, table: str, values: dict) -> int:
    """Add a row to one of the application's own tables and return its rowid."""
    _check_columns(table, _columns(conn, table, system=True), values)
    return _insert(conn, table, values)


def sys_delete(conn: sqlite3.Connection, table: str, conditions: list[tuple[str, str, object]]) -> int:
    """Remove the rows of one of the application's own tables that meet every condition, each (column, operator, value)
    with the operator one of =, !=, <= and IS. Returns how many went."""
    known = _columns(conn, table, system=True)
    _check_columns(table, known, [column for column, _, _ in conditions])
    if not conditions or any(operator not in _CONDITIONS for _, operator, _ in conditions):
        raise ValueError("A delete needs conditions, each with a supported operator.")
    where = " AND ".join(f"{column} {_CONDITIONS[operator]}" for column, operator, _ in conditions)
    return conn.execute(f"DELETE FROM {table} WHERE {where}", [value for _, _, value in conditions]).rowcount


def _insert(conn: sqlite3.Connection, table: str, values: dict) -> int:
    columns = list(values)
    marks = ", ".join("?" for _ in columns)
    return conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({marks})", [values[column] for column in columns]
    ).lastrowid
