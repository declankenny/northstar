"""Migration 0028 gives account_days the balance id, the balance date and the rate date, and changes nothing else. It is tested on a copy of
a database as the migration before it left it, holding synthetic accounts in every state: the rows the view had, and the Dashboard's
series, must come through unchanged. Synthetic data only."""

import shutil
from datetime import date

import pytest

from conftest import add_account, add_balance, op
from northstar import currencies, db, networth, rates

SYSTEM = "(SELECT id FROM users WHERE is_system = 1)"
TODAY = date(2026, 11, 11)
OLD_COLUMNS = "day, account_id, class_name, currency_id, currency_code, minor_units, converts, amount, rate"


def foreign(conn, name, code, type_name):
    return conn.execute(
        "INSERT INTO accounts (name, type_id, currency_id, created_by, updated_by) VALUES "
        f"(?, (SELECT id FROM account_types WHERE name = ?), (SELECT id FROM currencies WHERE code = ?), {SYSTEM}, {SYSTEM})",
        (name, type_name, code)).lastrowid


@pytest.fixture
def before(tmp_path):
    """A database with every migration but 0028, holding what the view reads, and what it showed: (path, rows, series)."""
    folder = tmp_path / "before"
    folder.mkdir()
    for file in db.MIGRATIONS_DIR.glob("*.sql"):
        if not file.name.startswith(("0028", "0029", "0030")):
            shutil.copy(file, folder)
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path, folder)
    conn = db.connect(path)
    conn.execute("UPDATE system_properties SET value = 'USD', read_only = 1 WHERE name = 'system.currency'")
    conn.execute("UPDATE currencies SET is_enabled = 1 WHERE code = 'USD'")
    for code in ("EUR", "GBP", "JPY"):
        currencies.update_currency(op(conn), code, True, "2020-01-01", TODAY)
    rates.add_rate(op(conn), "EUR", "2026-01-01", "1.10", TODAY)
    rates.add_rate(op(conn), "EUR", "2026-06-01", "1.25", TODAY)
    rates.add_rate(op(conn), "JPY", "2026-03-01", "0.0068", TODAY)
    rates.add_rate(op(conn), "GBP", "2026-05-01", "1.30", TODAY)                       # pounds have a balance from February but no rate until May
    accounts = {
        "dollars": add_account(conn, "Test dollars", 1, "Savings"), "card": add_account(conn, "Test card", 2, "Credit card"),
        "closed": add_account(conn, "Test closed", 1, "Checking"), "deleted": add_account(conn, "Test deleted", 1, "Savings"),
        "euros": foreign(conn, "Test euros", "EUR", "Savings"), "loan": foreign(conn, "Test euro loan", "EUR", "Loan"),
        "yen": foreign(conn, "Test yen", "JPY", "Savings"), "pounds": foreign(conn, "Test pounds", "GBP", "Savings"),
        "empty": add_account(conn, "Test empty", 1, "Savings"),                                  # no balance at all
    }
    for name, day, amount in (("dollars", "2026-01-10", 100_000), ("dollars", "2026-03-01", 150_000), ("card", "2026-02-01", 25_050),
                              ("closed", "2026-01-15", 5_000), ("closed", "2026-04-01", 0), ("deleted", "2026-02-01", 77_700),
                              ("euros", "2026-01-10", 100_000), ("euros", "2026-04-01", 120_000), ("loan", "2026-02-15", 50_005),
                              ("yen", "2026-03-05", 10_000), ("pounds", "2026-02-20", 9_900)):
        add_balance(conn, accounts[name], day, amount)
    conn.execute("UPDATE accounts SET is_open = 0 WHERE id = ?", (accounts["closed"],))
    conn.execute("UPDATE accounts SET deleted = 1 WHERE id = ?", (accounts["deleted"],))
    conn.commit()
    rows = [tuple(r) for r in conn.execute(f"SELECT {OLD_COLUMNS} FROM account_days ORDER BY day, account_id")]
    series = networth.net_worth_series(conn, TODAY, date(2026, 2, 1), date(2026, 9, 30), "week")
    conn.close()
    return path, rows, series, accounts


def test_the_view_has_the_same_rows_and_the_dashboard_the_same_series_after_the_upgrade(before):
    path, rows, series, _ = before
    assert db.upgrade(path) == ["0028_account_days_provenance", "0029_balance_history", "0030_restore_balance_value"]
    conn = db.connect(path)
    assert [tuple(r) for r in conn.execute(f"SELECT {OLD_COLUMNS} FROM account_days ORDER BY day, account_id")] == rows
    assert networth.net_worth_series(conn, TODAY, date(2026, 2, 1), date(2026, 9, 30), "week") == series
    assert len(rows) > 500
    conn.close()


def test_the_old_columns_keep_their_order_and_the_new_ones_follow(before):
    path, *_ = before
    db.upgrade(path)
    conn = db.connect(path)
    columns = [r[1] for r in conn.execute("PRAGMA table_info(account_days)")]
    assert columns == ["day", "account_id", "class_name", "currency_id", "currency_code", "minor_units", "converts", "amount", "rate",
                       "balance_id", "balance_date", "rate_date"]
    conn.close()


def test_every_row_says_which_balance_and_which_rate_it_used(before):
    path, _, _, accounts = before
    db.upgrade(path)
    conn = db.connect(path)
    checked = 0
    for row in conn.execute("SELECT * FROM account_days"):
        latest = conn.execute("SELECT id, as_of_date, amount_cents FROM balances WHERE account_id = ? AND as_of_date <= ? "
                              "ORDER BY as_of_date DESC LIMIT 1", (row["account_id"], row["day"])).fetchone()
        assert (row["balance_id"], row["balance_date"], row["amount"]) == tuple(latest)
        rate = conn.execute("SELECT rate, rate_date FROM exchange_rates WHERE currency_id = ? AND rate_date <= ? "
                            "ORDER BY rate_date DESC LIMIT 1", (row["currency_id"], row["day"])).fetchone()
        assert (row["rate"], row["rate_date"]) == (tuple(rate) if rate else (None, None))
        checked += 1
    assert checked > 500
    early = conn.execute("SELECT DISTINCT rate, rate_date FROM account_days WHERE account_id = ? AND day < '2026-05-01'",
                         (accounts["pounds"],)).fetchall()
    assert [tuple(r) for r in early] == [(None, None)]                        # before the first pound rate: still no rate, as before
    conn.close()


def test_a_deleted_account_and_an_account_with_no_balance_still_have_no_rows(before):
    path, _, _, accounts = before
    db.upgrade(path)
    conn = db.connect(path)
    for name in ("deleted", "empty"):
        assert conn.execute("SELECT COUNT(*) FROM account_days WHERE account_id = ?", (accounts[name],)).fetchone()[0] == 0
    conn.close()


def test_net_worth_on_a_day_is_still_the_hand_calculated_sum_of_the_same_rows(before):
    path, _, _, _ = before
    db.upgrade(path)
    conn = db.connect(path)
    # 15 June: dollars 1,500.00; closed 0; euros 1,200.00 x 1.25 = 1,500.00; yen 10,000 x 0.0068 = $68.00; pounds 99.00 x 1.30 = $128.70;
    # less the card 250.50 and the euro loan 500.05 x 1.25 = 625.06. The deleted account and the empty one count for nothing.
    assert networth.net_worth_on(conn, date(2026, 6, 15)) == {"date": "2026-06-15", "assets": 319_670, "liabilities": 87_556, "net_worth": 232_114}
    conn.close()
