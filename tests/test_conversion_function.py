"""The one conversion, and the SQL function that lets a view call it (northstar/conversion.py). Synthetic data only."""

import sqlite3

import pytest

from northstar import backup, conversion, db, networth


def test_net_worth_and_the_database_use_the_same_function():
    assert networth.convert is conversion.convert


@pytest.mark.parametrize("amount, minor_units, rate, system_minor_units, expected", [
    (123_456, 2, "1.10", 2, 135_802),            # 1,234.56 x 1.10 = 1,358.016
    (123_456, 2, "1.08", 2, 133_332),            # 1,333.3248
    (5, 2, "1.10", 2, 6),                        # 0.055: half a cent rounds away from zero
    (1, 2, "0.5", 2, 1),                         # 0.5 of a cent: away from zero (round-half-even would give 0)
    (5, 2, "0.5", 2, 3),                         # 2.5 -> 3 (half-even gives 2)
    (-5, 2, "0.5", 2, -3),                       # -2.5 -> -3 (half-even gives -2)
    (-1, 2, "0.5", 2, -1),                       # -0.5 -> -1
    (-5, 2, "1.10", 2, -6),                      # and so does -0.055, not toward zero
    (5_000, 0, "0.0067", 2, 3_350),              # 5,000 yen at 0.0067 = 33.50 dollars
    (10, 0, "0.0067", 2, 7),                     # 0.067 -> 7 cents
    (100_000, 2, "0.0067", 0, 7),                # dollars into yen: 1,000.00 x 0.0067 = 6.7 -> 7
    (1, 3, "1", 2, 0),                           # 0.001 -> 0.00
    (0, 2, "1.10", 2, 0),                        # a zero is converted like any other amount
    (99_999_999_999_99, 2, "123456789.12345", 2, 1_234_567_891_234_376_543_211),   # the largest amount: no overflow, still exact
])
def test_the_conversion_is_exact_decimal_arithmetic_rounded_half_away_from_zero(amount, minor_units, rate, system_minor_units, expected):
    assert conversion.convert(amount, minor_units, rate, system_minor_units) == expected


@pytest.fixture
def path(tmp_path):
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path)
    return path


def test_every_connection_the_application_opens_can_call_it_from_sql(path):
    conn = db.connect(path)
    assert conn.execute("SELECT northstar_convert(123456, 2, '1.10', 2)").fetchone()[0] == 135_802
    assert conn.execute("SELECT northstar_convert(-5, 2, '1.10', 2)").fetchone()[0] == -6


@pytest.mark.parametrize("arguments", ["NULL, 2, '1.10', 2", "5, NULL, '1.10', 2", "5, 2, NULL, 2", "5, 2, '1.10', NULL"])
def test_a_missing_amount_rate_or_currency_gives_a_missing_answer_never_zero(path, arguments):
    conn = db.connect(path)
    assert conn.execute(f"SELECT northstar_convert({arguments})").fetchone()[0] is None


def test_every_view_in_the_database_can_be_read_through_the_applications_connection(path):
    conn = db.connect(path)
    views = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'")]
    assert {"live_accounts", "live_balances", "account_days", "live_balance_values"} <= set(views)
    for name in views:
        conn.execute(f'SELECT * FROM "{name}" LIMIT 1').fetchall()          # a view that needs a function nobody registered fails here


def test_the_view_that_calls_it_needs_the_applications_connection_and_nothing_else_does(path):
    """A view that calls a function cannot be read without it, and every other way to use the file still works: it can be
    checked, and backed up, by a connection that has not registered anything."""
    plain = sqlite3.connect(path)
    with pytest.raises(sqlite3.OperationalError, match="no such function: northstar_convert"):
        plain.execute("SELECT * FROM live_balance_values").fetchall()
    assert plain.execute("SELECT COUNT(*) FROM live_accounts").fetchone()[0] == 0          # the other views are unaffected
    assert plain.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    plain.close()
    copy = path.parent / "copy.db"
    backup.create_backup(path, copy)
    assert backup.check_database(copy)["migrations"] >= 20
