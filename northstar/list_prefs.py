"""A person's choices for the lists. Plain functions, no web code. That is how many rows a page shows and which columns, for each list."""

import json
import sqlite3

from northstar import writer
from northstar.errors import ValidationError
from northstar.lists.listdef import PAGE_SIZES, ListDef
from northstar.lists.registry import Catalog
from northstar.lists.request import parse_request
from northstar.writer import Operation


def _row(conn: sqlite3.Connection, user_id: int, list_key: str):
    return conn.execute("SELECT id, page_size, columns FROM user_list_prefs WHERE user_id = ? AND list_key = ?", (user_id, list_key)).fetchone()


def _save(op: Operation, list_key: str, **values) -> None:
    """Change one of the person's choices for a list, making the row if it is the first one they have made."""
    row = _row(op.conn, op.actor_id, list_key)
    if row is None:
        writer.insert(op, "user_list_prefs", {"user_id": op.actor_id, "list_key": list_key, **values})
    else:
        writer.update(op, "user_list_prefs", row["id"], values)


def page_size(conn: sqlite3.Connection, user_id: int, list_key: str, default: int) -> int:
    """How many rows a page of this list shows for this person: their choice, or `default` when they have not made one."""
    row = _row(conn, user_id, list_key)
    return default if row is None or row["page_size"] is None else row["page_size"]


def set_page_size(op: Operation, list_key: str, size) -> int:
    """Save the signed-in person's page size for a list. Returns it. A size that is not one of the offered ones is refused."""
    if isinstance(size, bool) or size not in PAGE_SIZES:
        raise ValidationError(f"Show {', '.join(map(str, PAGE_SIZES))} rows per page.")
    _save(op, list_key, page_size=size)
    return size


def saved_columns(conn: sqlite3.Connection, user_id: int, list_key: str) -> str | None:
    """The columns this person chose for the list, as the JSON text they were stored as, or None when they have not chosen."""
    row = _row(conn, user_id, list_key)
    return None if row is None else row["columns"]


def usable_columns(catalog: Catalog, definition: ListDef, stored: str) -> tuple[list[str], list[dict]]:
    """The stored columns that the list still offers, in order, and the ones it no longer does with the reason, so a column the list
    has stopped offering is dropped and nothing more. An empty result means the person's choice is gone and the list's own applies."""
    kept, skipped = [], []
    for key in json.loads(stored):
        try:
            parse_request(catalog, definition, {"columns": [key]})
            kept.append(key)
        except ValidationError as error:
            skipped.append({"field": key if isinstance(key, str) else None, "reason": str(error)})
    return kept, skipped


def set_columns(op: Operation, catalog: Catalog, definition: ListDef, columns) -> list[str]:
    """Save the signed-in person's columns for a list, in the order they gave. Returns them. `None` forgets the choice, so the list's own
    columns apply again. At least one column, each offered by the list and shown once, or the request is refused."""
    if columns is None:
        if _row(op.conn, op.actor_id, definition.key) is not None:
            _save(op, definition.key, columns=None)
        return list(definition.columns)
    parsed = parse_request(catalog, definition, {"columns": columns})          # the same rules as a request that names columns
    _save(op, definition.key, columns=json.dumps(list(parsed.columns)))
    return list(parsed.columns)
