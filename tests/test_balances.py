from datetime import date

import pytest

from northstar import accounts, balances
from northstar.errors import ValidationError

from conftest import add_account, add_balance

ASSET, LIABILITY = 1, 2
TODAY = date(2026, 10, 30)


def stored(conn, account_id):
    return {r["as_of_date"]: r["amount_cents"] for r in
            conn.execute("SELECT * FROM balances WHERE account_id = ?", (account_id,))}


# -- dates --

def test_parse_date_accepts_today_and_the_past():
    assert balances.parse_date("2026-10-30", TODAY) == TODAY
    assert balances.parse_date(" 2020-02-29 ", TODAY) == date(2020, 2, 29)


@pytest.mark.parametrize("text", ["", None, "10/30/2026", "2026-1-5", "20261030", "2026-02-30",
                                  "2026-W44-5", "yesterday", "٢٠٢٦-١٠-٣٠"])
def test_parse_date_rejects_non_dates(text):
    with pytest.raises(ValidationError, match="valid date"):
        balances.parse_date(text, TODAY)


def test_parse_date_rejects_the_future():
    with pytest.raises(ValidationError, match="future"):
        balances.parse_date("2026-10-31", TODAY)


# -- recording one balance --

def test_record_balance_adds_then_updates_then_reports_unchanged(conn):
    acct = add_account(conn, "Test", ASSET, "Checking")
    d = date(2026, 10, 1)
    assert balances.record_balance(conn, acct, d, 1000) == "added"
    assert balances.record_balance(conn, acct, d, 1000) == "unchanged"
    assert balances.record_balance(conn, acct, d, 1500) == "updated"
    assert stored(conn, acct) == {"2026-10-01": 1500}


def test_unchanged_does_not_touch_updated_at(conn):
    acct = add_account(conn, "Test", ASSET, "Checking")
    balances.record_balance(conn, acct, date(2026, 10, 1), 1000)
    conn.execute("UPDATE balances SET updated_at = '2000-01-01T00:00:00Z'")
    balances.record_balance(conn, acct, date(2026, 10, 1), 1000)
    assert conn.execute("SELECT updated_at FROM balances").fetchone()[0] == "2000-01-01T00:00:00Z"
    balances.record_balance(conn, acct, date(2026, 10, 1), 2000)
    assert conn.execute("SELECT updated_at FROM balances").fetchone()[0] != "2000-01-01T00:00:00Z"


def test_record_balance_refuses_closed_accounts(conn):
    acct = add_account(conn, "Test", ASSET, "Checking")
    accounts.close_account(conn, acct)
    with pytest.raises(ValidationError, match="is closed"):
        balances.record_balance(conn, acct, date(2026, 10, 1), 1000)
    assert stored(conn, acct) == {}


def test_record_balance_refuses_missing_accounts(conn):
    with pytest.raises(ValidationError, match="no longer exists"):
        balances.record_balance(conn, 9999, date(2026, 10, 1), 1000)


def test_negative_and_zero_balances_are_fine(conn):
    acct = add_account(conn, "Test", ASSET, "Checking")
    balances.record_balance(conn, acct, date(2026, 10, 1), -2500)
    balances.record_balance(conn, acct, date(2026, 10, 2), 0)
    assert stored(conn, acct) == {"2026-10-01": -2500, "2026-10-02": 0}


# -- the rows the Update screen shows --

def test_update_rows_show_latest_balance_staleness_and_existing_amount(conn):
    checking = add_account(conn, "Checking", ASSET, "Checking")
    house = add_account(conn, "House", ASSET, "Real estate")
    new = add_account(conn, "New one", ASSET, "Savings")
    add_balance(conn, checking, "2026-08-01", 100)   # 90 days old, limit 35: stale
    add_balance(conn, checking, "2026-09-15", 200)   # 45 days old: still stale
    add_balance(conn, house, "2026-01-01", 30000000)  # 302 days old, limit 365: fine
    rows = {r["name"]: r for r in balances.update_rows(conn, date(2026, 9, 15), TODAY)}
    assert (rows["Checking"]["last_date"], rows["Checking"]["last_cents"]) == ("2026-09-15", 200)
    assert rows["Checking"]["days_since"] == 45 and rows["Checking"]["stale"]
    assert rows["Checking"]["existing_cents"] == 200
    assert rows["House"]["days_since"] == 302 and not rows["House"]["stale"]
    assert rows["House"]["existing_cents"] is None
    assert rows["New one"]["last_date"] is None and rows["New one"]["stale"]


def test_update_rows_leave_out_closed_accounts(conn):
    open_one = add_account(conn, "Open", ASSET, "Checking")
    closed = add_account(conn, "Closed", ASSET, "Savings")
    accounts.close_account(conn, closed)
    assert [r["id"] for r in balances.update_rows(conn, TODAY, TODAY)] == [open_one]


def test_update_rows_are_grouped_by_class(conn):
    add_account(conn, "Z loan", LIABILITY, "Loan")
    add_account(conn, "A checking", ASSET, "Checking")
    assert [r["class_name"] for r in balances.update_rows(conn, TODAY, TODAY)] == ["Asset", "Liability"]


# -- saving a batch --

def test_save_update_skips_blank_rows_and_counts_results(conn):
    a = add_account(conn, "A", ASSET, "Checking")
    b = add_account(conn, "B", ASSET, "Savings")
    c = add_account(conn, "C", LIABILITY, "Loan")
    add_balance(conn, b, "2026-10-30", 500)
    counts = balances.save_update(conn, "2026-10-30", {a: "1,000.50", b: "5.00", c: "   "}, TODAY)
    assert counts == {"added": 1, "updated": 0, "unchanged": 1}
    assert stored(conn, a) == {"2026-10-30": 100050}
    assert stored(conn, c) == {}


def test_save_update_edits_an_existing_date(conn):
    a = add_account(conn, "A", ASSET, "Checking")
    add_balance(conn, a, "2026-10-30", 100)
    assert balances.save_update(conn, "2026-10-30", {a: "2.50"}, TODAY) == {"added": 0, "updated": 1, "unchanged": 0}
    assert stored(conn, a) == {"2026-10-30": 250}


def test_save_update_is_all_or_nothing_and_reports_each_bad_row(conn):
    a = add_account(conn, "A", ASSET, "Checking")
    b = add_account(conn, "B", ASSET, "Savings")
    c = add_account(conn, "C", ASSET, "Brokerage")
    with pytest.raises(balances.EntryErrors) as caught:
        balances.save_update(conn, "2026-10-30", {a: "100", b: "abc", c: "1.234"}, TODAY)
    assert set(caught.value.by_account) == {b, c}
    assert stored(conn, a) == {}      # the good row was not saved either


def test_save_update_rejects_bad_or_future_date_before_looking_at_amounts(conn):
    a = add_account(conn, "A", ASSET, "Checking")
    for bad in ("2026-11-01", "nonsense", ""):
        with pytest.raises(ValidationError) as caught:
            balances.save_update(conn, bad, {a: "abc"}, TODAY)
        assert not isinstance(caught.value, balances.EntryErrors)


def test_save_update_ignores_closed_and_unknown_account_ids(conn):
    a = add_account(conn, "A", ASSET, "Checking")
    closed = add_account(conn, "Closed", ASSET, "Savings")
    accounts.close_account(conn, closed)
    counts = balances.save_update(conn, "2026-10-30", {a: "10", closed: "99", 9999: "5"}, TODAY)
    assert counts["added"] == 1
    assert stored(conn, closed) == {}


def test_save_update_with_nothing_entered_is_not_an_error(conn):
    a = add_account(conn, "A", ASSET, "Checking")
    assert balances.save_update(conn, "2026-10-30", {a: ""}, TODAY) == {"added": 0, "updated": 0, "unchanged": 0}


def test_failure_midway_rolls_back_the_whole_batch(conn, monkeypatch):
    a = add_account(conn, "A", ASSET, "Checking")
    b = add_account(conn, "B", ASSET, "Savings")
    real = balances.record_balance
    calls = []

    def flaky(connection, account_id, as_of, cents, note=None):
        calls.append(account_id)
        if len(calls) == 2:
            raise RuntimeError("disk full")
        return real(connection, account_id, as_of, cents, note)

    monkeypatch.setattr(balances, "record_balance", flaky)
    with pytest.raises(RuntimeError):
        balances.save_update(conn, "2026-10-30", {a: "1", b: "2"}, TODAY)
    assert conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0] == 0
    assert not conn.in_transaction
