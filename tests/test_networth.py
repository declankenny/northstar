"""Net worth against a hand calculation (the spec's acceptance test).

The dataset below is synthetic. The expected numbers were worked out by hand, line by line, and
are written next to the data so anyone can check them without running anything.

Accounts                          Class
  Checking                        Asset
  Savings                         Asset
  House                           Asset
  Old account (closed in March)   Asset
  Mortgage                        Liability
  Card                            Liability

Balances, in dollars (the latest on or before a date is what counts on that date)

  date        account      amount
  2026-01-01  House        400,000.00
  2026-01-01  Mortgage     250,000.00
  2026-01-31  Checking       1,200.00
  2026-01-31  Savings        5,000.00
  2026-01-31  Old account      300.00
  2026-02-28  Checking       1,350.50
  2026-02-28  Card             400.00
  2026-03-31  Old account        0.00      (then closed)
  2026-03-31  Savings        5,100.00
  2026-03-31  Mortgage     249,000.00
  2026-04-30  Checking         -75.25      (overdrawn: a negative asset)
  2026-04-30  Savings        5,200.00
  2026-04-30  Card             -20.00      (overpaid: a negative liability)
  2026-06-15  House        410,000.00

Hand calculation on each date a balance was entered: assets, liabilities, net worth

  2026-01-01  assets  400,000.00
              liab.   250,000.00
              net     150,000.00

  2026-01-31  assets  406,500.00 = 400,000 + 1,200 + 5,000 + 300
              liab.   250,000.00
              net     156,500.00

  2026-02-28  assets  406,650.50 = 400,000 + 1,350.50 + 5,000 + 300
              liab.   250,400.00 = 250,000 + 400
              net     156,250.50

  2026-03-31  assets  406,450.50 = 400,000 + 1,350.50 + 5,100 + 0
              liab.   249,400.00 = 249,000 + 400
              net     157,050.50

  2026-04-30  assets  405,124.75 = 400,000 - 75.25 + 5,200 + 0
              liab.   248,980.00 = 249,000 - 20
              net     156,144.75

  2026-06-15  assets  415,124.75 = 410,000 - 75.25 + 5,200 + 0
              liab.   248,980.00
              net     166,144.75

Hand calculation at each month end, with today = 2026-10-30
(a month with no entries carries the previous month's numbers forward)

  Jan 31   same as 2026-01-31 above         net 156,500.00   (the 01-01 state is not shown)
  Feb 28   same as 2026-02-28 above         net 156,250.50
  Mar 31   same as 2026-03-31 above         net 157,050.50
  Apr 30   same as 2026-04-30 above         net 156,144.75
  May 31   nothing entered: April carries   net 156,144.75
  Jun 30   includes the 06-15 entry         net 166,144.75
  Jul 31   carried forward                  net 166,144.75
  Aug 31   carried forward                  net 166,144.75
  Sep 30   carried forward                  net 166,144.75
  Oct 30   the current month, to date       net 166,144.75
"""

from datetime import date

import pytest

from northstar import accounts, balances, networth

from conftest import add_account, add_balance

ASSET, LIABILITY = 1, 2
TODAY = date(2026, 10, 30)

# (date, assets, liabilities, net worth) in cents, from the first hand calculation above.
ON_ENTRY_DATES = [
    ("2026-01-01", 40000000, 25000000, 15000000),
    ("2026-01-31", 40650000, 25000000, 15650000),
    ("2026-02-28", 40665050, 25040000, 15625050),
    ("2026-03-31", 40645050, 24940000, 15705050),
    ("2026-04-30", 40512475, 24898000, 15614475),
    ("2026-06-15", 41512475, 24898000, 16614475),
]

# (month end, assets, liabilities, net worth, partial) in cents, from the second hand calculation.
MONTH_ENDS = [
    ("2026-01-31", 40650000, 25000000, 15650000, False),
    ("2026-02-28", 40665050, 25040000, 15625050, False),
    ("2026-03-31", 40645050, 24940000, 15705050, False),
    ("2026-04-30", 40512475, 24898000, 15614475, False),
    ("2026-05-31", 40512475, 24898000, 15614475, False),
    ("2026-06-30", 41512475, 24898000, 16614475, False),
    ("2026-07-31", 41512475, 24898000, 16614475, False),
    ("2026-08-31", 41512475, 24898000, 16614475, False),
    ("2026-09-30", 41512475, 24898000, 16614475, False),
    ("2026-10-30", 41512475, 24898000, 16614475, True),
]


@pytest.fixture
def household(conn):
    ids = {
        "checking": add_account(conn, "Checking", ASSET, "Checking"),
        "savings": add_account(conn, "Savings", ASSET, "Savings"),
        "house": add_account(conn, "House", ASSET, "Real estate"),
        "old": add_account(conn, "Old account", ASSET, "Savings"),
        "mortgage": add_account(conn, "Mortgage", LIABILITY, "Mortgage"),
        "card": add_account(conn, "Card", LIABILITY, "Credit card"),
    }
    data = [
        ("2026-01-01", "house", 40000000), ("2026-01-01", "mortgage", 25000000),
        ("2026-01-31", "checking", 120000), ("2026-01-31", "savings", 500000), ("2026-01-31", "old", 30000),
        ("2026-02-28", "checking", 135050), ("2026-02-28", "card", 40000),
        ("2026-03-31", "old", 0), ("2026-03-31", "savings", 510000), ("2026-03-31", "mortgage", 24900000),
        ("2026-04-30", "checking", -7525), ("2026-04-30", "savings", 520000), ("2026-04-30", "card", -2000),
        ("2026-06-15", "house", 41000000),
    ]
    for when, name, cents in data:
        add_balance(conn, ids[name], when, cents)
    accounts.close_account(conn, ids["old"])      # its final balance is zero, so this is allowed
    return ids


def month_rows(conn, today=TODAY):
    return [(r["date"], r["assets"], r["liabilities"], r["net_worth"], r["partial"])
            for r in networth.net_worth_by_month(conn, today)]


def reference_net_worth(conn, day: date) -> tuple[int, int, int]:
    """The obvious, slow way, in plain Python, used only to check net_worth_on.

    For every account, take its balances up to the day, pick the one with the latest date, and
    add it to its class. No SQL tricks, so a mistake in net_worth_on's query can't be shared.
    """
    assets = liabilities = 0
    for account in conn.execute(
            "SELECT a.id, c.name AS class_name FROM accounts a JOIN account_classes c ON c.id = a.class_id"):
        eligible = [(r["as_of_date"], r["amount_cents"]) for r in conn.execute(
            "SELECT as_of_date, amount_cents FROM balances WHERE account_id = ?", (account["id"],))
            if r["as_of_date"] <= day.isoformat()]
        if not eligible:
            continue
        _, cents = max(eligible)
        if account["class_name"] == "Asset":
            assets += cents
        else:
            liabilities += cents
    return assets, liabilities, assets - liabilities


# -- the acceptance tests --

def test_month_end_series_matches_the_hand_calculation(conn, household):
    assert month_rows(conn) == MONTH_ENDS


def test_each_entry_date_matches_the_hand_calculation(conn, household):
    for when, assets, liabilities, net in ON_ENTRY_DATES:
        got = networth.net_worth_on(conn, date.fromisoformat(when))
        assert (got["assets"], got["liabilities"], got["net_worth"]) == (assets, liabilities, net)


def test_net_worth_on_agrees_with_the_plain_python_reference_on_every_day(conn, household):
    day = date(2025, 12, 1)
    while day <= date(2027, 1, 31):
        got = networth.net_worth_on(conn, day)
        assert (got["assets"], got["liabilities"], got["net_worth"]) == reference_net_worth(conn, day), day
        day = date.fromordinal(day.toordinal() + 1)


# -- carry-forward --

@pytest.mark.parametrize("when, expected_net", [
    ("2026-01-15", 15000000),    # between two dates: the 01-01 state carries forward
    ("2026-03-01", 15625050),    # the day after 02-28
    ("2026-05-20", 15614475),    # between 04-30 and 06-15
    ("2026-12-31", 16614475),    # long after the last balance
])
def test_dates_between_balances_carry_the_latest_forward(conn, household, when, expected_net):
    assert networth.net_worth_on(conn, date.fromisoformat(when))["net_worth"] == expected_net


def test_before_any_balance_everything_is_zero(conn, household):
    got = networth.net_worth_on(conn, date(2025, 12, 31))
    assert (got["assets"], got["liabilities"], got["net_worth"]) == (0, 0, 0)


def test_balances_after_the_chosen_date_are_ignored(conn, household):
    assert networth.net_worth_on(conn, date(2026, 3, 30))["net_worth"] == 15625050
    assert month_rows(conn, today=date(2026, 3, 31)) == MONTH_ENDS[:3]


def test_an_account_with_no_balance_yet_contributes_nothing(conn, household):
    add_account(conn, "Brand new", ASSET, "Brokerage")
    assert month_rows(conn) == MONTH_ENDS


# -- special cases from the rules --

def test_closing_an_account_does_not_change_any_number(conn, household):
    """The 'Old account' was closed in the fixture. Its final zero simply carries forward."""
    assert accounts.get_account(conn, household["old"])["is_open"] == 0
    assert month_rows(conn) == MONTH_ENDS
    accounts.reopen_account(conn, household["old"])
    assert month_rows(conn) == MONTH_ENDS


def test_negative_balances_on_either_class(conn, household):
    got = networth.net_worth_on(conn, date(2026, 4, 30))
    # Checking is -75.25 (reduces assets) and Card is -20.00 (reduces what is owed).
    assert got["assets"] == 40512475 and got["liabilities"] == 24898000


def test_several_balances_in_one_month_make_one_row(conn, household):
    rows = networth.net_worth_by_month(conn, TODAY)
    assert len(rows) == 10 and len({r["date"] for r in rows}) == 10


def test_mid_month_entries_are_folded_into_the_month_end(conn, household):
    """The 06-15 house revaluation is not a row of its own: it shows in June's month end."""
    dates = [r["date"] for r in networth.net_worth_by_month(conn, TODAY)]
    assert "2026-06-15" not in dates and "2026-01-01" not in dates


def test_changing_an_accounts_class_changes_past_net_worth(conn, household):
    """The spec's rule: editing a class rewrites history. Card becomes an asset."""
    other_asset = conn.execute("SELECT id FROM account_types WHERE name = 'Other asset'").fetchone()["id"]
    accounts.change_class(conn, household["card"], other_asset)
    got = networth.net_worth_on(conn, date(2026, 2, 28))
    # assets 406,650.50 + card 400.00 = 407,050.50 ; liabilities 250,000.00 ; net 157,050.50
    assert (got["assets"], got["liabilities"], got["net_worth"]) == (40705050, 25000000, 15705050)
    feb = {r["date"]: r for r in networth.net_worth_by_month(conn, TODAY)}["2026-02-28"]
    assert feb["net_worth"] == 15705050


def test_editing_and_deleting_balances_changes_the_numbers(conn, household):
    # Move the March mortgage balance to the 15th: from the 15th the mortgage is 249,000.
    row = conn.execute("SELECT id FROM balances WHERE account_id = ? AND as_of_date = '2026-03-31'",
                       (household["mortgage"],)).fetchone()["id"]
    balances.update_balance(conn, row, "2026-03-15", "249,000.00", None, TODAY)
    assert networth.net_worth_on(conn, date(2026, 3, 14))["liabilities"] == 25000000 + 40000
    assert networth.net_worth_on(conn, date(2026, 3, 15))["liabilities"] == 24900000 + 40000
    balances.delete_balance(conn, row)
    assert networth.net_worth_on(conn, date(2026, 3, 31))["liabilities"] == 25000000 + 40000


def test_totals_equal_the_sum_of_the_open_accounts_latest_balances(conn, household):
    """With every closed account at zero, the totals must equal what the account table adds up to."""
    rows = balances.update_rows(conn, TODAY, TODAY)
    assets = sum(r["last_cents"] or 0 for r in rows if r["class_name"] == "Asset")
    liabilities = sum(r["last_cents"] or 0 for r in rows if r["class_name"] == "Liability")
    got = networth.net_worth_on(conn, TODAY)
    assert (got["assets"], got["liabilities"]) == (assets, liabilities)


# -- which dates the month-end table asks about --

def test_month_end_dates_across_a_year_boundary_and_a_partial_month():
    assert networth.month_end_dates(date(2025, 11, 2), date(2026, 1, 5)) == [
        (date(2025, 11, 30), False), (date(2025, 12, 31), False), (date(2026, 1, 5), True)]


def test_month_end_dates_in_a_leap_year():
    assert networth.month_end_dates(date(2028, 2, 10), date(2028, 3, 31)) == [
        (date(2028, 2, 29), False), (date(2028, 3, 31), False)]


def test_today_on_the_last_day_of_a_month_is_not_partial():
    assert networth.month_end_dates(date(2026, 9, 1), date(2026, 10, 31)) == [
        (date(2026, 9, 30), False), (date(2026, 10, 31), False)]


def test_first_month_is_the_current_month():
    assert networth.month_end_dates(date(2026, 10, 1), date(2026, 10, 30)) == [(date(2026, 10, 30), True)]


# -- empty and tiny databases --

def test_nothing_at_all(conn):
    assert networth.net_worth_by_month(conn, TODAY) == []
    got = networth.net_worth_on(conn, TODAY)
    assert (got["assets"], got["liabilities"], got["net_worth"]) == (0, 0, 0)


def test_accounts_but_no_balances(conn):
    add_account(conn, "A", ASSET, "Checking")
    assert networth.net_worth_by_month(conn, TODAY) == []
    assert networth.net_worth_on(conn, TODAY)["net_worth"] == 0


def test_a_liability_alone_makes_net_worth_negative(conn):
    acct = add_account(conn, "Loan", LIABILITY, "Loan")
    add_balance(conn, acct, "2026-09-10", 123456)
    rows = networth.net_worth_by_month(conn, TODAY)
    assert [(r["date"], r["net_worth"]) for r in rows] == [("2026-09-30", -123456), ("2026-10-30", -123456)]
    assert (rows[0]["assets"], rows[0]["liabilities"]) == (0, 123456)
