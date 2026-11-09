"""The endpoints every list uses, and a person's page size. The lists named here exist only in these tests. Synthetic data only."""

import pytest
from fastapi.testclient import TestClient

from conftest import add_account, add_balance, op, sign_in, with_db
from northstar import currencies, db, list_prefs, rates
from northstar.errors import ValidationError
from northstar.lists import loader
from northstar.lists.listdef import ListDef
from northstar.web.app import create_app

BALANCES = ListDef("balances_api_test", "live_balance_values",
                   ("as_of_date", "account", "amount_cents", "reporting_value", "note"), ("as_of_date", "desc"))
ACCOUNTS = ListDef("accounts_api_test", "accounts", ("name", "type", "currency"), ("name", "asc"), source="live_accounts")
CURRENCIES = ListDef("currencies_api_test", "currencies", ("code", "name", "is_enabled"), ("code", "asc"), admin_only=True)


@pytest.fixture(autouse=True)
def lists():
    for definition in (BALANCES, ACCOUNTS, CURRENCIES):
        loader.register(definition)
    yield
    for definition in (BALANCES, ACCOUNTS, CURRENCIES):
        loader._DEFINITIONS.pop(definition.key)


@pytest.fixture
def household(client):
    """Dollars and euros, three accounts and twelve balances."""
    with with_db(client) as conn:
        currencies.update_currency(op(conn), "EUR", True, "2020-01-01", __import__("datetime").date(2026, 6, 3))
        rates.add_rate(op(conn), "EUR", "2026-03-01", "1.10", __import__("datetime").date(2026, 6, 3))
        usd = add_account(conn, "Test dollars", 1, "Savings")
        card = add_account(conn, "Test card", 2, "Credit card")
        eur = conn.execute("INSERT INTO accounts (name, type_id, currency_id, created_by, updated_by) VALUES "
                           "('Test euros', (SELECT id FROM account_types WHERE name = 'Savings'), "
                           "(SELECT id FROM currencies WHERE code = 'EUR'), 1, 1)").lastrowid
        for number in range(12):
            add_balance(conn, [usd, card, eur][number % 3], f"2026-04-{number + 1:02d}", 10_000 + number)
        conn.commit()
    return {"usd": usd, "card": card, "eur": eur}


def ask(client, key, body=None, **extra):
    return client.post(f"/api/lists/{key}", json=body or {}, **extra)


# -- who may ask, and what for --

def test_a_list_is_only_for_people_who_are_signed_in(anon_client):
    assert anon_client.post("/api/lists/balances_api_test", json={}).status_code == 401


def test_an_unknown_list_is_not_found(client):
    response = ask(client, "no_such_list")
    assert response.status_code == 404 and "does not exist" in response.json()["detail"]


def test_a_list_for_admins_is_forbidden_to_anyone_else_and_open_to_an_admin(client, member_client, household):
    assert ask(member_client, "currencies_api_test").status_code == 403
    assert member_client.put("/api/lists/currencies_api_test/page-size", json={"page_size": 10}).status_code == 403
    response = ask(client, "currencies_api_test")
    assert response.status_code == 200 and response.json()["rows"]


def test_a_cross_site_request_is_refused(client, household):
    assert ask(client, "balances_api_test", headers={"Origin": "https://evil.example"}).status_code == 403
    assert ask(client, "balances_api_test", headers={"Origin": "http://testserver"}).status_code == 200


# -- what comes back --

def test_the_answer_has_the_columns_the_rows_and_the_counts(client, household):
    body = ask(client, "balances_api_test", {"page_size": 10}).json()
    assert all(c["scale"] is None for c in body["columns"])                  # no column here is a decimal stored as a whole number
    assert [(c["key"], c["label"], c["kind"]) for c in body["columns"]] == [
        ("as_of_date", "Date", "date"), ("account", "Account", "text"), ("amount_cents", "Value", "amount"),
        ("reporting_value", "Reporting value", "amount"), ("note", "Note", "text")]
    assert (body["total"], body["pages"], body["page"], body["page_size"], body["group"]) == (12, 2, 1, 10, None)
    assert body["sort"] == {"field": "as_of_date", "direction": "desc"}                  # the list's own, since the request named none
    named = ask(client, "balances_api_test", {"sort": {"field": "note", "direction": "asc"}}).json()
    assert named["sort"] == {"field": "note", "direction": "asc"}
    assert len(body["rows"]) == 10
    first = body["rows"][0]
    assert first["as_of_date"] == "2026-04-12" and first["amount_cents"]["unit"] in ("USD", "EUR")      # newest first
    assert set(first) >= {"_id", "_links", "as_of_date", "account", "amount_cents", "reporting_value", "note"}


def test_a_request_can_sort_filter_search_group_and_choose_columns(client, household):
    body = ask(client, "balances_api_test", {
        "columns": ["account", "amount_cents"], "sort": {"field": "amount_cents", "direction": "desc"},
        "filters": [{"field": "account", "operator": "is_any_of", "value": [household["eur"]]}], "page_size": 10}).json()
    assert [c["key"] for c in body["columns"]] == ["account", "amount_cents"]
    values = [r["amount_cents"]["value"] for r in body["rows"]]
    assert body["total"] == 4 and values == sorted(values, reverse=True)
    assert {r["account"] for r in body["rows"]} == {"Test euros"}
    assert ask(client, "balances_api_test", {"search": "dollars"}).json()["total"] == 4
    grouped = ask(client, "balances_api_test", {"group": "account", "columns": ["account"]}).json()
    assert {r["_group"] for r in grouped["rows"]} == {"Test card", "Test dollars", "Test euros"}
    assert all(r["_group_count"] == 4 for r in grouped["rows"])


def test_a_page_past_the_end_shows_the_last_and_nothing_matching_is_an_empty_page(client, household):
    body = ask(client, "balances_api_test", {"page": 99, "page_size": 10}).json()
    assert (body["page"], body["pages"], len(body["rows"])) == (2, 2, 2)
    empty = ask(client, "balances_api_test", {"filters": [{"field": "note", "operator": "equals", "value": "nothing"}]}).json()
    assert (empty["total"], empty["pages"], empty["page"], empty["rows"]) == (0, 1, 1, [])


@pytest.mark.parametrize("body, message", [
    ({"columns": ["no_such_column"]}, "not a column"),
    ({"columns": ["account.created_by.email"]}, "only shows its name"),
    ({"sort": {"field": "version"}}, "not a column"),
    ({"page": 0}, "page"),
    ({"surprise": 1}, "Unknown request field"),
    ({"filters": [{"field": "note", "operator": "nope", "value": "x"}]}, "cannot be filtered with"),
])
def test_a_request_that_breaks_a_rule_is_a_422_with_a_message(client, household, body, message):
    response = ask(client, "balances_api_test", body)
    assert response.status_code == 422 and message in response.json()["detail"]


def test_a_body_that_is_not_an_object_is_refused(client, household):
    assert client.post("/api/lists/balances_api_test", json=["x"]).status_code == 422


# -- links --

def test_a_column_opens_a_page_only_for_a_person_who_may_open_it(client, member_client, household):
    body = {"columns": ["name", "type", "currency"], "page_size": 10}
    admin = ask(client, "accounts_api_test", body).json()
    assert [c["linked"] for c in admin["columns"]] == [True, False, True]
    by_name = {r["name"]: r for r in admin["rows"]}
    assert by_name["Test euros"]["_links"] == {"name": f"/accounts/{household['eur']}", "currency": "/currencies/EUR"}
    assert by_name["Test card"]["_links"]["currency"] == "/currencies/USD"
    # a currency's page is for admins, so the same list shows a member no link there; the account's page is for everyone
    member_view = ask(member_client, "accounts_api_test", body).json()
    assert [c["linked"] for c in member_view["columns"]] == [True, False, False]
    assert all("currency" not in r["_links"] for r in member_view["rows"])


# -- a person's page size --

def test_a_page_size_is_remembered_for_the_person_and_the_list_and_an_explicit_one_wins(client, household):
    assert ask(client, "balances_api_test").json()["page_size"] == 25                 # the list's own default
    assert client.put("/api/lists/balances_api_test/page-size", json={"page_size": 10}).json() == {"page_size": 10}
    assert ask(client, "balances_api_test").json()["page_size"] == 10
    assert ask(client, "balances_api_test", {"page_size": 50}).json()["page_size"] == 50      # this request only
    assert ask(client, "balances_api_test").json()["page_size"] == 10
    assert ask(client, "accounts_api_test").json()["page_size"] == 25                 # another list is unaffected
    client.put("/api/lists/balances_api_test/page-size", json={"page_size": 100})
    assert ask(client, "balances_api_test").json()["page_size"] == 100
    with with_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM user_list_prefs").fetchone()[0] == 1      # changed, not added


@pytest.mark.parametrize("size", [7, 0, -10, 1000, "25", None, True, 25.5])
def test_a_page_size_that_is_not_offered_is_refused(client, size):
    response = client.put("/api/lists/balances_api_test/page-size", json={"page_size": size})
    assert response.status_code == 422


def test_an_unknown_list_has_no_page_size_to_save(client):
    assert client.put("/api/lists/no_such_list/page-size", json={"page_size": 10}).status_code == 404
    with with_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM user_list_prefs").fetchone()[0] == 0


def test_one_persons_page_size_is_not_anothers(tmp_path):
    first = sign_in(TestClient(create_app(tmp_path / "web.db")), "first@example.com", "First")
    second = sign_in(TestClient(create_app(tmp_path / "web.db")), "second@example.com", "Second", is_admin=False)
    first.put("/api/lists/balances_api_test/page-size", json={"page_size": 10})
    assert ask(first, "balances_api_test").json()["page_size"] == 10
    assert ask(second, "balances_api_test").json()["page_size"] == 25


def test_saving_a_page_size_makes_one_logged_row_and_changing_it_logs_nothing_more(client):
    def operations():
        with with_db(client) as conn:
            return conn.execute("SELECT COUNT(*) FROM sys_operations").fetchone()[0]
    start = operations()
    client.put("/api/lists/balances_api_test/page-size", json={"page_size": 10})
    created = operations()
    assert created == start + 1                                           # the row's creation
    client.put("/api/lists/balances_api_test/page-size", json={"page_size": 50})
    client.put("/api/lists/balances_api_test/page-size", json={"page_size": 10})
    assert operations() == created                                        # the page size is not a logged field


def test_the_module_refuses_a_size_it_does_not_offer_and_defaults_to_the_lists_own(client):
    with with_db(client) as conn:
        assert list_prefs.page_size(conn, 1, "anything", 25) == 25
        with pytest.raises(ValidationError, match="rows per page"):
            list_prefs.set_page_size(op(conn, 1), "anything", 3)
