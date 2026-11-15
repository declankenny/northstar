"""Deleted balances (#271): the admin list of balances that were deleted on their own, and putting one back. See
docs/design/history-and-recovery/design.md.

A balance is removed for good when it is deleted (its row goes), and what was in it stays in the change log: the DELETE entry's `old_json` holds
every logged field. So a deleted balance is a record whose latest entry in the log is a DELETE and that has no row now. Left out:

* a balance deleted by an import's undo, which was removed on purpose and as a group and is not recoverable one by one (the cleanup leaves it
  too, see retention.py);
* the balances of a deleted account, which come back through its Restore (deleted_accounts.py), after which any that were deleted on their own
  appear here.

Restoring writes the row again through the writer, under its original id, so its history is one history and the audit columns and the log apply.
"""

import json
import sqlite3

from northstar import accounts, balances, db, deleted_accounts, writer
from northstar.errors import NotFoundError, ValidationError
from northstar.writer import Operation

_LATEST_DELETE = (
    "FROM sys_record_changes rc JOIN sys_operations o ON o.id = rc.operation_id JOIN users u ON u.id = o.user_id "
    "WHERE rc.tablename = 'balances' AND rc.change = 'DELETE' AND o.kind != 'undo' "
    "AND rc.id = (SELECT MAX(id) FROM sys_record_changes WHERE tablename = 'balances' AND record_id = rc.record_id) "
    "AND NOT EXISTS (SELECT 1 FROM balances b WHERE b.id = rc.record_id) ")


class DateTaken(ValidationError):
    """A live balance has the date now, so restoring would replace it. Nothing was written. `existing` is that balance, for a link to it."""

    def __init__(self, message: str, existing: dict):
        super().__init__(message)
        self.existing = existing

    @property
    def details(self) -> dict:
        return {"reason": "date_taken", "existing": self.existing}


def list_deleted(conn: sqlite3.Connection) -> dict:
    """Every individually deleted balance of a live account, newest deletion first, with who deleted it and when, and the date of the cleanup
    run that will remove it for good (None when the cleanup is switched off). All of them: a recovery list is not cut off."""
    days, start, zone = deleted_accounts.schedule(conn)
    rows = conn.execute(
        f"SELECT rc.record_id, rc.old_json, o.created_at, u.display_name AS by_name {_LATEST_DELETE} ORDER BY o.created_at DESC, rc.id DESC").fetchall()
    out = []
    for row in rows:
        values = json.loads(row["old_json"])
        account = conn.execute(
            "SELECT a.id, a.name, a.is_open, c.code, c.name AS currency_name, c.minor_units FROM live_accounts a "
            "JOIN currencies c ON c.id = a.currency_id WHERE a.id = ?", (values["account_id"],)).fetchone()
        if account is None:
            continue                                    # its account is deleted (or gone): the account's own restore brings it back
        out.append({
            "id": row["record_id"], "account_id": account["id"], "account_name": account["name"], "account_open": bool(account["is_open"]),
            "currency": {"code": account["code"], "name": account["currency_name"], "minor_units": account["minor_units"]},
            "as_of_date": values["as_of_date"], "amount_cents": values["amount_cents"], "note": values.get("note"),
            "deleted_by": row["by_name"], "deleted_on": row["created_at"][:10],
            "purge_on": deleted_accounts.purge_date(row["created_at"], days, start, zone) if start is not None else None})
    return {"cleanup_on": start is not None, "retention_days": days, "balances": out}


def restore_balance(op: Operation, balance_id: int) -> dict:
    """Put a deleted balance back as it was, under its own id, with its amount, note and source. Rechecked here, in the transaction: the
    balance is still deleted, its account is live and open, and no live balance has its date (that one is never replaced: DateTaken, with the
    balance in the way). Anything refused writes nothing. The row's author and time are the restore's, and the log keeps the original entries.
    Returns {"id", "account_id", "as_of_date"}."""
    conn = op.conn
    with db.write_transaction(conn):
        row = conn.execute(f"SELECT rc.old_json {_LATEST_DELETE} AND rc.record_id = ?", (balance_id,)).fetchone()
        if row is None:
            raise NotFoundError("That balance is not deleted any more. It may already have been restored or permanently deleted.")
        values = {name: value for name, value in json.loads(row["old_json"]).items() if name not in (*writer.AUDIT_COLUMNS, "id")}
        account = conn.execute("SELECT id, name, is_open FROM live_accounts WHERE id = ?", (values["account_id"],)).fetchone()
        if account is None:
            raise NotFoundError("The account of that balance is deleted. Restore the account to bring its balances back.")
        balances.require_open(account)
        existing = conn.execute("SELECT id, amount_cents FROM live_balances WHERE account_id = ? AND as_of_date = ?",
                                (account["id"], values["as_of_date"])).fetchone()
        if existing is not None:
            raise DateTaken(f"{account['name']} already has a balance for that date. Restoring would replace it, so change or delete it first, then try again.",
                            {"balance_id": existing["id"], "amount_cents": existing["amount_cents"]})
        writer.insert(op, "balances", {"id": balance_id, **values})
        return {"id": balance_id, "account_id": account["id"], "as_of_date": values["as_of_date"]}
