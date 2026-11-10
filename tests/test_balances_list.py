"""The Balances list as the framework serves it: every live balance across all accounts, with the columns and the sort it opens with.
Synthetic data only."""

import datetime

import pytest

from conftest import add_account, add_balance, op, with_db
from northstar import currencies, rates
from northstar.listdefs import catalog as northstar_catalog
from northstar.lists import loader
from northstar.lists.listdef import check

TODAY = datetime.date(2026, 6, 3)
KEY = "balances"


@pytest.fixture
def household(client):
    """Dollars and euros: three live accounts (one of them closed) with balances on known dates, and one deleted account."""
    with with_db(client) as conn:
        currencies.update_currency(op(conn), "EUR", True, "2020-01-01", TODAY)
        rates.add_rate(op(conn), "EUR", "2026-03-01", "1.10", TODAY)
        usd = add_account(conn, "Test dollars", 1, "Savings")
        card = add_account(conn, "Test card", 2, "Credit card")
        eur = conn.execute("INSERT INTO accounts (name, type_id, currency_id, created_by, updated_by) VALUES "
                           "('Test euros', (SELECT id FROM account_types WHERE name = 'Savings'), "
                           "(SELECT id FROM currencies WHERE code = 'EUR'), 1, 1)").lastrowid
        gone = add_account(conn, "Test deleted", 1, "Savings")
        add_balance(conn, usd, "2026-04-01", 10_000)
        add_balance(conn, usd, "2026-05-01", 12_000)
        add_balance(conn, card, "2026-04-15", 5_000)
        add_balance(conn, eur, "2026-02-01", 20_000)         # before the first euro rate: no value in dollars yet
        add_balance(conn, eur, "2026-04-20", 30_000)
        add_balance(conn, gone, "2026-04-10", 999)
        conn.execute("UPDATE accounts SET is_open = 0 WHERE id = ?", (card,))
        conn.execute("UPDATE accounts SET deleted = 1 WHERE id = ?", (gone,))
        conn.commit()
    return {"usd": usd, "card": card, "eur": eur}


def ask(client, body=None):
    return client.post(f"/api/lists/{KEY}", json=body or {})


def test_the_list_is_registered_and_its_definition_fits_the_registry(client):
    definition = loader.get_list_definition(KEY)
    with with_db(client) as conn:
        check(northstar_catalog(conn), definition)           # every column and the sort are ones the registry offers
    assert (definition.table, definition.sort, definition.source, definition.scope, definition.admin_only) == (
        "live_balance_values", ("as_of_date", "desc"), None, None, False)


def test_it_opens_with_the_columns_in_the_order_the_design_gives_and_no_filter(client, household):
    body = ask(client).json()
    assert [(c["key"], c["label"]) for c in body["columns"]] == [
        ("as_of_date", "Date"), ("account", "Account"), ("account.type", "Type"), ("amount_cents", "Value"),
        ("account.currency", "Currency"), ("reporting_value", "Reporting value"), ("note", "Note")]
    assert body["default_columns"] == [c["key"] for c in body["columns"]]
    assert {c["key"]: c["groupable"] for c in body["columns"]} == {                      # the page leaves Group by off an amount's menu
        "as_of_date": True, "account": True, "account.type": True, "amount_cents": False, "account.currency": True, "reporting_value": False, "note": True}
    assert (body["filters"], body["default_filter_id"], body["customised"], body["group"]) == ([], None, False, None)
    assert body["sort"] == {"field": "as_of_date", "direction": "desc"}


def test_it_lists_every_live_balance_newest_first_and_never_a_deleted_accounts(client, household):
    body = ask(client).json()
    assert body["total"] == 5
    assert [(r["as_of_date"], r["account"]) for r in body["rows"]] == [
        ("2026-05-01", "Test dollars"), ("2026-04-20", "Test euros"), ("2026-04-15", "Test card"),
        ("2026-04-01", "Test dollars"), ("2026-02-01", "Test euros")]
    assert "Test deleted" not in {r["account"] for r in body["rows"]}


def test_a_closed_accounts_balances_are_listed(client, household):
    assert "Test card" in {r["account"] for r in ask(client).json()["rows"]}


def test_a_value_is_in_the_accounts_own_currency_and_the_reporting_value_in_the_system_currency(client, household):
    rows = {(r["as_of_date"], r["account"]): r for r in ask(client).json()["rows"]}
    euros = rows[("2026-04-20", "Test euros")]
    assert euros["amount_cents"] == {"value": 30_000, "scale": 2, "unit": "EUR"}
    assert euros["account.currency"] == "EUR"
    assert euros["reporting_value"] == {"value": 33_000, "scale": 2, "unit": "USD"}          # at 1.10
    dollars = rows[("2026-05-01", "Test dollars")]
    assert (dollars["amount_cents"]["unit"], dollars["reporting_value"]["value"], dollars["account.type"]) == ("USD", 12_000, "Savings")


def test_a_balance_with_no_rate_yet_has_no_reporting_value_rather_than_zero(client, household):
    rows = {(r["as_of_date"], r["account"]): r for r in ask(client).json()["rows"]}
    assert rows[("2026-02-01", "Test euros")]["reporting_value"] is None


def test_the_account_and_the_date_link_to_their_pages(client, household):
    row = ask(client).json()["rows"][0]                    # the newest: Test dollars
    assert row["_links"]["account"] == f"/accounts/{household['usd']}"
    assert row["_links"]["as_of_date"] == f"/balances/{row['_id']}"             # the date opens the balance's own page
    assert set(row["_links"]) <= {"as_of_date", "account", "account.currency"}


def test_the_currency_links_to_its_page_for_admins_only(client, member_client, household):
    assert ask(client).json()["rows"][0]["_links"].get("account.currency", "").startswith("/currencies/")
    member = ask(member_client).json()["rows"][0]
    assert "account.currency" not in member["_links"] and "account" in member["_links"]


def test_it_can_be_sorted_and_filtered_through_the_framework_like_any_list(client, household):
    by_value = ask(client, {"sort": {"field": "amount_cents", "direction": "asc"}}).json()
    assert [r["amount_cents"]["value"] for r in by_value["rows"]][:2] == [5_000, 10_000]
    euro = ask(client, {"filters": [{"field": "account.currency", "operator": "is_any_of",
                                       "value": [_currency_id(client, "EUR")]}]}).json()
    assert euro["total"] == 2 and {r["account"] for r in euro["rows"]} == {"Test euros"}


def test_it_is_only_for_people_who_are_signed_in(anon_client):
    assert anon_client.post(f"/api/lists/{KEY}", json={}).status_code == 401


def _currency_id(client, code):
    with with_db(client) as conn:
        return conn.execute("SELECT id FROM currencies WHERE code = ?", (code,)).fetchone()[0]
