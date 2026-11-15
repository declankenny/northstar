"""The cleanup of deleted data, the second job of the in-app scheduler (#269). See docs/design/history-and-recovery/design.md.

A deleted account and an individually deleted balance stay recoverable for `data.deleted.retention_days`. Once that has passed, the nightly
cleanup removes them for good, with every logged change to them, so that the values they held are not left in the change log.

* An account's clock is its `updated_at` while `deleted` is 1: deleting goes through the writer, which stamps it, and nothing writes to a
  deleted account afterwards. Its balances go with it, on the account's clock, and so does the history of any balance it ever had.
* A balance's clock is the time of the operation that deleted it: the latest entry for it in the log is a DELETE. A balance removed by
  an import's undo was removed on purpose and as a group, and is not part of this.

Every record is purged in a transaction of its own that first checks, inside it, that the record is still deleted and still past its
period, so a record restored after the list was drawn up is left alone. Nothing here is a setting of the job itself: the retention is read
when a run starts, and an unset start time means the scheduler never starts it.
"""

import logging
from datetime import datetime, timedelta, timezone

from northstar import scheduler, system_properties, writer
from northstar.writer import Operation

log = logging.getLogger(__name__)

JOB = "data.deleted.cleanup"
TIME_PROPERTY = "data.deleted.cleanup_time"
RETENTION_PROPERTY = "data.deleted.retention_days"


def cutoff(conn, now: datetime) -> str | None:
    """The moment before which a deletion has run out its period, as the UTC text the database keeps, or None when the period is
    longer than a date can go back (so nothing is eligible)."""
    days = system_properties.get_value(conn, RETENTION_PROPERTY)
    try:
        return (now.astimezone(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, TypeError, ValueError):
        return None


def expired_accounts(conn, before: str) -> list[int]:
    """The accounts that are deleted and were deleted before `before`."""
    return [row[0] for row in conn.execute("SELECT id FROM accounts WHERE deleted = 1 AND updated_at <= ? ORDER BY id", (before,))]


def expired_balances(conn, before: str) -> list[int]:
    """The balances whose latest change in the log is a deletion made before `before`, other than by an undo."""
    return [row[0] for row in conn.execute(
        "SELECT rc.record_id FROM sys_record_changes rc JOIN sys_operations o ON o.id = rc.operation_id "
        "WHERE rc.tablename = 'balances' AND rc.change = 'DELETE' AND o.kind != 'undo' AND o.created_at <= ? "
        "AND rc.id = (SELECT MAX(id) FROM sys_record_changes WHERE tablename = 'balances' AND record_id = rc.record_id) "
        "AND NOT EXISTS (SELECT 1 FROM balances b WHERE b.id = rc.record_id) ORDER BY rc.record_id", (before,))]


def purge_account(conn, account_id: int, before: str) -> bool:
    """Purge one account if it is still deleted and still past its period. Returns whether it did."""
    if account_id not in expired_accounts(conn, before):
        return False
    writer.purge(Operation(conn, None, "purge", {"table": "accounts", "record_id": account_id}), "accounts", account_id)
    return True


def purge_balance(conn, balance_id: int, before: str) -> bool:
    """Purge one deleted balance if it is still deleted and still past its period. Returns whether it did."""
    if balance_id not in expired_balances(conn, before):
        return False
    writer.purge(Operation(conn, None, "purge", {"table": "balances", "record_id": balance_id}), "balances", balance_id)
    return True


def run(ctx) -> None:
    """The job: the accounts first, with their balances, then the balances deleted on their own. Each is its own transaction, which the
    lock is checked in, so a run that is stopped or loses its lock has purged whole records and no part of one."""
    before = cutoff(ctx.conn, ctx.now())
    if before is None:
        return
    purged = 0
    for account_id in expired_accounts(ctx.conn, before):
        ctx.check()
        purged += ctx.commit(lambda conn: purge_account(conn, account_id, before))
    for balance_id in expired_balances(ctx.conn, before):
        ctx.check()
        purged += ctx.commit(lambda conn: purge_balance(conn, balance_id, before))
    log.info("Cleanup of deleted data purged %d records.", purged)
