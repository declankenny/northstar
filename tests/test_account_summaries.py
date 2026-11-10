"""The views behind the Accounts list: last_balances (an account's newest balance) and account_summaries (one row of computed
figures for each live account), and the SQL function northstar_today() that its age and staleness use. Migration 0024 is
tested on a copy of a database as 0023 left it. Synthetic data only; the figures are worked out by hand."""

import shutil
from datetime import date, datetime, timezone

import pytest

from conftest import add_account, add_balance, op, type_id, use_dollars
from northstar import accounts, clock, currencies, db, rates, staleness

TODAY = date(2026, 6, 3)
REAL_TODAY = clock.today          # the clock's own, before a test fixes it
ASSET, LIABILITY = 1, 2


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: TODAY)


def summary(conn, account_id):
    return conn.execute("SELECT * FROM account_summaries WHERE id = ?", (account_id,)).fetchone()


# -- last_balances --

def test_last_balances_holds_each_accounts_newest_balance_by_date_not_by_entry(conn):
    card = add_account(conn, "Test card", LIABILITY, "Credit card")
    add_balance(conn, card, "2026-05-31", 20_000)
    add_balance(conn, card, "2026-01-31", 99_999)         # entered later, dated earlier
    add_balance(conn, card, "2026-03-31", 30_000)
    rows = conn.execute("SELECT as_of_date, amount_cents FROM last_balances WHERE account_id = ?", (card,)).fetchall()
    assert [tuple(r) for r in rows] == [("2026-05-31", 20_000)]


def test_last_balances_has_the_columns_of_live_balances_and_no_row_for_an_account_without_balances(conn):
    empty = add_account(conn, "Test empty", ASSET, "Savings")
    full = add_account(conn, "Test full", ASSET, "Checking")
    add_balance(conn, full, "2026-05-01", 100)
    columns = [r[1] for r in conn.execute("PRAGMA table_info(last_balances)")]
    assert columns == [r[1] for r in conn.execute("PRAGMA table_info(live_balances)")]
    assert [r["account_id"] for r in conn.execute("SELECT account_id FROM last_balances")] == [full]
    assert conn.execute("SELECT COUNT(*) FROM last_balances WHERE account_id = ?", (empty,)).fetchone()[0] == 0


def test_last_balances_leaves_out_a_deleted_account(conn):
    gone = add_account(conn, "Test gone", ASSET, "Savings")
    add_balance(conn, gone, "2026-05-01", 100)
    accounts.delete_account(op(conn), gone)
    assert conn.execute("SELECT COUNT(*) FROM last_balances").fetchone()[0] == 0


def test_a_balance_dated_later_becomes_the_last_and_deleting_it_brings_the_earlier_back(conn):
    account = add_account(conn, "Test checking", ASSET, "Checking")
    add_balance(conn, account, "2026-04-01", 100)
    add_balance(conn, account, "2026-05-01", 200)
    assert summary(conn, account)["last_cents"] == 200
    conn.execute("DELETE FROM balances WHERE as_of_date = '2026-05-01'")
    assert (summary(conn, account)["last_date"], summary(conn, account)["last_cents"]) == ("2026-04-01", 100)


# -- account_summaries --

def test_there_is_one_row_for_each_live_account_closed_and_empty_ones_included(conn):
    ids = [add_account(conn, "Test checking", ASSET, "Checking"), add_account(conn, "Test empty", ASSET, "Savings"),
           add_account(conn, "Test closed", LIABILITY, "Credit card"), add_account(conn, "Test gone", ASSET, "Savings")]
    add_balance(conn, ids[0], "2026-05-01", 100)
    add_balance(conn, ids[2], "2026-01-01", 0)
    add_balance(conn, ids[3], "2026-05-01", 999)
    accounts.close_account(op(conn), ids[2])
    accounts.delete_account(op(conn), ids[3])
    assert sorted(r["id"] for r in conn.execute("SELECT id FROM account_summaries")) == sorted(ids[:3])


def test_the_count_the_last_balance_and_its_date(conn):
    account = add_account(conn, "Test checking", ASSET, "Checking")
    for day, cents in [("2026-03-31", 100), ("2026-04-30", 250), ("2026-05-31", 175)]:
        add_balance(conn, account, day, cents)
    row = summary(conn, account)
    assert (row["balance_count"], row["last_date"], row["last_cents"]) == (3, "2026-05-31", 175)


def test_an_account_with_no_balance_has_a_count_of_zero_and_everything_else_empty(conn):
    account = add_account(conn, "Test empty", ASSET, "Savings")
    row = summary(conn, account)
    assert row["balance_count"] == 0
    assert (row["last_date"], row["last_cents"], row["reporting_value"], row["days_since"]) == (None, None, None, None)
    assert row["is_stale"] == 1                  # an open account with no balance is flagged


def euro_account(conn):
    currencies.update_currency(op(conn), "EUR", True, "2020-01-01", TODAY)
    rates.add_rate(op(conn), "EUR", "2026-03-01", "1.08", TODAY)
    rates.add_rate(op(conn), "EUR", "2026-05-01", "1.10", TODAY)
    euro = conn.execute("SELECT id FROM currencies WHERE code = 'EUR'").fetchone()[0]
    return accounts.add_account(op(conn), "Test euros", ASSET, type_id(conn, "Savings"), None, euro)


def test_the_reporting_value_is_that_of_the_last_balance_by_the_rate_in_force_on_its_date(conn):
    account = euro_account(conn)
    add_balance(conn, account, "2026-03-15", 10_000)       # 1.08, but this is not the last balance
    add_balance(conn, account, "2026-05-10", 123_456)      # 1.10: 123456 x 1.10 = 135801.6, rounded to 135802
    row = summary(conn, account)
    assert (row["last_cents"], row["reporting_value"], row["reporting_scale"], row["reporting_unit"]) == (123_456, 135_802, 2, "USD")


def test_the_reporting_value_is_empty_when_there_is_no_rate_yet_and_the_own_amount_in_the_system_currency(conn):
    account = euro_account(conn)
    add_balance(conn, account, "2026-02-15", 50_000)       # before the first euro rate
    assert summary(conn, account)["reporting_value"] is None
    dollars = add_account(conn, "Test dollars", ASSET, "Checking")
    add_balance(conn, dollars, "2026-05-31", 123_456)
    assert summary(conn, dollars)["reporting_value"] == 123_456


def test_the_reporting_value_agrees_with_live_balance_values_for_every_account(conn):
    euros = euro_account(conn)
    dollars = add_account(conn, "Test dollars", ASSET, "Checking")
    for account, day, cents in [(euros, "2026-03-01", 10_000), (euros, "2026-05-12", -5), (dollars, "2026-05-31", 777)]:
        add_balance(conn, account, day, cents)
    for account in (euros, dollars):
        row = summary(conn, account)
        value = conn.execute("SELECT reporting_value FROM live_balance_values WHERE account_id = ? AND as_of_date = ?",
                             (account, row["last_date"])).fetchone()[0]
        assert row["reporting_value"] == value


# -- age and staleness --

def test_age_and_staleness_by_hand(conn):
    """Today is 3 June 2026. A checking account is stale after 35 days (a starting type), real estate after 365."""
    cases = {
        "same day": ("Checking", "2026-06-03", 0, 0),
        "at the limit": ("Checking", "2026-04-29", 35, 0),         # 35 days: not older than the limit
        "one past the limit": ("Checking", "2026-04-28", 36, 1),
        "a long-lived type, long ago": ("Real estate", "2026-01-01", 153, 0),
        "a long-lived type, past its limit": ("Real estate", "2025-06-02", 366, 1),
    }
    for name, (kind, day, days, stale) in cases.items():
        account = add_account(conn, name, ASSET, kind)
        add_balance(conn, account, day, 100)
        row = summary(conn, account)
        assert (row["days_since"], row["is_stale"]) == (days, stale), name


def test_a_closed_account_is_never_stale_however_old_its_last_balance(conn):
    card = add_account(conn, "Test old card", LIABILITY, "Credit card")
    add_balance(conn, card, "2024-01-01", 0)
    accounts.close_account(op(conn), card)
    row = summary(conn, card)
    assert row["days_since"] == 884 and row["is_stale"] == 0


def test_the_view_and_staleness_py_agree_for_every_account(conn):
    """The rule is written in SQL here and in Python in staleness.py: they must give the same answers."""
    kinds = ["Checking", "Savings", "Real estate", "Brokerage"]
    ids = []
    for number, day in enumerate(["2026-06-03", "2026-05-01", "2026-04-28", "2026-04-29", "2025-06-01", "2025-06-02", None, "2026-06-02"]):
        account = add_account(conn, f"Test account {number}", ASSET, kinds[number % len(kinds)])
        if day:
            add_balance(conn, account, day, 100 + number)
        ids.append(account)
    for account in ids:
        row = summary(conn, account)
        limit = conn.execute("SELECT t.stale_after_days FROM accounts a JOIN account_types t ON t.id = a.type_id WHERE a.id = ?",
                             (account,)).fetchone()[0]
        assert row["days_since"] == staleness.days_since(row["last_date"], TODAY)
        assert bool(row["is_stale"]) == staleness.is_stale(row["last_date"], TODAY, limit)


def test_the_age_follows_a_change_of_the_type_limit(conn):
    account = add_account(conn, "Test checking", ASSET, "Checking")
    add_balance(conn, account, "2026-04-01", 100)             # 63 days old
    assert summary(conn, account)["is_stale"] == 1
    conn.execute("UPDATE account_types SET stale_after_days = 90 WHERE id = ?", (type_id(conn, "Checking"),))
    assert summary(conn, account)["is_stale"] == 0


# -- northstar_today() --

def test_northstar_today_is_the_clocks_today_at_the_moment_it_is_called(conn, monkeypatch):
    assert conn.execute("SELECT northstar_today()").fetchone()[0] == "2026-06-03"
    monkeypatch.setattr(clock, "today", lambda: date(2026, 6, 4))
    assert conn.execute("SELECT northstar_today()").fetchone()[0] == "2026-06-04"


def test_northstar_today_follows_the_installations_time_zone(conn, monkeypatch):
    monkeypatch.setattr(clock, "today", REAL_TODAY)                         # the real today(), with a fixed now()
    monkeypatch.setattr(clock, "now", lambda: datetime(2026, 6, 3, 20, 0, tzinfo=timezone.utc))
    assert conn.execute("SELECT northstar_today()").fetchone()[0] == "2026-06-03"
    clock.set_zone("Pacific/Auckland")                                    # twelve hours ahead of UTC: already the 4th
    assert conn.execute("SELECT northstar_today()").fetchone()[0] == "2026-06-04"


# -- migration 0024, on a copy of a database as 0023 left it --

@pytest.fixture
def before(tmp_path):
    folder = tmp_path / "before"
    folder.mkdir()
    for file in db.MIGRATIONS_DIR.glob("*.sql"):
        if not file.name.startswith("0024"):
            shutil.copy(file, folder)
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path, folder)
    conn = db.connect(path)
    use_dollars_and_accounts(conn)
    conn.commit()
    conn.close()
    return path


def use_dollars_and_accounts(conn):
    use_dollars(conn)
    first = add_account(conn, "Test checking", ASSET, "Checking")
    add_balance(conn, first, "2026-04-01", 100)
    add_balance(conn, first, "2026-05-01", 200)
    gone = add_account(conn, "Test gone", ASSET, "Savings")
    add_balance(conn, gone, "2026-05-01", 999)
    conn.execute("UPDATE accounts SET deleted = 1 WHERE id = ?", (gone,))


def test_the_upgrade_adds_the_two_views_and_changes_no_data(before):
    assert db.upgrade(before) == ["0024_account_summaries"]
    conn = db.connect(before)
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0] == 3
    rows = conn.execute("SELECT balance_count, last_date, last_cents, days_since, is_stale FROM account_summaries").fetchall()
    assert [tuple(r) for r in rows] == [(2, "2026-05-01", 200, 33, 0)]       # 3 June 2026 less 1 May
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
