"""Deleted accounts (#270): the admin list of them, and bringing one back. See docs/design/history-and-recovery/design.md.

Deleting an account marks it deleted and leaves its balances where they are, hidden with it (accounts.delete_account), so restoring is
clearing that mark: the balances it hid return with it, and a balance that was deleted on its own before has no row and stays deleted.
Nothing writes to a deleted account's row, so its `updated_at` is when it was deleted, which is also the clock of the cleanup
(retention.py). This module reads the accounts table directly because live_accounts, by design, leaves these accounts out.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

from northstar import accounts, db, retention, system_properties, writer
from northstar.errors import NotFoundError
from northstar.writer import Operation

_STAMP = "%Y-%m-%dT%H:%M:%SZ"


def _purge_date(deleted_at: str, days: int) -> str | None:
    """The UTC date the cleanup is due to remove an account deleted at `deleted_at`, or None when a period that long is beyond a date."""
    try:
        return (datetime.strptime(deleted_at, _STAMP) + timedelta(days=days)).strftime("%Y-%m-%d")
    except (OverflowError, ValueError):
        return None


def list_deleted(conn: sqlite3.Connection) -> dict:
    """Every deleted account, newest deletion first, with the date it is due to be removed for good (None when the cleanup is switched
    off, because nothing is then removed), and whether its name is in use by a live account now. All of them: a recovery list is not cut off."""
    days = system_properties.get_value(conn, retention.RETENTION_PROPERTY)
    scheduled = system_properties.get_value(conn, retention.TIME_PROPERTY) is not None
    rows = conn.execute(
        "SELECT a.id, a.name, t.name AS type_name, a.is_open, a.updated_at, "
        "  (SELECT COUNT(*) FROM balances b WHERE b.account_id = a.id) AS balance_count, "
        "  EXISTS (SELECT 1 FROM live_accounts l WHERE l.name = a.name COLLATE NOCASE) AS name_taken "
        "FROM accounts a JOIN account_types t ON t.id = a.type_id WHERE a.deleted = 1 ORDER BY a.updated_at DESC, a.id DESC").fetchall()
    return {"cleanup_on": scheduled, "retention_days": days, "accounts": [{
        "id": row["id"], "name": row["name"], "type_name": row["type_name"], "is_open": bool(row["is_open"]),
        "deleted_on": row["updated_at"][:10], "purge_on": _purge_date(row["updated_at"], days) if scheduled else None,
        "balance_count": row["balance_count"], "name_taken": bool(row["name_taken"])} for row in rows]}


def restore_account(op: Operation, account_id: int, name: str | None = None) -> dict:
    """Bring a deleted account back with the balances its deletion hid, open or closed as it was. The name is checked again here, in the
    transaction, against the live accounts (the same rule as any account change), so a name taken since the list was drawn is refused and
    nothing is written; a new `name` may be given in its place. Another account is never renamed, merged with or replaced.
    A record that is not deleted (restored by someone else, or permanently removed) is a NotFoundError. Returns {"id", "name", "balance_count"}."""
    conn = op.conn
    with db.write_transaction(conn):
        row = conn.execute("SELECT id, name FROM accounts WHERE id = ? AND deleted = 1", (account_id,)).fetchone()
        if row is None:
            raise NotFoundError("That account is not deleted any more. It may already have been restored or permanently deleted.")
        chosen = accounts._clean_name(name) if name is not None else row["name"]
        accounts._check_name_free(conn, chosen, account_id)
        writer.update(op, "accounts", account_id, {"deleted": 0, "name": chosen})
        count = conn.execute("SELECT COUNT(*) FROM balances WHERE account_id = ?", (account_id,)).fetchone()[0]
    return {"id": account_id, "name": chosen, "balance_count": count}
