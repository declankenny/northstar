"""The one place that writes to the database. Every INSERT, UPDATE and DELETE the application makes is here, and a
test fails on any that is not (migrations excepted). See docs/design/v0.2-db-schema/design.md, "The write chokepoint".

A write belongs to an `Operation`: one user action, made once and passed to every write it causes. It carries the
connection and the actor, so a write cannot happen without saying who made it, and nothing is kept as hidden state on
the connection. The actor is not used yet; it is here so the change log and the audit columns (v0.2) can record it
without touching every caller again.

Table and column names are put into SQL text, so they are never taken from the caller's text: they are checked against
the live schema and an unknown one raises. Values are always parameters.

The audit columns are the writer's: `insert` sets created_by and updated_by from the operation's actor, and `update` sets
updated_at and updated_by when it really changes something. A caller cannot set them. An operation with no actor (the
command line) is made by the system user.
"""

import sqlite3
from dataclasses import dataclass

# The columns the writer fills from the operation's actor. A table has audit columns if it has these.
AUTHOR_COLUMNS = ("created_by", "updated_by")
# All four audit columns, which belong to the writer and which a caller cannot set. The two dates are filled by SQLite:
# an insert takes the column default, and an update sets updated_at in its own statement.
AUDIT_COLUMNS = (*AUTHOR_COLUMNS, "created_at", "updated_at")
# Tables whose rows are never removed: they are marked deleted instead. Their balances and history are kept, and the
# cascade from a balance to its account would otherwise erase them quietly.
SOFT_DELETED = frozenset({"accounts", "users"})
# A table the application writes for itself (sign-in sessions, failed-login tracking) is prefixed sys_. It holds no
# household data, has no audit columns, and a write to it needs no operation.

_CONDITIONS = {"=": "= ?", "!=": "!= ?", "<=": "<= ?", "IS": "IS ?"}


@dataclass(frozen=True)
class Operation:
    """One user action. `actor_id` is the signed-in user's id, or None for the command line, which has no user and so
    acts as the system user."""
    conn: sqlite3.Connection
    actor_id: int | None


def _is_system(table: str) -> bool:
    return table.startswith("sys_")


def _actor(op: Operation) -> int:
    """The id of whoever made the operation. The system user is found by its flag, never by a number."""
    if op.actor_id is not None:
        return op.actor_id
    row = op.conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()
    if row is None:
        raise RuntimeError("There is no system user. The database has not been migrated.")
    return row[0]


def _audited(known: set[str]) -> bool:
    return all(column in known for column in AUTHOR_COLUMNS)


def _refuse_audit(values) -> None:
    owned = sorted(set(values) & set(AUDIT_COLUMNS))
    if owned:
        raise ValueError(f"{', '.join(owned)} are set by the writer, not by the caller.")


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
    known = _columns(op.conn, table, system=False)
    _check_columns(table, known, values)
    _refuse_audit(values)
    if _audited(known):
        values = {**values, "created_by": _actor(op), "updated_by": _actor(op)}
    return _insert(op.conn, table, values)


def update(op: Operation, table: str, record_id: int, changes: dict, *, only_if: dict | None = None) -> bool:
    """Change fields of one row, and stamp who changed it and when. Returns False, and touches nothing, when the row is
    missing, when `only_if` (columns that must still hold the given values, so a concurrent change is not overwritten)
    does not match, or when no field would change."""
    known = _columns(op.conn, table, system=False)
    only_if = only_if or {}
    _check_columns(table, known, [*changes, *only_if])
    _refuse_audit(changes)
    current = op.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
    if current is None or any(current[column] != value for column, value in only_if.items()):
        return False
    if all(current[column] == value for column, value in changes.items()):
        return False
    assignments, values = [f"{column} = ?" for column in changes], list(changes.values())
    if _audited(known):
        assignments += ["updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')", "updated_by = ?"]
        values.append(_actor(op))
    op.conn.execute(f"UPDATE {table} SET {', '.join(assignments)} WHERE id = ?", [*values, record_id])
    return True


def delete(op: Operation, table: str, record_id: int) -> None:
    """Remove a row from a household table, if it is one that is ever removed."""
    _columns(op.conn, table, system=False)
    if table in SOFT_DELETED:
        raise ValueError(f"{table} are marked deleted, never removed.")
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
