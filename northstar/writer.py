"""The one place that writes to the database. Every INSERT, UPDATE and DELETE the application makes is here, and a
test fails on any that is not (migrations excepted). See docs/design/v0.2-db-schema/design.md, "The write chokepoint".

A write belongs to an `Operation`: one user action, made once and passed to every write it causes. It carries the
connection, the actor and the kind of action, so a write cannot happen without saying who made it and why, and nothing is
kept as hidden state on the connection.

Table and column names are put into SQL text, so they are never taken from the caller's text: they are checked against
the live schema and an unknown one raises. Values are always parameters.

The audit columns and the version are the writer's: `insert` sets created_by and updated_by from the operation's actor,
and `update` sets updated_at and updated_by when it really changes something. A caller cannot set them. An operation
with no actor (the command line) is made by the system user.

The change log is written here too, in the same transaction as the change. Each write goes in this order:
  1. nothing changed: nothing is written;
  2. only unlogged fields changed (a theme, a password): the row and its audit columns are updated, and no log is kept;
  3. otherwise the operation's header row (sys_operations) is written, the first time it is needed and not before, the
     row is changed with its audit columns and version, and one sys_record_changes row says what changed.
Which fields are logged is in sys_audited_fields, which is read once per operation and table.
"""

import json
import sqlite3
from dataclasses import dataclass, field

from northstar import db

# The columns the writer fills from the operation's actor. A table has audit columns if it has these.
AUTHOR_COLUMNS = ("created_by", "updated_by")
# All four audit columns, which belong to the writer and which a caller cannot set. The two dates are filled by SQLite:
# an insert takes the column default, and an update sets updated_at in its own statement.
AUDIT_COLUMNS = (*AUTHOR_COLUMNS, "created_at", "updated_at")
# `version`, on a table that has it, is the id of the operation that last made a logged change to the row.
VERSION = "version"
# Tables whose rows are never removed: they are marked deleted instead. Their balances and history are kept, and the
# cascade from a balance to its account would otherwise erase them quietly.
SOFT_DELETED = frozenset({"accounts", "users"})
# A table the application writes for itself (sign-in sessions, failed-login tracking, the change log) is prefixed sys_.
# It holds no household data, has no audit columns, and a write to it needs no operation.

# The origin of an action. These are the rows of sys_operation_kinds, and a test keeps the two the same.
KINDS = ("ui_edit", "bulk_update", "import", "undo", "cli")

_CONDITIONS = {"=": "= ?", "!=": "!= ?", "<=": "<= ?", "IS": "IS ?"}


class DuplicateChangeError(RuntimeError):
    """An operation changed the same record twice. The change log keeps one change per record per operation, so this is a
    programming error: the final change to each record must be worked out before the writer is called."""


@dataclass(frozen=True)
class Operation:
    """One user action. `actor_id` is the signed-in user's id, or None for the command line, which has no user and so
    acts as the system user. `kind` is where the action came from (one of KINDS) and `detail` is anything the header
    should say about it, as plain JSON values (for a bulk update, its date).

    An operation is for one action and one transaction. The writer keeps what it learns, the id of the operation's header
    and the fields that are logged, in `state`."""
    conn: sqlite3.Connection
    actor_id: int | None
    kind: str
    detail: dict | None = None
    state: dict = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"{self.kind!r} is not an operation kind.")


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


def _audited(known: list[str]) -> bool:
    return all(column in known for column in AUTHOR_COLUMNS)


def _refuse_owned(values) -> None:
    owned = sorted(set(values) & {*AUDIT_COLUMNS, VERSION})
    if owned:
        raise ValueError(f"{', '.join(owned)} are set by the writer, not by the caller.")


def _columns(conn: sqlite3.Connection, table: str, *, system: bool) -> list[str]:
    """The columns of a table that exists and is of the right kind, in order, or an error."""
    if _is_system(table) != system:
        raise ValueError(f"{table} cannot be written this way.")
    columns = [row[0] for row in conn.execute("SELECT name FROM pragma_table_info(?) ORDER BY cid", (table,))]
    if not columns:
        raise ValueError(f"There is no table {table}.")
    return columns


def _check_columns(table: str, known: list[str], names) -> None:
    unknown = sorted(set(names) - set(known))
    if unknown:
        raise ValueError(f"{table} has no column {', '.join(unknown)}.")


def _logged(op: Operation, table: str, known: list[str]) -> list[str]:
    """The columns of the table whose changes are logged, in column order. Read from the registry once per operation."""
    registry = op.state.setdefault("registry", {})
    if table not in registry:
        registry[table] = {name: bool(flag) for name, flag in op.conn.execute(
            "SELECT fieldname, is_logged FROM sys_audited_fields WHERE tablename = ?", (table,))}
    missing = sorted(set(known) - registry[table].keys())
    if missing:
        raise RuntimeError(f"{table}.{', '.join(missing)} has no row in sys_audited_fields. Say whether it is logged.")
    return [name for name in known if registry[table][name]]


def _operation_id(op: Operation) -> int:
    """The id of the operation's header row, written the first time a logged change needs it and not before, so an
    action that changes nothing that is logged leaves no header behind."""
    known = op.state.get("id")
    if known is not None:
        if op.conn.execute("SELECT 1 FROM sys_operations WHERE id = ?", (known,)).fetchone() is None:
            raise RuntimeError("This operation was rolled back, so it cannot make more changes. Start a new one.")
        return known
    op.state["id"] = _insert(op.conn, "sys_operations", {
        "kind": op.kind, "user_id": _actor(op), "detail": None if op.detail is None else json.dumps(op.detail)})
    return op.state["id"]


def _record(op: Operation, operation_id: int, table: str, record_id: int, change: str, old: dict | None, new: dict | None):
    try:
        _insert(op.conn, "sys_record_changes", {
            "operation_id": operation_id, "tablename": table, "record_id": record_id, "change": change,
            "old_json": None if old is None else json.dumps(old), "new_json": None if new is None else json.dumps(new)})
    except sqlite3.IntegrityError as error:
        if "UNIQUE" in str(error):
            raise DuplicateChangeError(f"{table} {record_id} was changed twice in one operation.") from error
        raise


def insert(op: Operation, table: str, values: dict) -> int:
    """Add a row to a household table and return its id. Always a logged change."""
    known = _columns(op.conn, table, system=False)
    _check_columns(table, known, values)
    _refuse_owned(values)
    with db.write_transaction(op.conn):
        logged = _logged(op, table, known)
        operation_id = _operation_id(op)
        values = dict(values)
        if _audited(known):
            values.update(created_by=_actor(op), updated_by=_actor(op))
        if VERSION in known:
            values[VERSION] = operation_id
        new_id = _insert(op.conn, table, values)
        row = op.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (new_id,)).fetchone()
        _record(op, operation_id, table, new_id, "INSERT", None, {name: row[name] for name in logged})
        return new_id


def update(op: Operation, table: str, record_id: int, changes: dict, *, only_if: dict | None = None) -> bool:
    """Change fields of one row, and stamp who changed it and when. Returns False, and touches nothing, when the row is
    missing, when `only_if` (columns that must still hold the given values, so a concurrent change is not overwritten)
    does not match, or when no field would change. A change to nothing but unlogged fields is made without a log."""
    known = _columns(op.conn, table, system=False)
    only_if = only_if or {}
    _check_columns(table, known, [*changes, *only_if])
    _refuse_owned(changes)
    with db.write_transaction(op.conn):
        current = op.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
        if current is None or any(current[column] != value for column, value in only_if.items()):
            return False
        changed = {column: value for column, value in changes.items() if current[column] != value}
        if not changed:
            return False
        logged = _logged(op, table, known)
        logged_changed = [column for column in logged if column in changed]
        assignments, values = [f"{column} = ?" for column in changed], list(changed.values())
        if _audited(known):
            assignments += ["updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')", "updated_by = ?"]
            values.append(_actor(op))
        operation_id = _operation_id(op) if logged_changed else None
        if operation_id is not None and VERSION in known:
            assignments.append(f"{VERSION} = ?")
            values.append(operation_id)
        op.conn.execute(f"UPDATE {table} SET {', '.join(assignments)} WHERE id = ?", [*values, record_id])
        if logged_changed:
            row = op.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
            _record(op, operation_id, table, record_id, "UPDATE",
                    {name: current[name] for name in logged_changed}, {name: row[name] for name in logged_changed})
        return True


def delete(op: Operation, table: str, record_id: int) -> None:
    """Remove a row from a household table, if it is one that is ever removed."""
    known = _columns(op.conn, table, system=False)
    if table in SOFT_DELETED:
        raise ValueError(f"{table} are marked deleted, never removed.")
    with db.write_transaction(op.conn):
        current = op.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (record_id,)).fetchone()
        if current is None:
            return
        logged = _logged(op, table, known)
        operation_id = _operation_id(op)
        op.conn.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))
        _record(op, operation_id, table, record_id, "DELETE", {name: current[name] for name in logged}, None)


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
