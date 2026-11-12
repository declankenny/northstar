"""Account positions: what each account is worth on a date. Hand-calculated figures, parity of the whole household with
`networth.net_worth_on`, and every edge the design names. Synthetic data only."""

from datetime import date, datetime, timedelta

import pytest

from conftest import add_account, add_balance, op
from northstar import currencies, db, networth, positions, rates
from northstar.errors import ValidationError
from northstar.networth import NoRate
from northstar.positions import AccountPosition, Balance, Rate, account_positions, totals
from northstar.reports.population import FixedPopulation

TODAY = date(2026, 11, 11)
SYSTEM = "(SELECT id FROM users WHERE is_system = 1)"


def add_foreign(conn, name, code, type_name):
    """An account in another currency, which the conftest helper (dollars only) does not make."""
    return conn.execute(
        "INSERT INTO accounts (name, type_id, currency_id, created_by, updated_by) VALUES "
        f"(?, (SELECT id FROM account_types WHERE name = ?), (SELECT id FROM currencies WHERE code = ?), {SYSTEM}, {SYSTEM})",
        (name, type_name, code)).lastrowid


def enable(conn, *codes):
    for code in codes:
        currencies.update_currency(op(conn), code, True, "2020-01-01", TODAY)


@pytest.fixture
def household(conn):
    """Five accounts with hand-calculated worth. Euro rates: 1.10 from 1 January, 1.25 from 1 June.

    usd_sav   asset, dollars:     1,000.00 on 10 Jan, 1,500.00 on 1 Mar
    usd_card  liability, dollars:   250.50 on 1 Feb
    eur_sav   asset, euros:       1,000.00 on 10 Jan, 1,200.00 on 1 Apr
    eur_loan  liability, euros:     500.05 on 15 Feb
    eur_over  asset, euros:        -500.05 on 15 Feb (overdrawn)
    """
    enable(conn, "EUR")
    rates.add_rate(op(conn), "EUR", "2026-01-01", "1.10", TODAY)
    rates.add_rate(op(conn), "EUR", "2026-06-01", "1.25", TODAY)
    ids = {"usd_sav": add_account(conn, "Test dollar savings", 1, "Savings"), "usd_card": add_account(conn, "Test card", 2, "Credit card"),
           "eur_sav": add_foreign(conn, "Test euro savings", "EUR", "Savings"), "eur_loan": add_foreign(conn, "Test euro loan", "EUR", "Loan"),
           "eur_over": add_foreign(conn, "Test euro overdraft", "EUR", "Checking")}
    for name, day, amount in (("usd_sav", "2026-01-10", 100_000), ("usd_sav", "2026-03-01", 150_000), ("usd_card", "2026-02-01", 25_050),
                              ("eur_sav", "2026-01-10", 100_000), ("eur_sav", "2026-04-01", 120_000), ("eur_loan", "2026-02-15", 50_005),
                              ("eur_over", "2026-02-15", -50_005)):
        add_balance(conn, ids[name], day, amount)
    conn.commit()
    return ids


def population(ids, *names):
    return FixedPopulation(ids[name] for name in (names or ids))


def by_name(result_day, ids):
    inverse = {value: key for key, value in ids.items()}
    return {inverse[p.account_id]: p for p in result_day}


def balance_id(conn, account_id, day):
    return conn.execute("SELECT id FROM balances WHERE account_id = ? AND as_of_date = ?", (account_id, day)).fetchone()[0]


# -- hand calculation, with where each figure came from --

def test_positions_are_what_the_balance_is_worth_at_the_rate_on_the_day(conn, household):
    days = [date(2026, 1, 9), date(2026, 1, 10), date(2026, 3, 15), date(2026, 6, 1), date(2026, 11, 11)]
    got = account_positions(conn, population(household), days)
    assert list(got) == days
    names = list(household)

    def values(day):
        return {name: p.value for name, p in by_name(got[day], household).items()}

    assert values(date(2026, 1, 9)) == dict.fromkeys(names, 0)                                    # nothing recorded yet
    assert values(date(2026, 1, 10)) == {"usd_sav": 100_000, "usd_card": 0, "eur_sav": 110_000, "eur_loan": 0, "eur_over": 0}
    # 50,005 x 1.10 = 55,005.5 and rounds away from zero in both directions: 55,006 and -55,006
    assert values(date(2026, 3, 15)) == {"usd_sav": 150_000, "usd_card": 25_050, "eur_sav": 110_000, "eur_loan": 55_006, "eur_over": -55_006}
    # the euro balances are the same facts, valued at 1.25 from 1 June: 120,000 x 1.25 = 150,000 and 50,005 x 1.25 = 62,506.25
    assert values(date(2026, 6, 1)) == {"usd_sav": 150_000, "usd_card": 25_050, "eur_sav": 150_000, "eur_loan": 62_506, "eur_over": -62_506}
    assert values(date(2026, 11, 11)) == values(date(2026, 6, 1))                                    # beyond the data: the last day's answer


def test_a_position_moves_with_the_rate_while_the_balance_it_rests_on_does_not(conn, household):
    before, after = account_positions(conn, population(household, "eur_sav"), [date(2026, 5, 31), date(2026, 6, 1)]).values()
    assert before[0].balance == after[0].balance == Balance(balance_id(conn, household["eur_sav"], "2026-04-01"), 120_000, "2026-04-01")
    assert (before[0].value, after[0].value) == (132_000, 150_000)
    assert before[0].rate == Rate("1.10", "2026-01-01") and after[0].rate == Rate("1.25", "2026-06-01")


def test_each_position_names_the_balance_it_used_and_the_day_it_was_asked(conn, household):
    got = account_positions(conn, population(household), [date(2026, 3, 15)])[date(2026, 3, 15)]
    by = by_name(got, household)
    sav = by["usd_sav"]
    assert sav.balance == Balance(balance_id(conn, household["usd_sav"], "2026-03-01"), 150_000, "2026-03-01")   # the newer of its two balances
    assert sav.rate is None and sav.day == date(2026, 3, 15) and sav.currency_code == "USD" and sav.minor_units == 2
    eur = by["eur_sav"]
    assert eur.balance.as_of_date == "2026-01-10" and eur.rate == Rate("1.10", "2026-01-01")                       # the January balance, still at the 1 January rate
    assert (eur.currency_code, eur.minor_units, eur.class_name) == ("EUR", 2, "Asset")
    assert by["usd_card"].class_name == "Liability"


def test_signed_values_and_totals_follow_the_class(conn, household):
    june = account_positions(conn, population(household), [date(2026, 6, 1)])[date(2026, 6, 1)]
    assert {name: p.signed_value for name, p in by_name(june, household).items()} == {
        "usd_sav": 150_000, "usd_card": -25_050, "eur_sav": 150_000, "eur_loan": -62_506, "eur_over": -62_506}
    # assets 150,000 + 150,000 - 62,506 (the overdrawn asset); liabilities 25,050 + 62,506
    assert totals(june) == positions.Totals(237_494, 87_556, 149_938)
    assert sum(p.signed_value for p in june) == totals(june).net_worth


def test_a_subset_is_worked_out_on_its_own_and_checked_by_hand(conn, household):
    """net_worth_on(account_id) is in the account's own currency and takes no population, so a subset is checked by hand."""
    got = account_positions(conn, population(household, "eur_sav", "usd_card"), [date(2026, 6, 1)])[date(2026, 6, 1)]
    assert totals(got) == positions.Totals(150_000, 25_050, 124_950)
    assert [p.account_id for p in got] == sorted([household["eur_sav"], household["usd_card"]])


# -- the whole household is the Dashboard's net worth --

def test_the_whole_household_equals_net_worth_on_every_day(conn, household):
    start = date(2025, 12, 25)
    days = [start + timedelta(days=n) for n in range(0, 220)] + [date(2026, 11, 11), date(2027, 6, 1)]
    got = account_positions(conn, population(household), days)
    assert set(got) == set(days)
    for day in days:
        expected = networth.net_worth_on(conn, day)
        assert totals(got[day]) == positions.Totals(expected["assets"], expected["liabilities"], expected["net_worth"]), day


def test_the_whole_household_equals_net_worth_with_closed_accounts_and_a_stale_foreign_balance(conn, household):
    conn.execute("UPDATE accounts SET is_open = 0 WHERE id = ?", (household["usd_card"],))
    add_balance(conn, household["usd_card"], "2026-05-01", 0)                                          # closed with a final zero
    conn.commit()
    days = [date(2026, 4, 30), date(2026, 5, 1), date(2026, 9, 1)]
    got = account_positions(conn, population(household), days)
    for day in days:
        expected = networth.net_worth_on(conn, day)
        assert totals(got[day]).net_worth == expected["net_worth"]
    assert by_name(got[date(2026, 5, 1)], household)["usd_card"].value == 0
    assert by_name(got[date(2026, 5, 1)], household)["usd_card"].balance.amount == 0               # a recorded zero is a balance


def test_rounding_goes_away_from_zero_at_the_half_in_both_directions_and_matches_net_worth(conn):
    enable(conn, "EUR")
    rates.add_rate(op(conn), "EUR", "2026-01-01", "0.5", TODAY)
    a = add_foreign(conn, "Test half up", "EUR", "Savings")
    b = add_foreign(conn, "Test half down", "EUR", "Checking")
    add_balance(conn, a, "2026-01-02", 3)         # 3 x 0.5 = 1.5 -> 2
    add_balance(conn, b, "2026-01-02", -3)        # -1.5 -> -2
    conn.commit()
    got = account_positions(conn, FixedPopulation([a, b]), [date(2026, 1, 2)])[date(2026, 1, 2)]
    assert [p.value for p in got] == [2, -2]
    assert totals(got).net_worth == networth.net_worth_on(conn, date(2026, 1, 2))["net_worth"] == 0


def test_an_amount_in_a_currency_with_no_minor_units_is_scaled_to_the_system_currencys(conn):
    enable(conn, "JPY")
    rates.add_rate(op(conn), "JPY", "2026-01-01", "0.0068", TODAY)
    yen = add_foreign(conn, "Test yen", "JPY", "Savings")
    add_balance(conn, yen, "2026-01-02", 10_000)                         # 10,000 yen: no minor units
    conn.commit()
    got = account_positions(conn, FixedPopulation([yen]), [date(2026, 1, 2)])[date(2026, 1, 2)][0]
    assert got.minor_units == 0 and got.value == 6_800                    # $68.00 in cents
    assert got.value == networth.net_worth_on(conn, date(2026, 1, 2))["net_worth"]


# -- no balance, and a recorded zero --

def test_an_account_with_no_balance_yet_is_listed_with_nothing_and_needs_no_rate(conn, household):
    enable(conn, "GBP")
    pounds = add_foreign(conn, "Test pounds", "GBP", "Savings")                 # no balance, and no pound rate exists
    conn.commit()
    got = account_positions(conn, FixedPopulation([pounds]), [date(2026, 3, 1)])[date(2026, 3, 1)][0]
    assert got == AccountPosition(pounds, date(2026, 3, 1), "Asset", "GBP", 2, None, None, 0)


def test_a_recorded_zero_in_another_currency_still_needs_a_rate(conn, household):
    enable(conn, "GBP")
    pounds = add_foreign(conn, "Test pounds", "GBP", "Savings")
    add_balance(conn, pounds, "2026-02-01", 0)
    conn.commit()
    with pytest.raises(NoRate) as error:
        account_positions(conn, FixedPopulation([pounds]), [date(2026, 3, 1)])
    assert error.value.codes == ["GBP"]
    # and a recorded zero in the system currency is a balance that is simply zero
    zero = add_account(conn, "Test zero dollars", 1, "Savings")
    add_balance(conn, zero, "2026-02-01", 0)
    conn.commit()
    got = account_positions(conn, FixedPopulation([zero]), [date(2026, 3, 1)])[date(2026, 3, 1)][0]
    assert got.balance.amount == 0 and got.balance is not None and got.value == 0


# -- a missing rate refuses the whole call --

@pytest.fixture
def uncovered(conn, household):
    """Pounds and francs with balances on 1 February but rates only from 1 March, so 15 February cannot be converted and 1 April can."""
    enable(conn, "GBP", "CHF")
    ids = {"gbp": add_foreign(conn, "Test pounds", "GBP", "Savings"), "chf": add_foreign(conn, "Test francs", "CHF", "Savings")}
    for account in ids.values():
        add_balance(conn, account, "2026-02-01", 10_000)
    rates.add_rate(op(conn), "GBP", "2026-03-01", "1.30", TODAY)
    rates.add_rate(op(conn), "CHF", "2026-03-01", "1.10", TODAY)
    conn.commit()
    return ids


def test_one_day_without_a_rate_fails_the_whole_call_and_names_the_earliest_such_day(conn, household, uncovered):
    everyone = FixedPopulation(list(household.values()) + list(uncovered.values()))
    with pytest.raises(NoRate) as error:
        account_positions(conn, everyone, [date(2026, 4, 1), date(2026, 2, 15), date(2026, 2, 20)])    # an earlier day fails, a later one is covered
    assert error.value.codes == ["CHF", "GBP"] and "Feb 15, 2026" in str(error.value)                  # every currency missing on the first such day
    assert error.value.details == {"missing_rates": ["CHF", "GBP"]}
    covered = account_positions(conn, everyone, [date(2026, 4, 1)])
    assert date(2026, 4, 1) in covered


def test_the_refusal_is_the_same_as_net_worth_for_the_whole_household(conn, household, uncovered):
    everyone = FixedPopulation(list(household.values()) + list(uncovered.values()))
    with pytest.raises(NoRate) as mine:
        account_positions(conn, everyone, [date(2026, 2, 15)])
    with pytest.raises(NoRate) as theirs:
        networth.net_worth_on(conn, date(2026, 2, 15))
    assert str(mine.value) == str(theirs.value) and mine.value.codes == theirs.value.codes


def test_only_the_accounts_in_the_population_can_cause_a_refusal(conn, household, uncovered):
    got = account_positions(conn, population(household, "usd_sav", "eur_sav"), [date(2026, 2, 15)])       # the pounds are not counted
    assert totals(got[date(2026, 2, 15)]).assets == 100_000 + 110_000
    with pytest.raises(NoRate):
        account_positions(conn, FixedPopulation([household["usd_sav"], uncovered["gbp"]]), [date(2026, 2, 15)])


# -- who and what is counted --

def test_positions_come_back_in_account_id_order_for_each_day_oldest_day_first(conn, household):
    got = account_positions(conn, FixedPopulation(sorted(household.values(), reverse=True)), [date(2026, 3, 1), date(2026, 1, 20), date(2026, 3, 1)])
    assert list(got) == [date(2026, 1, 20), date(2026, 3, 1)]                                           # sorted, and asked twice gives one
    for day_positions in got.values():
        ids = [p.account_id for p in day_positions]
        assert ids == sorted(ids) and len(ids) == 5


def test_a_deleted_account_and_an_unknown_id_are_not_counted(conn, household):
    conn.execute("UPDATE accounts SET deleted = 1 WHERE id = ?", (household["usd_card"],))
    conn.commit()
    got = account_positions(conn, FixedPopulation(list(household.values()) + [9999]), [date(2026, 3, 15)])[date(2026, 3, 15)]
    assert household["usd_card"] not in [p.account_id for p in got] and 9999 not in [p.account_id for p in got] and len(got) == 4
    expected = networth.net_worth_on(conn, date(2026, 3, 15))
    assert totals(got).net_worth == expected["net_worth"]


def test_the_class_is_the_one_the_account_has_now(conn, household):
    """An account counts in the class of its type today, for every day, as net worth does."""
    conn.execute("UPDATE accounts SET type_id = (SELECT id FROM account_types WHERE name = 'Loan') WHERE id = ?", (household["usd_sav"],))
    conn.commit()
    got = account_positions(conn, FixedPopulation([household["usd_sav"]]), [date(2026, 1, 10)])[date(2026, 1, 10)][0]
    assert got.class_name == "Liability" and got.signed_value == -100_000
    assert totals([got]).net_worth == networth.net_worth_on(conn, date(2026, 1, 10), household["usd_sav"])["net_worth"] == -100_000


def test_a_household_with_no_balances_has_every_account_listed_and_nothing_valued(conn):
    one = add_account(conn, "Test empty", 1, "Savings")
    conn.commit()
    got = account_positions(conn, FixedPopulation([one]), [date(2026, 3, 1)])[date(2026, 3, 1)]
    assert [(p.balance, p.rate, p.value) for p in got] == [(None, None, 0)]
    assert networth.net_worth_on(conn, date(2026, 3, 1))["net_worth"] == 0


# -- what is asked, and what is read --

def test_no_days_returns_nothing_and_reads_nothing(conn, household):
    statements = []
    conn.set_trace_callback(statements.append)
    assert account_positions(conn, population(household), []) == {}
    assert account_positions(conn, population(household), iter(())) == {}
    assert statements == []


def test_an_empty_population_lists_no_accounts_for_each_day_and_reads_nothing(conn, household):
    statements = []
    conn.set_trace_callback(statements.append)
    assert account_positions(conn, FixedPopulation([]), [date(2026, 3, 1), date(2026, 3, 2)]) == {date(2026, 3, 1): (), date(2026, 3, 2): ()}
    assert statements == []


def test_many_days_are_read_with_one_query_of_the_view(conn, household):
    statements = []
    conn.set_trace_callback(statements.append)
    account_positions(conn, population(household), [date(2026, 1, 1) + timedelta(days=n) for n in range(300)])
    assert sum("balance_id" in s and "FROM account_days" in s for s in statements) == 1        # one read of the positions for all 300 days


def test_too_many_days_and_things_that_are_not_days_are_refused(conn, household):
    start = date(2026, 1, 1)
    account_positions(conn, population(household), [start + timedelta(days=n) for n in range(positions.MAX_DAYS)])
    with pytest.raises(ValidationError, match="at most"):
        account_positions(conn, population(household), [start + timedelta(days=n) for n in range(positions.MAX_DAYS + 1)])
    for bad in ("2026-01-01", datetime(2026, 1, 1, 12), 20260101, None):
        with pytest.raises((ValueError, TypeError)):
            account_positions(conn, population(household), [bad])


def test_an_unset_system_currency_is_refused_with_what_to_do(conn, household):
    conn.execute("UPDATE system_properties SET value = NULL, read_only = 0 WHERE name = 'system.currency'")
    with pytest.raises(ValidationError, match="system currency"):
        account_positions(conn, population(household), [date(2026, 3, 1)])
    assert not conn.in_transaction and conn.execute("PRAGMA query_only").fetchone()[0] == 0


# -- one snapshot, whether or not the caller opened a transaction --

def test_it_opens_its_own_snapshot_when_used_alone_and_leaves_the_connection_as_it_was(conn, household):
    statements = []
    conn.set_trace_callback(statements.append)
    account_positions(conn, population(household), [date(2026, 3, 1)])
    assert sum(s.strip().upper() == "BEGIN" for s in statements) == 1
    assert not conn.in_transaction and conn.execute("PRAGMA query_only").fetchone()[0] == 0


def test_it_joins_a_transaction_the_caller_already_opened(conn, household):
    statements = []
    with db.write_transaction(conn):
        conn.set_trace_callback(statements.append)
        account_positions(conn, population(household), [date(2026, 3, 1)])
        assert conn.in_transaction                                         # still the caller's
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 0        # and writable again for the caller
    assert not any(s.strip().upper() == "BEGIN" for s in statements)
