"""Deleted accounts (#270): the admin list of them, and bringing one back. See docs/design/history-and-recovery/design.md.

Deleting an account marks it deleted and leaves its balances where they are, hidden with it (accounts.delete_account), so restoring is
clearing that mark: the balances it hid return with it, and a balance that was deleted on its own before has no row and stays deleted.
Nothing writes to a deleted account's row, so its `updated_at` is when it was deleted, which is also the clock of the cleanup
(retention.py). This module reads the accounts table directly because live_accounts, by design, leaves these accounts out.
"""

import sqlite3
from datetime import datetime, time, timedelta, timezone, tzinfo

from northstar import accounts, db, retention, scheduler, system_properties, writer
from northstar.errors import NotFoundError
from northstar.writer import Operation

_STAMP = "%Y-%m-%dT%H:%M:%SZ"


def purge_date(deleted_at: str, days: int, start: str, zone: tzinfo) -> str | None:
    """The date, in the installation's zone, of the first scheduled run of the cleanup that finds an account deleted at `deleted_at` past its
    period, or None when a period that long is beyond a date. The period runs out at one moment, and the cleanup runs once a date from its
    start time (`start`, "HH:MM", as the scheduler reads it), so the run is on the date of that moment when it falls at or before the start time
    (an account is eligible from the moment its period ends, which the cleanup tests with <=), and on the next date when it falls after it. A run that was missed is made up on the date it was missed, which is this date."""
    try:
        expires = (datetime.strptime(deleted_at, _STAMP).replace(tzinfo=timezone.utc) + timedelta(days=days)).astimezone(zone)
    except (OverflowError, ValueError):
        return None
    day = expires.date() if expires.time().replace(tzinfo=None) <= time.fromisoformat(start) else expires.date() + timedelta(days=1)
    return day.isoformat()


def schedule(conn: sqlite3.Connection) -> tuple[int, str | None, tzinfo]:
    """What the dates of the recovery lists are worked out from: the retention period, the cleanup's start time (None when it is switched
    off) and the installation's zone."""
    return (system_properties.get_value(conn, retention.RETENTION_PROPERTY), system_properties.get_value(conn, retention.TIME_PROPERTY) or None,
            scheduler.zone_of(conn))


def list_deleted(conn: sqlite3.Connection) -> dict:
    """Every deleted account, newest deletion first, with the date of the cleanup run that will remove it (in the installation's zone, None when the cleanup is switched
    off, because nothing is then removed), and whether its name is in use by a live account now. All of them: a recovery list is not cut off."""
    days, start, zone = schedule(conn)
    scheduled = start is not None
    rows = conn.execute(
        "SELECT a.id, a.name, t.name AS type_name, a.is_open, a.updated_at, "
        "  (SELECT COUNT(*) FROM balances b WHERE b.account_id = a.id) AS balance_count, "
        "  EXISTS (SELECT 1 FROM live_accounts l WHERE l.name = a.name COLLATE NOCASE) AS name_taken, "
        "  (SELECT u.display_name FROM sys_record_changes rc JOIN sys_operations o ON o.id = rc.operation_id JOIN users u ON u.id = o.user_id "
        "   WHERE rc.tablename = 'accounts' AND rc.record_id = a.id AND rc.change = 'UPDATE' AND json_extract(rc.new_json, '$.deleted') = 1 "
        "   ORDER BY rc.id DESC LIMIT 1) AS deleted_by "
        "FROM accounts a JOIN account_types t ON t.id = a.type_id WHERE a.deleted = 1 ORDER BY a.updated_at DESC, a.id DESC").fetchall()
    return {"cleanup_on": scheduled, "retention_days": days, "accounts": [{
        "id": row["id"], "name": row["name"], "type_name": row["type_name"], "is_open": bool(row["is_open"]),
        "deleted_by": row["deleted_by"], "deleted_on": row["updated_at"][:10], "purge_on": purge_date(row["updated_at"], days, start, zone) if scheduled else None,
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
