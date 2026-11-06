"""Exchange rates, enabling a currency and the conversion of net worth into the system currency. Synthetic data only.

The figures are worked out by hand: each account is converted on its own with the latest rate on or before the date, rounded half
away from zero to a whole minor unit of the system currency (US dollars, in cents, here), and the converted amounts are summed.
"""

import sqlite3
from datetime import date

import pytest

from conftest import add_balance, op, type_id
from northstar import accounts, currencies, networth, rates
from northstar import system_properties as sp
from northstar.errors import NotFoundError, ValidationError
from northstar.locales import get as locale_get
from northstar.money import _US

TODAY = date(2026, 6, 3)
ASSET, LIABILITY = 1, 2


def cid(conn, code):
    return conn.execute("SELECT id FROM currencies WHERE code = ?", (code,)).fetchone()[0]


def switch_on(conn, code, start="2020-01-01"):
    currencies.update_currency(op(conn), code, True, start, TODAY)


def rate(conn, code, day, text):
    return rates.add_rate(op(conn), code, day, text, TODAY)


def account(conn, name, code="EUR", klass=ASSET):
    kind = "Savings" if klass == ASSET else conn.execute("SELECT name FROM account_types WHERE class_id = 2 LIMIT 1").fetchone()[0]
    return accounts.add_account(op(conn), name, klass, type_id(conn, kind), None, cid(conn, code))


def household(conn, code="EUR", first_rate=("2026-05-01", "1.0850")):
    """EUR switched on with one rate, then an account in dollars and one in euros."""
    switch_on(conn, code)
    rate(conn, code, *first_rate)
    return account(conn, "Test dollars", "USD"), account(conn, "Test euros", code)


# -- reading a typed rate --

@pytest.mark.parametrize("typed, stored", [
    ("1.0850", "1.0850"), (" 1.085 ", "1.085"), ("2", "2"), ("0.5", "0.5"), ("007.5", "7.5"), ("1,234.5", "1234.5"),
    ("0.000039510000", "0.000039510000"), ("123456789", "123456789")])
def test_a_typed_rate_is_read_as_exact_decimal_text(typed, stored):
    assert rates.parse_rate(typed) == stored


@pytest.mark.parametrize("typed", ["", "  ", "abc", "1.2.3", "1,2", ".5", "5.", "-1", "0", "0.00", "1e3", "1 000.5", "1.0850000000001",
                                   "1234567890", "1.23456789012345"])
def test_a_rate_that_is_not_a_positive_decimal_is_refused(typed):
    with pytest.raises(ValidationError):
        rates.parse_rate(typed)


def test_a_rate_is_read_in_the_locale_of_the_person(conn):
    german = locale_get(conn, "de-DE")
    assert rates.parse_rate("1.234,5", german) == "1234.5"
    assert rates.parse_rate("1,0850", german) == "1.0850"
    with pytest.raises(ValidationError, match="1,0850"):
        rates.parse_rate("1.0850", german)       # the point is the group mark here, and is not allowed after the decimal
    with pytest.raises(ValidationError, match="Enter a rate like 1.0850"):
        rates.parse_rate("1,0850", _US)


def test_more_than_twelve_significant_digits_or_decimals_are_refused_with_the_limit_in_the_message():
    with pytest.raises(ValidationError, match="at most 12 significant digits"):
        rates.parse_rate("1.2345678901234")


# -- switching a currency on and off --

def test_a_currency_is_switched_on_with_the_date_its_rates_start_from(conn):
    switch_on(conn, "EUR", "2020-01-01")
    row = conn.execute("SELECT is_enabled, rates_start FROM currencies WHERE code = 'EUR'").fetchone()
    assert (row["is_enabled"], row["rates_start"]) == (1, "2020-01-01")


def test_switching_on_without_a_start_date_is_refused_and_nothing_changes(conn):
    with pytest.raises(ValidationError, match="date rates start from"):
        currencies.update_currency(op(conn), "EUR", True, None, TODAY)
    assert conn.execute("SELECT is_enabled FROM currencies WHERE code = 'EUR'").fetchone()[0] == 0


def test_switching_off_keeps_the_start_date_and_switching_on_again_needs_no_new_one(conn):
    switch_on(conn, "EUR", "2021-02-03")
    currencies.update_currency(op(conn), "EUR", False, None, TODAY)
    row = conn.execute("SELECT is_enabled, rates_start FROM currencies WHERE code = 'EUR'").fetchone()
    assert (row["is_enabled"], row["rates_start"]) == (0, "2021-02-03")
    currencies.update_currency(op(conn), "EUR", True, None, TODAY)
    assert conn.execute("SELECT is_enabled FROM currencies WHERE code = 'EUR'").fetchone()[0] == 1


def test_the_start_date_can_be_changed_by_itself_and_cannot_be_in_the_future_or_not_a_date(conn):
    switch_on(conn, "EUR")
    currencies.update_currency(op(conn), "EUR", None, "2018-05-06", TODAY)
    assert conn.execute("SELECT rates_start FROM currencies WHERE code = 'EUR'").fetchone()[0] == "2018-05-06"
    for bad, message in (("2026-06-04", "after today"), ("2026-13-01", "date rates start from"), ("", "date rates start from")):
        with pytest.raises(ValidationError, match=message):
            currencies.update_currency(op(conn), "EUR", None, bad, TODAY)


def test_the_system_currency_is_always_enabled_and_cannot_be_switched_off_or_given_a_start_date(conn):
    assert conn.execute("SELECT is_enabled FROM currencies WHERE code = 'USD'").fetchone()[0] == 1
    with pytest.raises(ValidationError, match="system currency"):
        currencies.update_currency(op(conn), "USD", False, None, TODAY)
    with pytest.raises(ValidationError, match="no rates"):
        currencies.update_currency(op(conn), "USD", None, "2020-01-01", TODAY)
    currencies.update_currency(op(conn), "USD", True, None, TODAY)       # nothing to do, and nothing wrong
    assert conn.execute("SELECT rates_start FROM currencies WHERE code = 'USD'").fetchone()[0] is None


def test_an_unknown_currency_is_not_found(conn):
    with pytest.raises(NotFoundError):
        currencies.update_currency(op(conn), "ZZZ", True, "2020-01-01", TODAY)


def test_switching_on_and_off_is_in_the_change_log(conn):
    switch_on(conn, "EUR", "2020-01-01")
    changes = conn.execute("SELECT new_json FROM sys_record_changes WHERE tablename = 'currencies' AND change = 'UPDATE'").fetchall()
    assert any('"is_enabled": 1' in row["new_json"] and '"rates_start": "2020-01-01"' in row["new_json"] for row in changes)


# -- adding and correcting rates --

def test_a_rate_is_added_for_a_date_and_listed_newest_first_with_what_it_runs_until(conn):
    switch_on(conn, "EUR")
    for day, text in (("2026-05-01", "1.0850"), ("2026-05-12", "1.0840"), ("2026-05-05", "1.0815")):
        rate(conn, "EUR", day, text)
    listed = rates.list_rates(conn, cid(conn, "EUR"))
    assert [(r["date"], r["rate"], r["source"], r["until"]) for r in listed] == [
        ("2026-05-12", "1.0840", "manual", None), ("2026-05-05", "1.0815", "manual", "2026-05-12"),
        ("2026-05-01", "1.0850", "manual", "2026-05-05")]


def test_a_rate_for_a_date_that_already_has_one_is_refused_and_says_to_correct_it(conn):
    switch_on(conn, "EUR")
    rate(conn, "EUR", "2026-05-01", "1.0850")
    with pytest.raises(ValidationError, match="May 1, 2026 already exists. Use Correct"):
        rate(conn, "EUR", "2026-05-01", "1.2")
    assert conn.execute("SELECT COUNT(*) FROM exchange_rates").fetchone()[0] == 1


def test_a_rate_cannot_be_dated_in_the_future_or_be_a_bad_date_or_a_bad_value(conn):
    switch_on(conn, "EUR")
    for day, text, message in (("2026-06-04", "1.1", "after today"), ("not a date", "1.1", "date the rate is for"),
                               ("", "1.1", "date the rate is for"), ("2026-06-01", "0", "greater than zero"),
                               ("2026-06-01", "x", "Enter a rate like")):
        with pytest.raises(ValidationError, match=message):
            rate(conn, "EUR", day, text)
    assert conn.execute("SELECT COUNT(*) FROM exchange_rates").fetchone()[0] == 0


def test_rates_can_be_added_only_while_a_currency_is_enabled_or_has_accounts(conn):
    with pytest.raises(ValidationError, match="Switch on EUR"):
        rate(conn, "EUR", "2026-05-01", "1.0850")
    household(conn)
    currencies.update_currency(op(conn), "EUR", False, None, TODAY)           # off, but an account still uses it
    rate(conn, "EUR", "2026-05-12", "1.0840")
    assert conn.execute("SELECT COUNT(*) FROM exchange_rates").fetchone()[0] == 2


def test_the_system_currency_takes_no_rates(conn):
    with pytest.raises(ValidationError, match="needs no rates"):
        rate(conn, "USD", "2026-05-01", "1")


def test_a_rate_is_added_in_the_locale_the_form_was_using_and_refused_if_that_is_not_the_saved_one(conn):
    switch_on(conn, "EUR")
    with pytest.raises(ValidationError, match="number and date format changed"):
        rates.add_rate(op(conn), "EUR", "2026-05-01", "1,0850", TODAY, "de-DE")
    assert conn.execute("SELECT COUNT(*) FROM exchange_rates").fetchone()[0] == 0
    rates.add_rate(op(conn), "EUR", "2026-05-01", "1.0850", TODAY, "en-US")
    assert conn.execute("SELECT rate FROM exchange_rates").fetchone()[0] == "1.0850"


def test_a_correction_changes_the_value_and_makes_the_source_manual_and_nothing_else(conn):
    switch_on(conn, "EUR")
    rate_id = rate(conn, "EUR", "2026-05-01", "1.0850")
    conn.execute("UPDATE exchange_rates SET source = 'provider'")
    rates.correct_rate(op(conn), "EUR", rate_id, "1.09")
    row = conn.execute("SELECT currency_id, rate_date, rate, source FROM exchange_rates").fetchone()
    assert (row["currency_id"], row["rate_date"], row["rate"], row["source"]) == (cid(conn, "EUR"), "2026-05-01", "1.09", "manual")
    log = conn.execute("SELECT old_json, new_json FROM sys_record_changes WHERE tablename = 'exchange_rates' AND change = 'UPDATE'").fetchall()
    assert '"rate": "1.0850"' in log[-1]["old_json"] and '"rate": "1.09"' in log[-1]["new_json"]


def test_a_correction_of_a_rate_of_another_currency_or_one_that_does_not_exist_is_not_found(conn):
    switch_on(conn, "EUR")
    switch_on(conn, "GBP")
    rate_id = rate(conn, "EUR", "2026-05-01", "1.0850")
    with pytest.raises(NotFoundError):
        rates.correct_rate(op(conn), "GBP", rate_id, "1.2")
    with pytest.raises(NotFoundError):
        rates.correct_rate(op(conn), "EUR", 9999, "1.2")


def test_the_database_refuses_to_delete_a_rate_or_change_its_date_or_currency(conn):
    switch_on(conn, "EUR")
    rate(conn, "EUR", "2026-05-01", "1.0850")
    for sql in ("DELETE FROM exchange_rates", "UPDATE exchange_rates SET rate_date = '2026-05-02'",
                f"UPDATE exchange_rates SET currency_id = {cid(conn, 'GBP')}"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql)
    for bad in ("0", "00.0", "1.2.3", "-1", "1e5", ".5", "5.", "x"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO exchange_rates (currency_id, rate_date, rate, source, created_by, updated_by) "
                         "VALUES (?, '2026-05-02', ?, 'manual', 1, 1)", (cid(conn, "EUR"), bad))


def test_an_account_in_a_currency_needs_it_switched_on_and_a_stored_rate(conn):
    with pytest.raises(ValidationError, match="Choose a currency that is enabled"):
        account(conn, "Test euros")
    switch_on(conn, "EUR")
    with pytest.raises(ValidationError, match="no exchange rate yet"):
        account(conn, "Test euros")
    rate(conn, "EUR", "2026-05-01", "1.0850")
    assert currencies.account_currency(conn, account(conn, "Test euros")).code == "EUR"


# -- the currency page --

def test_the_page_of_a_currency_has_its_state_its_rates_and_whether_rates_can_be_added(conn):
    page = rates.currency_page(conn, "EUR", TODAY)
    assert (page["is_enabled"], page["can_add_rates"], page["is_system"], page["rates"], page["stale"]) == (False, False, False, [], None)
    assert (page["system_code"], page["rates_start"], page["default_rates_start"]) == ("USD", None, "2000-01-01")
    household(conn)
    page = rates.currency_page(conn, "EUR", TODAY)
    assert (page["is_enabled"], page["can_add_rates"], page["rates_start"], page["account_count"]) == (True, True, "2020-01-01", 1)
    usd = rates.currency_page(conn, "USD", TODAY)
    assert (usd["is_enabled"], usd["is_system"], usd["can_add_rates"], usd["account_count"]) == (True, True, False, 1)


def test_a_currency_with_an_account_can_have_rates_added_after_it_is_switched_off(conn):
    household(conn)
    currencies.update_currency(op(conn), "EUR", False, None, TODAY)
    assert rates.currency_page(conn, "EUR", TODAY)["can_add_rates"] is True


def test_the_page_warns_of_stale_rates_only_past_the_threshold_and_only_with_an_open_account(conn):
    _, euros = household(conn, first_rate=("2026-05-20", "1.0850"))          # 14 days before 2026-06-03
    assert rates.currency_page(conn, "EUR", TODAY)["stale"] is None
    assert rates.currency_page(conn, "EUR", date(2026, 6, 4))["stale"] == {"last_date": "2026-05-20", "days": 15, "threshold": 14}
    sp.set_property(op(conn), "currency.rate.stale_days", "30")
    assert rates.currency_page(conn, "EUR", date(2026, 6, 4))["stale"] is None
    sp.set_property(op(conn), "currency.rate.stale_days", "14")
    conn.execute("UPDATE accounts SET is_open = 0 WHERE id = ?", (euros,))
    assert rates.currency_page(conn, "EUR", date(2026, 6, 4))["stale"] is None


def test_an_unknown_currency_has_no_page(conn):
    with pytest.raises(NotFoundError):
        rates.currency_page(conn, "ZZZ", TODAY)


# -- converting --

@pytest.mark.parametrize("amount, minor, rate_text, system_minor, expected", [
    (10000, 2, "1.0850", 2, 10850),           # 100.00 EUR at 1.0850
    (5, 2, "1.5", 2, 8),                      # 7.5 cents is halfway: away from zero
    (-5, 2, "1.5", 2, -8),                    # and the same for a negative amount
    (4, 2, "1.5", 2, 6),                      # 6.0 exactly
    (1, 2, "1.4", 2, 1), (1, 2, "1.6", 2, 2), (-1, 2, "1.4", 2, -1), (-1, 2, "1.6", 2, -2),
    (1000, 0, "0.0067", 2, 670),              # 1,000 yen is 6.70 dollars: 0 decimals into 2
    (15, 3, "1.0", 2, 2), (-15, 3, "1.0", 2, -2),   # 0.015 dinars is 1.5 cents: 3 decimals into 2, halfway
    (1234, 3, "3.25", 2, 401),                # 1.234 KWD at 3.25 is 4.0105 dollars
    (10000, 2, "150.5", 0, 15050),            # into a currency with no decimals: 100.00 at 150.5 is 15,050 yen
    (0, 2, "1.0850", 2, 0),
    (9_999_999_999_999, 2, "1.000000000001", 2, 10_000_000_000_009),   # the ceiling, times a rate with 12 decimals
    (9_999_999_999_999, 2, "1000000", 2, 9_999_999_999_999_000_000),   # past what a 64-bit integer holds, and exact
])
def test_conversion_is_exact_and_rounds_half_away_from_zero(amount, minor, rate_text, system_minor, expected):
    assert networth.convert(amount, minor, rate_text, system_minor) == expected


def test_net_worth_adds_each_account_converted_on_its_own(conn):
    dollars, euros = household(conn)
    add_balance(conn, dollars, "2026-01-01", 100000)
    add_balance(conn, euros, "2026-05-01", 10000)
    assert networth.net_worth_on(conn, date(2026, 5, 1)) == {
        "date": "2026-05-01", "assets": 110850, "liabilities": 0, "net_worth": 110850}


def test_each_account_is_rounded_by_itself_and_not_the_sum(conn):
    _, first = household(conn, first_rate=("2026-05-01", "1.5"))
    second = account(conn, "Test euros two")
    add_balance(conn, first, "2026-05-01", 5)         # 7.5 cents, rounded to 8
    add_balance(conn, second, "2026-05-01", 5)        # 8 again: summed first it would be 15
    assert networth.net_worth_on(conn, date(2026, 5, 1))["assets"] == 16


def test_a_liability_in_a_currency_is_converted_and_taken_off(conn):
    switch_on(conn, "EUR")
    rate(conn, "EUR", "2026-05-01", "1.5")
    debt = account(conn, "Test card", "EUR", LIABILITY)
    assets = account(conn, "Test euros")
    add_balance(conn, debt, "2026-05-01", 5)
    add_balance(conn, assets, "2026-05-01", -5)
    assert networth.net_worth_on(conn, date(2026, 5, 1)) == {
        "date": "2026-05-01", "assets": -8, "liabilities": 8, "net_worth": -16}


def test_the_latest_rate_on_or_before_the_date_is_used_and_never_a_later_one(conn):
    switch_on(conn, "EUR")
    rate(conn, "EUR", "2026-02-01", "1.1")
    rate(conn, "EUR", "2026-03-01", "1.2")
    euros = account(conn, "Test euros")
    add_balance(conn, euros, "2026-02-01", 10000)
    assert networth.net_worth_on(conn, date(2026, 2, 28))["net_worth"] == 11000
    assert networth.net_worth_on(conn, date(2026, 3, 1))["net_worth"] == 12000
    assert networth.net_worth_on(conn, date(2026, 4, 15))["net_worth"] == 12000


def test_a_date_with_no_rate_has_no_net_worth_and_says_which_currency(conn):
    household(conn)
    euros = conn.execute("SELECT id FROM accounts WHERE name = 'Test euros'").fetchone()[0]
    add_balance(conn, euros, "2026-04-15", 10000)
    with pytest.raises(networth.NoRate, match="no EUR rate on or before Apr 30, 2026") as caught:
        networth.net_worth_on(conn, date(2026, 4, 30))
    assert caught.value.codes == ["EUR"] and caught.value.details == {"missing_rates": ["EUR"]}


def test_a_zero_balance_needs_a_rate_like_any_other(conn):
    household(conn)
    euros = conn.execute("SELECT id FROM accounts WHERE name = 'Test euros'").fetchone()[0]
    add_balance(conn, euros, "2026-04-15", 0)
    with pytest.raises(networth.NoRate):
        networth.net_worth_on(conn, date(2026, 4, 30))
    assert networth.net_worth_on(conn, date(2026, 5, 1))["net_worth"] == 0


def test_a_date_after_the_newest_balance_and_rate_is_answered_with_the_last_day(conn):
    dollars, euros = household(conn)
    add_balance(conn, dollars, "2026-01-01", 100000)
    add_balance(conn, euros, "2026-05-01", 10000)
    assert networth.net_worth_on(conn, date(2026, 6, 3))["net_worth"] == 110850
    assert networth.net_worth_on(conn, date(2026, 6, 3))["date"] == "2026-06-03"
    assert networth.net_worth_on(conn, date(2025, 12, 31))["net_worth"] == 0         # before the first balance


def test_a_correction_changes_what_a_date_was_worth_and_not_the_balances(conn):
    dollars, euros = household(conn)
    add_balance(conn, euros, "2026-05-01", 10000)
    before = conn.execute("SELECT account_id, as_of_date, amount_cents FROM balances ORDER BY id").fetchall()
    rates.correct_rate(op(conn), "EUR", conn.execute("SELECT id FROM exchange_rates").fetchone()[0], "1.2")
    assert networth.net_worth_on(conn, date(2026, 5, 1))["net_worth"] == 12000
    assert conn.execute("SELECT account_id, as_of_date, amount_cents FROM balances ORDER BY id").fetchall() == before


def test_a_deleted_account_counts_for_nothing_and_does_not_move_the_calendar(conn):
    dollars, euros = household(conn)
    add_balance(conn, euros, "2026-05-01", 10000)
    gone = account(conn, "Test gone")
    add_balance(conn, gone, "2025-01-01", 500)
    conn.execute("UPDATE accounts SET deleted = 1 WHERE id = ?", (gone,))
    assert conn.execute("SELECT MIN(day) FROM account_days").fetchone()[0] == "2026-05-01"
    assert networth.net_worth_on(conn, date(2026, 5, 1))["net_worth"] == 10850


# -- one account is in its own currency --

def test_a_single_account_is_in_its_own_currency_with_no_rate_needed(conn):
    household(conn)
    euros = conn.execute("SELECT id FROM accounts WHERE name = 'Test euros'").fetchone()[0]
    add_balance(conn, euros, "2026-04-15", 10000)
    assert networth.net_worth_on(conn, date(2026, 4, 20), euros) == {
        "date": "2026-04-20", "assets": 10000, "liabilities": 0, "net_worth": 10000}
    series = networth.net_worth_series(conn, TODAY, account_id=euros)
    assert series["limited"] is None and series["start"] == "2026-04-15"
    assert [p["net_worth"] for p in series["series"]] == [10000] * 4          # Apr 15, Apr 30, May 31 and Jun 3


# -- the series --

def gap_in_the_middle(conn):
    """Dollars from January, euros from March, and the first euro rate in May: March and April cannot be converted, January and
    February can, and the series cannot start before May."""
    switch_on(conn, "EUR")
    rate(conn, "EUR", "2026-05-01", "1.0850")
    dollars, euros = account(conn, "Test dollars", "USD"), account(conn, "Test euros")
    add_balance(conn, dollars, "2026-01-01", 100000)
    add_balance(conn, euros, "2026-03-01", 10000)


def test_the_series_starts_at_the_first_date_from_which_every_later_date_can_be_converted(conn):
    gap_in_the_middle(conn)
    result = networth.net_worth_series(conn, TODAY)
    assert result["limited"] == {"starts_on": "2026-05-01", "currencies": ["EUR"]}
    assert result["start"] == "2026-05-01"
    assert [(p["date"], p["net_worth"]) for p in result["series"]] == [
        ("2026-05-01", 110850), ("2026-05-31", 110850), ("2026-06-03", 110850)]


def test_a_start_after_the_gap_is_not_limited_and_one_inside_it_is(conn):
    gap_in_the_middle(conn)
    after = networth.net_worth_series(conn, TODAY, start=date(2026, 5, 15))
    assert after["limited"] is None and after["series"][0]["date"] == "2026-05-15"
    inside = networth.net_worth_series(conn, TODAY, start=date(2026, 4, 1))
    assert inside["limited"] == {"starts_on": "2026-05-01", "currencies": ["EUR"]} and inside["series"][0]["date"] == "2026-05-01"
    before = networth.net_worth_series(conn, TODAY, start=date(2026, 1, 1))
    assert before["start"] == "2026-05-01"


def test_a_series_ending_inside_the_gap_is_empty_and_says_which_currency(conn):
    gap_in_the_middle(conn)
    result = networth.net_worth_series(conn, TODAY, end=date(2026, 4, 20))
    assert result["series"] == [] and result["limited"] == {"starts_on": None, "currencies": ["EUR"]}


def test_a_series_is_empty_when_no_date_up_to_the_end_can_be_converted(conn):
    switch_on(conn, "EUR")
    rate(conn, "EUR", "2026-05-01", "1.0850")
    euros = account(conn, "Test euros")
    add_balance(conn, euros, "2026-05-20", 10000)
    conn.execute("DROP TRIGGER exchange_rates_never_deleted")
    conn.execute("DELETE FROM exchange_rates")
    conn.execute("INSERT INTO exchange_rates (currency_id, rate_date, rate, source, created_by, updated_by) "
                 "VALUES (?, '2026-06-10', '1.1', 'manual', 1, 1)", (cid(conn, "EUR"),))      # a rate dated after today
    result = networth.net_worth_series(conn, TODAY)
    assert result["series"] == [] and result["limited"] == {"starts_on": None, "currencies": ["EUR"]}


def test_a_series_with_everything_covered_is_not_limited(conn):
    dollars, euros = household(conn)
    add_balance(conn, dollars, "2026-05-01", 100000)
    add_balance(conn, euros, "2026-05-01", 10000)
    result = networth.net_worth_series(conn, TODAY)
    assert result["limited"] is None and result["start"] == "2026-05-01"


def test_a_household_in_one_currency_has_no_rates_and_is_unchanged(conn):
    dollars = account(conn, "Test dollars", "USD")
    add_balance(conn, dollars, "2026-01-01", 123456)
    result = networth.net_worth_series(conn, TODAY)
    assert result["limited"] is None and result["series"][-1]["net_worth"] == 123456
