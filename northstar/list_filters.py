"""Saved filters for the lists. Plain functions, no web code.

A saved filter is a name and the conditions of a filter for one list. A person's own are private. A filter with no owner is shared
with everyone who can see the list, and only an admin makes, changes or removes it. A list opens with the person's own default
filter, else the shared default, else none. What a condition means is the list engine's: it is checked against the list when it is
saved and again when it is used, because the list can change, and a condition that no longer fits is skipped, never an error.
"""

import json
import sqlite3

from northstar import db, writer
from northstar.errors import NotAllowedError, NotFoundError, ValidationError
from northstar.lists.listdef import ListDef
from northstar.lists.registry import Catalog
from northstar.lists.request import parse_request
from northstar.writer import Operation

MAX_NAME = 80
MAX_PER_SCOPE = 100           # the filters one person (or everyone) can keep for one list
MAX_JSON = 20_000
_UNSET = object()


def _name(text) -> str:
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        raise ValidationError("Give the filter a name.")
    if len(text) > MAX_NAME:
        raise ValidationError(f"A name can be at most {MAX_NAME} characters.")
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise ValidationError("A name cannot hold control characters.")
    return text


def checked(catalog: Catalog, definition: ListDef, conditions) -> str:
    """The conditions as the text that is stored, after the list engine has checked every one against the list."""
    if not isinstance(conditions, list):
        raise ValidationError("A filter is a list of conditions.")
    parse_request(catalog, definition, {"filters": conditions})
    clean = [{key: c[key] for key in ("field", "operator", "value") if key in c} for c in conditions]
    text = json.dumps(clean, separators=(",", ":"), ensure_ascii=False)
    if len(text) > MAX_JSON:
        raise ValidationError("That filter is too long to save.")
    return text


def visible(conn: sqlite3.Connection, user_id: int, list_key: str) -> list[sqlite3.Row]:
    """The filters of a list this person can see: the shared ones, and their own."""
    return conn.execute(
        "SELECT * FROM list_filters WHERE list_key = ? AND (owner_id IS NULL OR owner_id = ?) ORDER BY name COLLATE NOCASE, id",
        (list_key, user_id)).fetchall()


def default_id(conn: sqlite3.Connection, user_id: int, list_key: str) -> int | None:
    """The filter a list opens with for this person: their own default, else the shared default, else none."""
    row = conn.execute(
        "SELECT id FROM list_filters WHERE list_key = ? AND is_default = 1 AND (owner_id = ? OR owner_id IS NULL) "
        "ORDER BY owner_id IS NULL LIMIT 1", (list_key, user_id)).fetchone()
    return None if row is None else row["id"]


def get(conn: sqlite3.Connection, user_id: int, list_key: str, filter_id: int) -> sqlite3.Row:
    """One filter this person can see. Another person's private filter is not found, so its existence is not told."""
    row = conn.execute("SELECT * FROM list_filters WHERE id = ? AND list_key = ?", (filter_id, list_key)).fetchone()
    if row is None or (row["owner_id"] is not None and row["owner_id"] != user_id):
        raise NotFoundError("That filter no longer exists.")
    return row


def _editable(conn: sqlite3.Connection, user_id: int, is_admin: bool, list_key: str, filter_id: int) -> sqlite3.Row:
    row = get(conn, user_id, list_key, filter_id)
    if row["owner_id"] is None and not is_admin:
        raise NotAllowedError("Only admins can change a filter that is for everyone.")
    return row


def _check_name_free(conn: sqlite3.Connection, owner: int | None, list_key: str, name: str, own_id: int | None = None) -> None:
    taken = conn.execute(
        "SELECT 1 FROM list_filters WHERE COALESCE(owner_id, 0) = COALESCE(?, 0) AND list_key = ? AND name = ? COLLATE NOCASE AND id IS NOT ?",
        (owner, list_key, name, own_id)).fetchone()
    if taken:
        raise ValidationError(f'There is already a filter called "{name}". Choose another name, or replace that one.')


def create(op: Operation, catalog: Catalog, definition: ListDef, name, conditions, *, shared: bool, is_admin: bool) -> int:
    """Save a filter. A shared one is for admins. It is never the default until it is made one."""
    if shared and not is_admin:
        raise NotAllowedError("Only admins can save a filter for everyone.")
    name = _name(name)
    text = checked(catalog, definition, conditions)
    owner = None if shared else op.actor_id
    with db.write_transaction(op.conn):
        _check_name_free(op.conn, owner, definition.key, name)
        count = op.conn.execute("SELECT COUNT(*) FROM list_filters WHERE COALESCE(owner_id, 0) = COALESCE(?, 0) AND list_key = ?",
                                (owner, definition.key)).fetchone()[0]
        if count >= MAX_PER_SCOPE:
            raise ValidationError(f"There can be at most {MAX_PER_SCOPE} saved filters for one list. Remove one first.")
        return writer.insert(op, "list_filters", {"owner_id": owner, "list_key": definition.key, "name": name,
                                                  "conditions": text, "is_default": 0})


def update(op: Operation, catalog: Catalog, definition: ListDef, filter_id: int, *, is_admin: bool,
           name=_UNSET, conditions=_UNSET, is_default=_UNSET) -> None:
    """Rename a filter, replace its conditions, or make it (or stop it being) the default for its owner or, if it is shared, for
    everyone. Making one the default takes the mark from the one that had it, in the same transaction."""
    with db.write_transaction(op.conn):
        row = _editable(op.conn, op.actor_id, is_admin, definition.key, filter_id)
        changes: dict = {}
        if name is not _UNSET:
            changes["name"] = _name(name)
            _check_name_free(op.conn, row["owner_id"], definition.key, changes["name"], filter_id)
        if conditions is not _UNSET:
            changes["conditions"] = checked(catalog, definition, conditions)
        if is_default is not _UNSET:
            if not isinstance(is_default, bool):
                raise ValidationError("A filter is the default or it is not.")
            changes["is_default"] = int(is_default)
            if is_default:
                previous = op.conn.execute(
                    "SELECT id FROM list_filters WHERE COALESCE(owner_id, 0) = COALESCE(?, 0) AND list_key = ? AND is_default = 1 AND id != ?",
                    (row["owner_id"], definition.key, filter_id)).fetchone()
                if previous is not None:
                    writer.update(op, "list_filters", previous["id"], {"is_default": 0})
        writer.update(op, "list_filters", filter_id, changes)


def delete(op: Operation, definition: ListDef, filter_id: int, *, is_admin: bool) -> None:
    with db.write_transaction(op.conn):
        _editable(op.conn, op.actor_id, is_admin, definition.key, filter_id)
        writer.delete(op, "list_filters", filter_id)


def usable(catalog: Catalog, definition: ListDef, stored: str) -> tuple[list[dict], list[dict]]:
    """The conditions of a stored filter that still fit the list, and the ones that no longer do with the reason, so a column the list
    has stopped offering skips its condition and nothing more."""
    kept, skipped = [], []
    for condition in json.loads(stored):
        try:
            parse_request(catalog, definition, {"filters": [condition]})
            kept.append(condition)
        except ValidationError as error:
            skipped.append({"field": condition.get("field") if isinstance(condition, dict) else None, "reason": str(error)})
    return kept, skipped
