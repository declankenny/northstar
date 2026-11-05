"""The register of past imports, read from the change log (sys_operations, kind 'import'), and the undo of an import.
Plain functions, no web code.

An import that wrote nothing creates no operation, so it is not listed. The account is named by the id in the import's
header and shown as it is now; a deleted account is marked, and a header without an id (none exist outside tests) has none.

Undo is all or nothing. It reverts an import only if every balance the import wrote is still as the import left it (the
balance's version is still the import's operation id) and its account is open; otherwise it refuses, writes nothing, and
says which dates are in the way. The commit repeats the checks under the write lock, so a change between the plan and
the commit is a refusal and never an overwrite.
"""

import json
import sqlite3
from dataclasses import dataclass

from northstar import db, locales, writer
from northstar.errors import NotFoundError, ValidationError
from northstar.writer import Operation

LIMIT = 25      # the newest imports listed; older ones are not
SHOWN = 10      # blocked dates named in a refusal; the rest are counted


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


class UndoBlocked(ValidationError):
    """The import cannot be undone as things are now. Nothing was written. `kind` says why: `reverted` (already undone),
    `account_closed`, `account_deleted`, or `changed` (some balances moved on, and `blocked` names the first SHOWN of them,
    each with its date and a reason, out of `total`)."""

    def __init__(self, message: str, kind: str, blocked: list[dict] | None = None, total: int = 0):
        super().__init__(message)
        self.kind = kind
        self.blocked = blocked or []
        self.total = total

    @property
    def details(self) -> dict:
        return {"reason": self.kind, "blocked": self.blocked[:SHOWN], "more": max(self.total - SHOWN, 0)}


@dataclass(frozen=True)
class UndoPlan:
    """What undoing an import would do: the balances it added (deleted) and the ones it replaced (put back as they were)."""
    import_id: int
    file: str | None
    date: str
    by: str
    account_id: int | None
    account_name: str | None
    delete: list[int]
    restore: list[tuple[int, dict]]


@dataclass(frozen=True)
class UndoResult:
    deleted: int
    restored: int


def _date_of(conn: sqlite3.Connection, balance_id: int) -> str:
    """A balance's date from the log, for one that is gone."""
    row = conn.execute(
        "SELECT COALESCE(json_extract(new_json, '$.as_of_date'), json_extract(old_json, '$.as_of_date')) FROM sys_record_changes "
        "WHERE tablename = 'balances' AND record_id = ? "
        "AND (json_extract(new_json, '$.as_of_date') IS NOT NULL OR json_extract(old_json, '$.as_of_date') IS NOT NULL) "
        "ORDER BY id DESC LIMIT 1", (balance_id,)).fetchone()
    return row[0] if row else "an unknown date"


def _why_changed(conn: sqlite3.Connection, version: int) -> str:
    """Why a balance no longer carries the import's version, from the operation that wrote it last."""
    row = conn.execute("SELECT kind, created_at FROM sys_operations WHERE id = ?", (version,)).fetchone()
    if row is not None and row["kind"] == "import":
        return f"Replaced by a later import ({locales.speaking().date(row['created_at'][:10])})"
    return "Edited since the import"


def undo_plan(conn: sqlite3.Connection, import_id: int) -> UndoPlan:
    """What undoing the import would do, or an UndoBlocked saying why it cannot. Writes nothing."""
    header = conn.execute(
        "SELECT o.id, o.created_at, o.detail, u.display_name AS by_name FROM sys_operations o JOIN users u ON u.id = o.user_id "
        "WHERE o.id = ? AND o.kind = 'import'", (import_id,)).fetchone()
    if header is None:
        raise NotFoundError("That import no longer exists.")
    reverted = conn.execute("SELECT created_at FROM sys_operations WHERE undoes_operation_id = ?", (import_id,)).fetchone()
    if reverted is not None:
        raise UndoBlocked(f"This import was already undone on {locales.speaking().date(reverted['created_at'][:10])}.", "reverted")
    detail = json.loads(header["detail"] or "{}")
    changes = conn.execute(
        "SELECT c.record_id, c.change, c.old_json, b.id AS found, b.version, b.as_of_date, "
        "       a.id AS account_id, a.name AS account_name, a.is_open, a.deleted "
        "FROM sys_record_changes c LEFT JOIN balances b ON b.id = c.record_id LEFT JOIN accounts a ON a.id = b.account_id "
        "WHERE c.operation_id = ? AND c.tablename = 'balances' ORDER BY c.id", (import_id,)).fetchall()
    accounts_involved = {}
    if detail.get("account_id") is not None:
        named = conn.execute("SELECT id, name, is_open, deleted FROM accounts WHERE id = ?", (detail["account_id"],)).fetchone()
        if named is not None:
            accounts_involved[named["id"]] = named
    for change in changes:
        if change["found"] is not None:
            accounts_involved[change["account_id"]] = {
                "name": change["account_name"], "is_open": change["is_open"], "deleted": change["deleted"]}
    for account in accounts_involved.values():
        if account["deleted"]:
            raise UndoBlocked(f"{account['name']} was deleted, so its balances cannot be changed.", "account_deleted")
    for account in accounts_involved.values():
        if not account["is_open"]:
            raise UndoBlocked(f"{account['name']} is closed, and a closed account takes no changes. Reopen it, then try Undo again.",
                              "account_closed")
    blocked, delete, restore = [], [], []
    for change in changes:
        if change["found"] is None:
            blocked.append({"date": _date_of(conn, change["record_id"]), "why": "Deleted since the import"})
        elif change["version"] != import_id:
            blocked.append({"date": change["as_of_date"], "why": _why_changed(conn, change["version"])})
        elif change["change"] == "INSERT":
            delete.append(change["record_id"])
        else:
            restore.append((change["record_id"], json.loads(change["old_json"])))
    if blocked:
        blocked.sort(key=lambda entry: entry["date"])
        raise UndoBlocked("Some of this import's balances have changed since, and Undo does not overwrite later changes.",
                          "changed", blocked, len(blocked))
    named_account = accounts_involved.get(detail.get("account_id"))
    return UndoPlan(import_id, detail.get("file"), header["created_at"][:10], header["by_name"],
                    None if named_account is None else detail["account_id"], None if named_account is None else named_account["name"],
                    delete, restore)


def undo_import(conn: sqlite3.Connection, actor_id: int | None, import_id: int) -> UndoResult:
    """Undo the import, or refuse with UndoBlocked and write nothing. The checks run again under the write lock, and the
    whole undo is one transaction and one operation."""
    with db.write_transaction(conn):
        plan = undo_plan(conn, import_id)
        op = Operation(conn, actor_id, "undo", {"undoes": import_id, "deleted": len(plan.delete), "restored": len(plan.restore)},
                       undoes=import_id)
        for balance_id in plan.delete:
            writer.delete(op, "balances", balance_id)
        for balance_id, old in plan.restore:
            if not writer.update(op, "balances", balance_id, old, only_if={"version": import_id}):
                raise RuntimeError("A balance the undo checked has changed under the write lock.")
        return UndoResult(len(plan.delete), len(plan.restore))
