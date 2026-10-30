from datetime import date

import pytest

from conftest import add_account, add_balance, with_db

TODAY = date(2026, 10, 30)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("northstar.clock.today", lambda: TODAY)


def make_account(client, name, class_id, type_name):
    with with_db(client) as conn:
        return add_account(conn, name, class_id, type_name)


def balance(client, account_id, as_of, cents):
    with with_db(client) as conn:
        add_balance(conn, account_id, as_of, cents)


def test_empty_database_points_to_the_next_step(client):
    page = client.get("/").text
    assert "Nothing to show yet" in page and 'href="/accounts"' in page
    assert page.count("$0.00") == 3                       # net worth, assets, liabilities


def test_accounts_without_balances_say_so(client):
    make_account(client, "New account", 1, "Checking")
    page = client.get("/").text
    assert "No balances yet" in page and "New account" in page and "Net worth over time" not in page


def test_totals_are_as_of_today_with_carry_forward(client):
    house = make_account(client, "House", 1, "Real estate")
    mortgage = make_account(client, "Mortgage", 2, "Mortgage")
    balance(client, house, "2026-01-01", 40000000)
    balance(client, mortgage, "2026-01-01", 25000000)
    page = client.get("/").text
    assert "$150,000.00" in page          # net worth
    assert "$400,000.00" in page and "$250,000.00" in page
    assert "As of 2026-10-30" in page


def test_negative_net_worth_shows_a_minus_sign(client):
    loan = make_account(client, "Loan", 2, "Loan")
    balance(client, loan, "2026-05-01", 123456)
    assert "-$1,234.56" in client.get("/").text


def test_net_worth_over_time_is_one_row_per_month_end_newest_first(client):
    checking = make_account(client, "Checking", 1, "Checking")
    savings = make_account(client, "Savings", 1, "Savings")
    balance(client, checking, "2026-01-10", 100000)
    balance(client, savings, "2026-01-20", 200000)       # same month: still one row
    balance(client, checking, "2026-09-15", 150000)
    table = client.get("/").text.split("Net worth over time")[1]
    assert table.count("<tr>") == 11                      # header, then Jan to Oct 2026
    # Newest first: today (the current month), then each earlier month end.
    order = ["2026-10-30", "2026-09-30", "2026-08-31", "2026-02-28", "2026-01-31"]
    positions = [table.index(day) for day in order]
    assert positions == sorted(positions)
    assert "2026-01-10" not in table and "2026-09-15" not in table   # entry dates are not rows
    # Jan-Aug: 1,000 + 2,000 carried forward. Each row shows $3,000.00 as assets and as net worth.
    assert table.count("$3,000.00") == 8 * 2
    assert table.count("$3,500.00") == 2 * 2              # Sep and Oct: 1,500 + 2,000


def test_the_current_month_is_marked_to_date_and_only_it(client):
    acct = make_account(client, "Checking", 1, "Checking")
    balance(client, acct, "2026-09-01", 100)
    table = client.get("/").text.split("Net worth over time")[1]
    assert table.count("to date") == 1 and table.index("2026-10-30") < table.index("to date")


def test_a_balance_entered_this_month_shows_in_the_current_row_straight_away(client):
    acct = make_account(client, "Checking", 1, "Checking")
    balance(client, acct, "2026-10-05", 12345)
    table = client.get("/").text.split("Net worth over time")[1]
    assert table.count("<tr>") == 2 and "$123.45" in table and "2026-10-30" in table


def test_account_table_shows_open_accounts_with_age_and_stale_flag_and_links(client):
    checking = make_account(client, "Everyday", 1, "Checking")
    house = make_account(client, "House", 1, "Real estate")
    card = make_account(client, "Card", 2, "Credit card")
    balance(client, checking, "2026-08-01", 150000)       # 90 days, limit 35: stale
    balance(client, house, "2026-01-01", 40000000)        # 302 days, limit 365: fine
    page = client.get("/").text
    assert f'<a href="/accounts/{checking}">Everyday</a>' in page
    assert "90 days" in page and "302 days" in page
    assert page.count("Stale") == 1
    assert "No balance yet" in page                        # the card
    assert page.index("Assets</th>") < page.index("Liabilities</th>")
    assert f'/accounts/{card}"' in page


def test_closed_accounts_leave_the_table_but_not_the_totals(client):
    old = make_account(client, "Old savings", 1, "Savings")
    keep = make_account(client, "Keeper", 1, "Checking")
    balance(client, old, "2026-01-01", 50000)
    balance(client, old, "2026-02-01", 0)
    balance(client, keep, "2026-02-01", 70000)
    before = client.get("/").text
    client.post(f"/accounts/{old}/close")
    after = client.get("/").text
    assert "Old savings" in before and "Old savings" not in after
    assert "$700.00" in after and after.count("$700.00") >= 2   # totals unchanged, still in the series


def test_home_is_not_a_redirect_and_nav_has_a_dashboard_link(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 200 and '<a href="/">Dashboard</a>' in response.text


def test_names_are_escaped(client):
    acct = make_account(client, "<script>alert(1)</script>", 1, "Checking")
    balance(client, acct, "2026-10-01", 100)
    page = client.get("/").text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


def test_the_dashboard_cannot_be_posted_to(client):
    assert client.post("/").status_code == 405
