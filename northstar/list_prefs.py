"""A person's choices for the lists. Plain functions, no web code. Today that is how many rows a page shows, for each list."""

import sqlite3

from northstar import writer
from northstar.errors import ValidationError
from northstar.lists.listdef import PAGE_SIZES
from northstar.writer import Operation


def page_size(conn: sqlite3.Connection, user_id: int, list_key: str, default: int) -> int:
    """How many rows a page of this list shows for this person: their choice, or `default` when they have not made one."""
    row = conn.execute("SELECT page_size FROM user_list_prefs WHERE user_id = ? AND list_key = ?", (user_id, list_key)).fetchone()
    return default if row is None else row["page_size"]


def set_page_size(op: Operation, list_key: str, size) -> int:
    """Save the signed-in person's page size for a list. Returns it. A size that is not one of the offered ones is refused."""
    if isinstance(size, bool) or size not in PAGE_SIZES:
        raise ValidationError(f"Show {', '.join(map(str, PAGE_SIZES))} rows per page.")
    row = op.conn.execute("SELECT id FROM user_list_prefs WHERE user_id = ? AND list_key = ?", (op.actor_id, list_key)).fetchone()
    if row is None:
        writer.insert(op, "user_list_prefs", {"user_id": op.actor_id, "list_key": list_key, "page_size": size})
    else:
        writer.update(op, "user_list_prefs", row["id"], {"page_size": size})
    return size
