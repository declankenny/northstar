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


# -- the tree of columns and the choices for a filter --

def get(client, path):
    return client.get(f"/api/lists/{path}")


def all_keys(node):
    found = [f["key"] for f in node["fields"]]
    for relation in node["relations"]:
        found.append(relation["key"])
        if relation["children"]:
            found += all_keys(relation["children"])
    return found


def test_the_fields_and_the_choices_are_for_people_who_are_signed_in(anon_client):
    assert get(anon_client, "balances_api_test/fields").status_code == 401
    assert get(anon_client, "balances_api_test/choices/account").status_code == 401


def test_an_unknown_list_has_no_fields_or_choices_and_an_admin_list_is_for_admins(client, member_client, household):
    assert get(client, "no_such_list/fields").status_code == 404
    assert get(client, "no_such_list/choices/account").status_code == 404
    assert get(member_client, "currencies_api_test/fields").status_code == 403
    assert get(member_client, "currencies_api_test/choices/code").status_code == 403
    assert get(client, "currencies_api_test/fields").status_code == 200


def test_a_lists_fields_are_a_tree_of_its_own_columns_and_those_of_the_records_it_points_at(client, household):
    tree = get(client, "balances_api_test/fields").json()
    assert {f["key"] for f in tree["fields"]} == {"as_of_date", "amount_cents", "reporting_value", "note", "source", "created_at", "updated_at"}
    relations = {r["key"]: r for r in tree["relations"]}
    assert set(relations) == {"account", "created_by", "updated_by"}
    assert relations["created_by"]["children"] is None                                  # a person is shown by name, not entered
    account = relations["account"]
    assert {r["key"] for r in account["children"]["relations"]} == {"account.type", "account.currency", "account.created_by", "account.updated_by"}
    assert "account.type.class" in all_keys(tree) and "account.currency.minor_units" in all_keys(tree)
    assert not [k for k in all_keys(tree) if "email" in k or "password" in k or "deleted" in k or k.endswith("version")]
    value = next(f for f in tree["fields"] if f["key"] == "amount_cents")
    assert (value["label"], value["kind"], [o["name"] for o in value["operators"]]) == ("Value", "amount", ["equals", "at_least", "at_most", "between", "is_empty", "is_not_empty"])


def test_a_relation_offers_the_records_the_list_actually_has_and_never_a_deleted_accounts(client, household):
    with with_db(client) as conn:
        gone = add_account(conn, "Test deleted", 1, "Savings")
        add_balance(conn, gone, "2026-04-20", 5_000)
        conn.commit()
        from northstar import accounts
        accounts.delete_account(op(conn), gone)
    body = get(client, "balances_api_test/choices/account").json()
    assert body["kind"] == "records" and body["more"] is False
    assert [o["value"] for o in body["options"]] == ["Test card", "Test dollars", "Test euros"]
    assert {o["id"] for o in body["options"]} == {household["card"], household["usd"], household["eur"]}


def test_a_column_on_a_related_record_offers_its_own_choices_and_a_status_its_declared_values(client, household):
    currencies_offered = get(client, "balances_api_test/choices/account.currency").json()
    assert [o["value"] for o in currencies_offered["options"]] == ["EUR", "USD"]
    assert [o["value"] for o in get(client, "balances_api_test/choices/account.type").json()["options"]] == ["Credit card", "Savings"]


def test_a_column_with_nothing_to_pick_from_or_that_is_not_one_is_a_422(client, household):
    assert get(client, "balances_api_test/choices/note").status_code == 422
    assert get(client, "balances_api_test/choices/amount_cents").status_code == 422
    assert get(client, "balances_api_test/choices/no_such_column").status_code == 422
    assert get(client, "balances_api_test/choices/account.created_by.email").status_code == 422


# -- saved filters --

TYPES = [{"field": "account.type", "operator": "is_any_of", "value": [1]}]
SAVINGS = [{"field": "account", "operator": "is_any_of", "value": [1]}]


def post_filter(client, key, name, conditions=TYPES, shared=False):
    return client.post(f"/api/lists/{key}/filters", json={"name": name, "conditions": conditions, "shared": shared})


def names(body):
    return [f["name"] for f in body["filters"]]


def savings_types(client):
    """The condition "account type is Savings", with the id this database gave that type."""
    with with_db(client) as conn:
        savings = conn.execute("SELECT id FROM account_types WHERE name = 'Savings'").fetchone()[0]
    return [{"field": "account.type", "operator": "is_any_of", "value": [savings]}]


def test_saved_filters_follow_the_lists_access(anon_client, client, member_client, household):
    assert anon_client.get("/api/lists/balances_api_test/filters").status_code == 401
    assert anon_client.post("/api/lists/balances_api_test/filters", json={"name": "x", "conditions": []}).status_code == 401
    assert client.get("/api/lists/no_such_list/filters").status_code == 404
    assert member_client.get("/api/lists/currencies_api_test/filters").status_code == 403
    assert post_filter(member_client, "currencies_api_test", "x", []).status_code == 403
    assert client.get("/api/lists/balances_api_test/filters").json() == {"filters": [], "default_id": None}


def test_a_person_saves_a_private_filter_and_only_they_see_it(client, member_client, household):
    response = post_filter(member_client, "balances_api_test", "Savings")
    assert response.status_code == 201
    saved = response.json()["filters"][0]
    assert (saved["name"], saved["shared"], saved["is_default"], saved["can_edit"], saved["conditions"], saved["problems"]) == (
        "Savings", False, False, True, TYPES, [])
    assert names(member_client.get("/api/lists/balances_api_test/filters").json()) == ["Savings"]
    assert client.get("/api/lists/balances_api_test/filters").json()["filters"] == []             # not even an admin's


def test_only_an_admin_saves_a_shared_filter_and_everyone_sees_it_but_cannot_change_it(client, member_client, household):
    assert post_filter(member_client, "balances_api_test", "For all", shared=True).status_code == 403
    assert post_filter(client, "balances_api_test", "For all", shared=True).status_code == 201
    seen = member_client.get("/api/lists/balances_api_test/filters").json()["filters"]
    assert [(f["name"], f["shared"], f["can_edit"]) for f in seen] == [("For all", True, False)]
    filter_id = seen[0]["id"]
    assert member_client.put(f"/api/lists/balances_api_test/filters/{filter_id}", json={"name": "Mine"}).status_code == 403
    assert member_client.delete(f"/api/lists/balances_api_test/filters/{filter_id}").status_code == 403
    assert client.get("/api/lists/balances_api_test/filters").json()["filters"][0]["can_edit"] is True


def test_a_filter_is_renamed_replaced_defaulted_and_removed_and_each_answer_is_the_whole_set(client, household):
    filter_id = post_filter(client, "balances_api_test", "First").json()["filters"][0]["id"]
    url = f"/api/lists/balances_api_test/filters/{filter_id}"
    assert names(client.put(url, json={"name": "Renamed"}).json()) == ["Renamed"]
    assert client.put(url, json={"conditions": SAVINGS}).json()["filters"][0]["conditions"] == SAVINGS
    body = client.put(url, json={"is_default": True}).json()
    assert (body["default_id"], body["filters"][0]["is_default"], body["filters"][0]["name"]) == (filter_id, True, "Renamed")   # only what was named changed
    body = client.put(url, json={"is_default": False}).json()
    assert body["default_id"] is None
    assert client.delete(url).json() == {"filters": [], "default_id": None}
    assert client.delete(url).status_code == 404                                                  # already gone


def test_someone_elses_private_filter_is_not_found(client, member_client, household):
    filter_id = post_filter(member_client, "balances_api_test", "Hers").json()["filters"][0]["id"]
    url = f"/api/lists/balances_api_test/filters/{filter_id}"
    assert client.put(url, json={"name": "x"}).status_code == 404
    assert client.delete(url).status_code == 404
    assert member_client.put(f"/api/lists/accounts_api_test/filters/{filter_id}", json={"name": "x"}).status_code == 404   # nor in another list


@pytest.mark.parametrize("body, message", [
    ({"name": "", "conditions": TYPES}, "Give the filter a name"),
    ({"name": "x", "conditions": [{"field": "nope", "operator": "equals", "value": 1}]}, "not a column"),
    ({"name": "x", "conditions": "nope"}, None),
    ({"name": "x"}, None),
    ({"name": "x", "conditions": TYPES, "shared": "maybe"}, None),
])
def test_a_filter_that_breaks_a_rule_is_a_422(client, household, body, message):
    response = client.post("/api/lists/balances_api_test/filters", json=body)
    assert response.status_code == 422
    if message:
        assert message in response.json()["detail"]


def test_a_name_already_taken_is_a_422_that_says_so(client, household):
    post_filter(client, "balances_api_test", "Savings")
    response = post_filter(client, "balances_api_test", "savings")
    assert response.status_code == 422 and "already a filter called" in response.json()["detail"]


def test_a_list_opens_with_the_default_filter_and_says_which(client, household):
    plain = ask(client, "balances_api_test", {"page_size": 100}).json()
    assert (plain["total"], plain["filters"], plain["skipped"], plain["default_filter_id"]) == (12, [], [], None)
    types = savings_types(client)
    saved = post_filter(client, "balances_api_test", "Savings", types).json()["filters"][0]
    client.put(f"/api/lists/balances_api_test/filters/{saved['id']}", json={"is_default": True})
    opened = ask(client, "balances_api_test", {"page_size": 100}).json()
    assert (opened["total"], opened["filters"], opened["default_filter_id"]) == (8, types, saved["id"])      # savings accounts only
    assert {r["account"] for r in opened["rows"]} == {"Test dollars", "Test euros"}


def test_a_request_that_names_filters_even_none_gets_no_default(client, household):
    saved = post_filter(client, "balances_api_test", "Savings", TYPES).json()["filters"][0]
    client.put(f"/api/lists/balances_api_test/filters/{saved['id']}", json={"is_default": True})
    cleared = ask(client, "balances_api_test", {"filters": [], "page_size": 100}).json()
    assert (cleared["total"], cleared["filters"], cleared["default_filter_id"]) == (12, [], None)             # cleared stays cleared
    other = ask(client, "balances_api_test", {"filters": [{"field": "account", "operator": "is_any_of", "value": [household["card"]]}]}).json()
    assert other["total"] == 4 and other["default_filter_id"] is None


def test_the_persons_own_default_wins_over_the_shared_one_and_the_shared_one_reaches_everyone(client, member_client, household):
    shared = post_filter(client, "balances_api_test", "Everyone's", TYPES, shared=True).json()["filters"][0]["id"]
    client.put(f"/api/lists/balances_api_test/filters/{shared}", json={"is_default": True})
    assert ask(member_client, "balances_api_test").json()["default_filter_id"] == shared
    own = post_filter(member_client, "balances_api_test", "Mine", SAVINGS).json()["filters"][0]["id"]
    member_client.put(f"/api/lists/balances_api_test/filters/{own}", json={"is_default": True})
    assert ask(member_client, "balances_api_test").json()["default_filter_id"] == own
    assert ask(client, "balances_api_test").json()["default_filter_id"] == shared                  # the admin has no default of their own
    assert member_client.get("/api/lists/balances_api_test/filters").json()["default_id"] == own


def test_a_default_with_a_condition_the_list_no_longer_fits_is_applied_without_it_and_says_so(client, household):
    import json
    types = savings_types(client)
    saved = post_filter(client, "balances_api_test", "Savings", types).json()["filters"][0]["id"]
    with with_db(client) as conn:
        stale = types + [{"field": "a_column_since_removed", "operator": "equals", "value": 1}]
        conn.execute("UPDATE list_filters SET conditions = ?, is_default = 1 WHERE id = ?", (json.dumps(stale), saved))
    opened = ask(client, "balances_api_test", {"page_size": 100}).json()
    assert opened["filters"] == types and opened["total"] == 8
    assert [s["field"] for s in opened["skipped"]] == ["a_column_since_removed"] and "not a column" in opened["skipped"][0]["reason"]
    listed = client.get("/api/lists/balances_api_test/filters").json()["filters"][0]
    assert [p["field"] for p in listed["problems"]] == ["a_column_since_removed"]                  # the picker can mark it
