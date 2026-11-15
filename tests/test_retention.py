"""The cleanup of deleted data (#269): a deleted account and its balances on the account's clock, a balance deleted on its own clock, a
record restored or changed after the list was drawn up left alone, live and unrelated history untouched, and the job's setting and
schedule. Synthetic data only."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from northstar import accounts, balances, jobs, retention, scheduler, system_properties as sp, writer
from northstar.errors import ValidationError
from northstar.writer import Operation
from tests.conftest import op, type_id
from tests.test_scheduler import FakeClock, make_env

UTC = timezone.utc
NOW = datetime(2026, 11, 20, 3, 0, tzinfo=UTC)
ASSET = 1
JOB = retention.JOB


def stamp(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def account(conn, name="Test savings", balances_on=("2026-01-31",)):
    account_id = accounts.add_account(op(conn), name, ASSET, type_id(conn, "Savings"))
    for i, day in enumerate(balances_on):
        balances.record_balance(op(conn), account_id, date.fromisoformat(day), 100_000 + i)
    conn.commit()
    return account_id


def balance_id(conn, account_id, day):
    return conn.execute("SELECT id FROM balances WHERE account_id = ? AND as_of_date = ?", (account_id, day)).fetchone()[0]


def delete_account(conn, account_id, days_ago):
    accounts.delete_account(op(conn), account_id)
    conn.execute("UPDATE accounts SET updated_at = ? WHERE id = ?", (stamp(days_ago), account_id))
    conn.commit()


def delete_balance(conn, bid, days_ago):
    balances.delete_balance(op(conn), bid)
    conn.execute("UPDATE sys_operations SET created_at = ? WHERE id = (SELECT MAX(id) FROM sys_operations)", (stamp(days_ago),))
    conn.commit()


def go(conn, now=NOW):
    env = make_env(conn, jobs.REGISTRY, FakeClock(now))
    return [run for run in scheduler.run_due(env) if run[0] == JOB]


def log_rows(conn, table, record_id):
    return conn.execute("SELECT COUNT(*) FROM sys_record_changes WHERE tablename = ? AND record_id = ?", (table, record_id)).fetchone()[0]


def exists(conn, table, record_id):
    return conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (record_id,)).fetchone() is not None


def headers(conn, header):
    return conn.execute("SELECT COUNT(*) FROM sys_operations WHERE id = ?", (header,)).fetchone()[0]


# -- the setting --

def test_the_defaults_are_90_days_and_03_00(conn):
    assert sp.get_value(conn, "data.deleted.retention_days") == 90
    assert sp.get_value(conn, "data.deleted.cleanup_time") == "03:00"


def test_the_period_must_be_a_positive_whole_number(conn):
    with pytest.raises(ValidationError):
        sp.set_property(op(conn), "data.deleted.retention_days", "0")
    sp.set_property(op(conn), "data.deleted.retention_days", "30")
    assert sp.get_value(conn, "data.deleted.retention_days") == 30


def test_the_job_is_registered_with_its_own_start_time():
    assert [(job.name, job.time_property) for job in jobs.REGISTRY if job.name == JOB] == [(JOB, "data.deleted.cleanup_time")]


# -- an account, on its own clock --

def test_an_account_past_its_period_goes_with_its_balances_and_all_their_history(conn):
    keep = account(conn, "Live account")
    gone = account(conn, "Gone account", ("2026-01-31", "2026-02-28"))
    ids = [balance_id(conn, gone, d) for d in ("2026-01-31", "2026-02-28")]
    delete_account(conn, gone, 91)
    assert go(conn) == [(JOB, "succeeded")]
    assert not exists(conn, "accounts", gone) and not any(exists(conn, "balances", i) for i in ids)
    assert log_rows(conn, "accounts", gone) == 0 and all(log_rows(conn, "balances", i) == 0 for i in ids)
    assert exists(conn, "accounts", keep) and exists(conn, "balances", balance_id(conn, keep, "2026-01-31"))
    assert log_rows(conn, "accounts", keep) > 0


def test_an_account_inside_its_period_is_left_with_everything(conn):
    gone = account(conn)
    bid = balance_id(conn, gone, "2026-01-31")
    delete_account(conn, gone, 89)
    go(conn)
    assert exists(conn, "accounts", gone) and exists(conn, "balances", bid) and log_rows(conn, "balances", bid) > 0


def test_the_period_is_the_one_set(conn):
    gone = account(conn)
    delete_account(conn, gone, 40)
    go(conn)
    assert exists(conn, "accounts", gone)
    sp.set_property(op(conn), "data.deleted.retention_days", "30")
    conn.commit()
    go(conn, NOW + timedelta(days=1))
    assert not exists(conn, "accounts", gone)


def test_an_account_that_is_not_deleted_is_never_purged_however_old(conn):
    live = account(conn)
    conn.execute("UPDATE accounts SET updated_at = ? WHERE id = ?", (stamp(4000), live))
    conn.commit()
    go(conn)
    assert exists(conn, "accounts", live)


def test_a_balance_deleted_before_its_account_goes_with_the_account(conn):
    gone = account(conn, "Gone account", ("2026-01-31", "2026-02-28"))
    first = balance_id(conn, gone, "2026-01-31")
    delete_balance(conn, first, 5)
    delete_account(conn, gone, 91)
    go(conn)
    assert log_rows(conn, "balances", first) == 0 and log_rows(conn, "accounts", gone) == 0


# -- a balance, on its own clock --

def test_a_balance_deleted_on_its_own_past_its_period_loses_its_history_and_nothing_else(conn):
    acct = account(conn, balances_on=("2026-01-31", "2026-02-28"))
    old, other = balance_id(conn, acct, "2026-01-31"), balance_id(conn, acct, "2026-02-28")
    delete_balance(conn, old, 91)
    before = log_rows(conn, "balances", other)
    go(conn)
    assert log_rows(conn, "balances", old) == 0
    assert exists(conn, "balances", other) and log_rows(conn, "balances", other) == before
    assert exists(conn, "accounts", acct) and log_rows(conn, "accounts", acct) > 0


def test_a_balance_deleted_inside_its_period_stays_recoverable(conn):
    acct = account(conn)
    bid = balance_id(conn, acct, "2026-01-31")
    delete_balance(conn, bid, 10)
    before = log_rows(conn, "balances", bid)
    go(conn)
    assert log_rows(conn, "balances", bid) == before


def test_a_balance_removed_by_an_undo_is_not_purged(conn):
    acct = account(conn)
    bid = balance_id(conn, acct, "2026-01-31")
    writer.delete(Operation(conn, None, "undo"), "balances", bid)
    conn.execute("UPDATE sys_operations SET created_at = ? WHERE id = (SELECT MAX(id) FROM sys_operations)", (stamp(400),))
    conn.commit()
    go(conn)
    assert log_rows(conn, "balances", bid) > 0


# -- a stale selection --

def test_a_record_restored_after_the_list_was_drawn_up_is_not_purged(conn):
    gone = account(conn)
    delete_account(conn, gone, 91)
    before = retention.cutoff(conn, NOW)
    assert retention.expired_accounts(conn, before) == [gone]
    conn.execute("UPDATE accounts SET deleted = 0, updated_at = ? WHERE id = ?", (stamp(0), gone))     # a restore, in between
    conn.commit()
    assert retention.purge_account(conn, gone, before) is False
    assert exists(conn, "accounts", gone) and log_rows(conn, "accounts", gone) > 0


def test_a_balance_put_back_after_the_list_was_drawn_up_is_not_purged(conn):
    acct = account(conn)
    bid = balance_id(conn, acct, "2026-01-31")
    delete_balance(conn, bid, 91)
    before = retention.cutoff(conn, NOW)
    assert retention.expired_balances(conn, before) == [bid]
    restore = Operation(conn, None, "restore")                                                          # a restore writes a new INSERT, same id
    writer.insert(restore, "balances", {"id": bid, "account_id": acct, "as_of_date": "2026-01-31", "amount_cents": 1})
    conn.commit()
    assert retention.purge_balance(conn, bid, before) is False
    assert exists(conn, "balances", bid)


# -- operation headers --

def test_a_header_stays_until_none_of_its_records_remain(conn):
    acct = account(conn, balances_on=("2026-01-31", "2026-02-28"))
    first, second = balance_id(conn, acct, "2026-01-31"), balance_id(conn, acct, "2026-02-28")
    operation = Operation(conn, None, "bulk_update")
    writer.update(operation, "balances", first, {"amount_cents": 7})
    writer.update(operation, "balances", second, {"amount_cents": 8})
    conn.commit()
    header = operation.state["id"]
    delete_balance(conn, first, 91)
    go(conn)
    assert headers(conn, header) == 1
    delete_balance(conn, second, 91)
    go(conn, NOW + timedelta(days=1))
    assert headers(conn, header) == 0


def test_a_header_that_an_undo_names_is_kept(conn):
    acct = account(conn)
    bid = balance_id(conn, acct, "2026-01-31")
    delete_balance(conn, bid, 91)
    header = conn.execute("SELECT operation_id FROM sys_record_changes WHERE tablename = 'balances' AND record_id = ? AND change = 'INSERT'",
                          (bid,)).fetchone()[0]
    conn.execute("INSERT INTO sys_operations (kind, user_id, undoes_operation_id) VALUES ('undo', "
                 "(SELECT id FROM users WHERE is_system = 1), ?)", (header,))
    conn.commit()
    go(conn)
    assert headers(conn, header) == 1


def test_each_purge_leaves_one_header_that_says_which_record_and_nothing_that_was_in_it(conn):
    gone = account(conn, "Secret savings")
    delete_account(conn, gone, 91)
    go(conn)
    [row] = conn.execute("SELECT kind, user_id, detail FROM sys_operations WHERE kind = 'purge'").fetchall()
    assert row["user_id"] == conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]
    assert json.loads(row["detail"]) == {"table": "accounts", "record_id": gone}
    everything = [tuple(r) for r in conn.execute("SELECT * FROM sys_operations")] + [tuple(r) for r in conn.execute("SELECT * FROM sys_record_changes")]
    assert "Secret" not in str(everything)


def test_purging_a_table_that_is_not_purgeable_is_refused(conn):
    with pytest.raises(ValueError):
        writer.purge(Operation(conn, None, "purge"), "users", 1)


# -- the schedule --

def test_with_no_start_time_nothing_runs_and_nothing_is_purged(conn):
    gone = account(conn)
    delete_account(conn, gone, 91)
    conn.execute("UPDATE system_properties SET value = NULL WHERE name = 'data.deleted.cleanup_time'")
    conn.commit()
    assert go(conn) == []
    assert exists(conn, "accounts", gone)


def test_before_the_start_time_nothing_runs(conn):
    gone = account(conn)
    delete_account(conn, gone, 91)
    assert go(conn, NOW - timedelta(hours=2)) == []
    assert exists(conn, "accounts", gone)


def test_a_missed_run_is_made_up_at_the_next_tick(conn):
    gone = account(conn)
    delete_account(conn, gone, 91)
    assert go(conn, NOW + timedelta(hours=9)) == [(JOB, "succeeded")]
    assert not exists(conn, "accounts", gone)


def test_it_runs_once_a_date(conn):
    gone = account(conn)
    delete_account(conn, gone, 91)
    assert go(conn) == [(JOB, "succeeded")]
    assert go(conn, NOW + timedelta(hours=1)) == []


def test_a_period_longer_than_a_date_can_go_back_purges_nothing(conn):
    gone = account(conn)
    delete_account(conn, gone, 4000)
    conn.execute("UPDATE system_properties SET value = '999999999' WHERE name = 'data.deleted.retention_days'")
    conn.commit()
    assert go(conn) == [(JOB, "succeeded")]
    assert exists(conn, "accounts", gone)
