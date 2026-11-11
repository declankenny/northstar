"""The balances either side of one (`GET /api/balances/{id}/neighbours`), which the balance page's delete confirmation is worded from, and
the count of an account's balances that the net worth answer gives its page. Synthetic data only."""

import pytest

from conftest import add_account, add_balance, balances_of, op, with_db
from northstar import accounts, balances
from northstar.errors import NotFoundError

ASSET = 1


@pytest.fixture
def two(client):
    """An account with balances on four dates (out of order on purpose), another with one, and a deleted one."""
    with with_db(client) as conn:
        one = add_account(conn, "Test one", ASSET, "Savings")
        other = add_account(conn, "Test two", ASSET, "Savings")
        gone = add_account(conn, "Test three", ASSET, "Savings")
        for day, cents in (("2026-03-01", 300), ("2026-01-01", 100), ("2026-04-01", 400), ("2026-02-01", 200)):
            add_balance(conn, one, day, cents)
        add_balance(conn, other, "2026-02-15", 999)         # between two of the first account's dates, and not its neighbour
        add_balance(conn, gone, "2026-02-10", 777)
        conn.commit()
        accounts.delete_account(op(conn), gone)
    return client, one, other


def ask(client, account, day):
    entry = next(b for b in balances_of(client, account) if b["as_of_date"] == day)
    return client.get(f"/api/balances/{entry['id']}/neighbours")


def test_a_balance_in_the_middle_has_one_either_side_by_date_and_not_by_when_it_was_entered(two):
    client, one, _ = two
    body = ask(client, one, "2026-03-01").json()
    assert body == {"older": {"as_of_date": "2026-02-01", "amount_cents": 200}, "newer": {"as_of_date": "2026-04-01", "amount_cents": 400}}


def test_the_first_has_no_older_and_the_last_has_no_newer(two):
    client, one, _ = two
    assert ask(client, one, "2026-01-01").json() == {"older": None, "newer": {"as_of_date": "2026-02-01", "amount_cents": 200}}
    assert ask(client, one, "2026-04-01").json() == {"older": {"as_of_date": "2026-03-01", "amount_cents": 300}, "newer": None}


def test_the_only_balance_has_neither(two):
    client, _, other = two
    assert ask(client, other, "2026-02-15").json() == {"older": None, "newer": None}


def test_only_the_same_accounts_balances_count(two):
    client, one, other = two
    # the other account's 2026-02-15 and the deleted account's 2026-02-10 sit between the first account's dates and are neither's neighbour
    assert ask(client, one, "2026-02-01").json() == {"older": {"as_of_date": "2026-01-01", "amount_cents": 100},
                                                      "newer": {"as_of_date": "2026-03-01", "amount_cents": 300}}


def test_a_missing_or_deleted_accounts_balance_is_a_404_and_it_needs_a_sign_in(two, anon_client):
    client, *_ = two
    with with_db(client) as conn:
        deleted = conn.execute("SELECT id FROM balances WHERE amount_cents = 777").fetchone()[0]
    assert client.get("/api/balances/99999/neighbours").status_code == 404
    assert client.get(f"/api/balances/{deleted}/neighbours").status_code == 404
    assert anon_client.get("/api/balances/1/neighbours").status_code == 401


def test_the_lookup_is_two_small_queries(two):
    client, one, _ = two
    with with_db(client) as conn:
        seen = []
        conn.set_trace_callback(seen.append)
        target = next(b for b in balances_of(client, one) if b["as_of_date"] == "2026-03-01")["id"]
        seen.clear()
        balances.neighbours(conn, target)
    assert len([s for s in seen if "LIMIT 1" in s]) == 2 and all("LIMIT 1" in s or "live_balances b" in s for s in seen)


def test_an_unknown_balance_raises_not_found(client):
    with with_db(client) as conn:
        with pytest.raises(NotFoundError):
            balances.neighbours(conn, 12345)


# -- the count the account page's tile shows --

def networth(client, account, **query):
    return client.get("/api/networth", params={"account_id": account, **query}).json()


def test_the_series_of_an_account_counts_its_balances_inside_the_dates_shown(two):
    client, one, other = two
    assert networth(client, one, start="2026-02-01")["balance_count"] == 3          # the start itself counts
    assert networth(client, one, start="2026-03-02")["balance_count"] == 1
    assert networth(client, one)["balance_count"] == 4
    assert networth(client, other)["balance_count"] == 1                            # not the first account's


def test_the_count_is_zero_for_an_account_with_no_balances_and_empty_for_the_household(client, two):
    client, *_ = two
    with with_db(client) as conn:
        empty = add_account(conn, "Test empty", ASSET, "Savings")
        conn.commit()
    assert networth(client, empty)["balance_count"] == 0
    assert client.get("/api/networth").json()["balance_count"] is None


def test_a_deleted_accounts_balances_are_not_counted(two):
    client, *_ = two
    with with_db(client) as conn:
        gone = conn.execute("SELECT account_id FROM balances WHERE amount_cents = 777").fetchone()[0]
    assert client.get("/api/networth", params={"account_id": gone}).status_code == 404
