from datetime import date

import pytest

from northstar import accounts
from northstar.errors import ValidationError

from conftest import add_account, add_balance

ASSET, LIABILITY = 1, 2
TODAY = date(2026, 10, 30)


def test_summary_of_an_account_with_no_balances(conn):
    acct = add_account(conn, "Test", ASSET, "Checking")
    s = accounts.account_summary(conn, acct, TODAY)
    assert (s["name"], s["class_name"], s["type_name"], s["is_open"]) == ("Test", "Asset", "Checking", 1)
    assert (s["balance_count"], s["earliest_date"], s["last_date"], s["last_cents"]) == (0, None, None, None)
    assert s["days_since"] is None and s["stale"]


def test_summary_uses_the_latest_by_date_not_by_entry_order(conn):
    acct = add_account(conn, "Test", ASSET, "Checking")
    add_balance(conn, acct, "2026-10-20", 200)   # entered first, dated later
    add_balance(conn, acct, "2026-01-05", 100)   # entered second, dated earlier
    s = accounts.account_summary(conn, acct, TODAY)
    assert (s["last_date"], s["last_cents"], s["earliest_date"], s["balance_count"]) == (
        "2026-10-20", 200, "2026-01-05", 2)
    assert s["days_since"] == 10 and not s["stale"]


def test_summary_stale_follows_the_types_limit(conn):
    checking = add_account(conn, "Checking", ASSET, "Checking")
    house = add_account(conn, "House", ASSET, "Real estate")
    add_balance(conn, checking, "2026-08-01", 100)   # 90 days, limit 35
    add_balance(conn, house, "2026-01-01", 100)      # 302 days, limit 365
    assert accounts.account_summary(conn, checking, TODAY)["stale"]
    assert not accounts.account_summary(conn, house, TODAY)["stale"]


def test_summary_of_a_closed_account_and_a_liability(conn):
    acct = add_account(conn, "Old card", LIABILITY, "Credit card")
    add_balance(conn, acct, "2025-05-01", 0)      # far older than the 35-day limit
    accounts.close_account(conn, acct)
    s = accounts.account_summary(conn, acct, TODAY)
    assert (s["class_name"], s["is_open"], s["last_cents"]) == ("Liability", 0, 0)
    assert s["days_since"] > 35 and not s["stale"]   # closed accounts are never flagged


def test_closed_account_with_no_balances_is_not_flagged(conn):
    acct = add_account(conn, "Never used", ASSET, "Checking")
    accounts.close_account(conn, acct)
    assert not accounts.account_summary(conn, acct, TODAY)["stale"]


def test_summary_of_missing_account(conn):
    with pytest.raises(ValidationError, match="no longer exists"):
        accounts.account_summary(conn, 9999, TODAY)


def test_history_is_newest_first_and_only_this_accounts(conn):
    a = add_account(conn, "A", ASSET, "Checking")
    b = add_account(conn, "B", ASSET, "Savings")
    for d, c in [("2026-03-01", 3), ("2026-10-01", 10), ("2026-05-01", 5)]:
        add_balance(conn, a, d, c)
    add_balance(conn, b, "2026-07-01", 999)
    rows = accounts.balance_history(conn, a)
    assert [(r["as_of_date"], r["amount_cents"]) for r in rows] == [
        ("2026-10-01", 10), ("2026-05-01", 5), ("2026-03-01", 3)]
    assert all(r["source"] == "manual" for r in rows)


def test_history_of_account_with_no_balances_is_empty(conn):
    assert accounts.balance_history(conn, add_account(conn, "A", ASSET, "Checking")) == []
