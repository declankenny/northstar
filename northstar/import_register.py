"""The register of past imports, read from the change log (sys_operations, kind 'import'). Plain functions, no web code.

An import that wrote nothing creates no operation, so it is not listed. The account is named by the id in the import's
header and shown as it is now; a deleted account is marked, and a header without an id (none exist outside tests) has none.
"""

import json
import sqlite3

LIMIT = 25      # the newest imports listed; older ones are not


def list_imports(conn: sqlite3.Connection) -> dict:
    """The newest imports first, at most LIMIT, and whether there are more."""
    rows = conn.execute(
        "SELECT o.id, o.created_at, o.detail, u.display_name AS by_name, "
        "  (SELECT r.created_at FROM sys_operations r WHERE r.undoes_operation_id = o.id) AS reverted_at "
        "FROM sys_operations o JOIN users u ON u.id = o.user_id "
        "WHERE o.kind = 'import' ORDER BY o.id DESC LIMIT ?", (LIMIT + 1,)).fetchall()
    return {"imports": [_entry(conn, row) for row in rows[:LIMIT]], "more": len(rows) > LIMIT, "limit": LIMIT}


def _entry(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    detail = json.loads(row["detail"] or "{}")
    counts = detail.get("counts") or {}
    account = None
    if detail.get("account_id") is not None:
        account = conn.execute("SELECT id, name, is_open, deleted FROM accounts WHERE id = ?", (detail["account_id"],)).fetchone()
    return {
        "id": row["id"],
        "date": row["created_at"][:10],
        "by": row["by_name"],
        "account_id": None if account is None else account["id"],
        "account_name": None if account is None else account["name"],
        "account_deleted": account is not None and bool(account["deleted"]),
        "account_open": account is not None and bool(account["is_open"]),
        "file": detail.get("file"),
        "added": counts.get("added", 0),
        "replaced": counts.get("updated", 0),
        "reverted_on": None if row["reverted_at"] is None else row["reverted_at"][:10],
    }
