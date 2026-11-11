"""The account page's balance history (a fixed list of the framework, `/api/lists/account_balances`): one account's live balances,
newest first, with how much each changed from the one before. Synthetic data only."""

import pytest

from conftest import add_account, add_balance, op, with_db
from northstar import accounts
from northstar.listdefs import catalog as household_catalog
from northstar.lists import loader
from northstar.lists.listdef import ListDef, check
from northstar.lists.registry import RegistryError

LIST = "/api/lists/account_balances"
ASSET = 1


def ask(client, account, **request):
    return client.post(LIST, json={"params": {"account": account}, **request})


def month(n):
    return f"2026-{n:02d}-01"


@pytest.fixture
def history(client):
    """An account with 30 balances (one a month from 2024-01), another with two, and a deleted one with one."""
    with with_db(client) as conn:
        one = add_account(conn, "Test one", ASSET, "Savings")
        other = add_account(conn, "Test two", ASSET, "Savings")
        gone = add_account(conn, "Test three", ASSET, "Savings")
        for i in range(30):
            add_balance(conn, one, f"{2024 + i // 12}-{i % 12 + 1:02d}-01", 100_00 + 10_00 * i * i)
        add_balance(conn, other, month(1), 500_00)
        add_balance(conn, other, month(2), 450_00)
        add_balance(conn, gone, month(1), 1_00)
        accounts.delete_account(op(conn), gone)
        return client, one, other, gone


# -- the view --

def test_each_balance_has_its_change_from_the_one_before_and_the_first_has_none(history):
    client, one, other, _ = history
    rows = ask(client, other).json()["rows"]
    assert [(r["as_of_date"], r["amount_cents"]["value"], r["change_cents"] and r["change_cents"]["value"]) for r in rows] == [
        (month(2), 450_00, -50_00), (month(1), 500_00, None)]


def test_the_change_is_from_the_balance_before_even_when_that_one_is_on_another_page(history):
    client, one, *_ = history
    page = ask(client, one, page=3).json()                   # the oldest six, newest first: the first of them has the last of page 2 before it
    assert [r["as_of_date"] for r in page["rows"]] == ["2024-06-01", "2024-05-01", "2024-04-01", "2024-03-01", "2024-02-01", "2024-01-01"]
    assert page["rows"][0]["change_cents"]["value"] == 10_00 * (5 * 5 - 4 * 4)
    assert page["rows"][-1]["change_cents"] is None


def test_the_change_is_in_the_accounts_own_currency_with_its_places(history):
    client, one, *_ = history
    row = ask(client, one).json()["rows"][0]
    assert row["change_cents"] == {"value": 10_00 * (29 * 29 - 28 * 28), "scale": 2, "unit": "USD"}
    assert row["amount_cents"]["unit"] == "USD"


def test_a_deleted_accounts_balances_are_not_in_the_view(history):
    client, _, _, gone = history
    with with_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM account_balances WHERE account_id = ?", (gone,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM balances WHERE account_id = ?", (gone,)).fetchone()[0] == 1


# -- the list --

def test_it_lists_one_accounts_balances_newest_first_twelve_to_a_page(history):
    client, one, *_ = history
    body = ask(client, one).json()
    assert (body["total"], body["pages"], body["page_size"], len(body["rows"])) == (30, 3, 12, 12)
    assert body["rows"][0]["as_of_date"] == "2026-06-01" and body["rows"][-1]["as_of_date"] == "2025-07-01"
    assert body["sort"] == {"field": "as_of_date", "direction": "desc"}
    assert [c["label"] for c in body["columns"]] == ["Date", "Balance", "Change"]
    assert body["customisable"] is False and body["filters"] == [] and body["customised"] is False


def test_it_shows_only_that_account_and_the_total_and_pages_follow_it(history):
    client, one, other, _ = history
    body = ask(client, other).json()
    assert (body["total"], body["pages"], len(body["rows"])) == (2, 1, 2)


def test_the_date_opens_the_balance_page(history):
    client, one, *_ = history
    row = ask(client, one).json()["rows"][0]
    assert row["_links"] == {"as_of_date": f"/balances/{row['_id']}"}


def test_it_sorts_by_a_column_it_shows_and_by_no_other(history):
    client, one, *_ = history
    up = ask(client, one, sort={"field": "as_of_date", "direction": "asc"}).json()["rows"]
    assert up[0]["as_of_date"] == "2024-01-01"
    by_amount = ask(client, one, sort={"field": "amount_cents", "direction": "asc"}).json()["rows"]
    assert by_amount[0]["as_of_date"] == "2024-01-01"
    assert ask(client, one, sort={"field": "note", "direction": "asc"}).status_code == 422
    assert ask(client, one, sort={"field": "account.name", "direction": "asc"}).status_code == 422


def test_a_page_past_the_end_shows_the_last(history):
    client, one, *_ = history
    body = ask(client, one, page=9).json()
    assert (body["page"], len(body["rows"])) == (3, 6)


def test_an_account_with_no_balances_is_an_empty_list(client):
    with with_db(client) as conn:
        empty = add_account(conn, "Test one", ASSET, "Savings")
    body = ask(client, empty).json()
    assert (body["total"], body["rows"], body["pages"]) == (0, [], 1)


def test_a_closed_account_lists_its_history_too(history):
    client, _, other, _ = history
    with with_db(client) as conn:
        add_balance(conn, other, month(3), 0)
        accounts.close_account(op(conn), other)
    assert ask(client, other).json()["total"] == 3


# -- the account is a parameter --

def test_the_request_must_name_the_account_and_nothing_else(history):
    client, one, *_ = history
    assert client.post(LIST, json={}).status_code == 422
    assert client.post(LIST, json={"params": {}}).status_code == 422
    assert client.post(LIST, json={"params": {"account": one, "other": 1}}).status_code == 422


@pytest.mark.parametrize("value", ["1", "1 OR 1 = 1", 0, -1, 1.5, True, None, [1]])
def test_the_account_is_a_whole_number_and_never_sql(history, value):
    client, *_ = history
    assert ask(client, value).status_code == 422


def test_an_unknown_or_deleted_account_is_a_404(history):
    client, _, _, gone = history
    assert ask(client, 99_999).status_code == 404
    assert ask(client, gone).status_code == 404


def test_another_list_takes_no_parameters(client):
    assert client.post("/api/lists/balances", json={"params": {"account": 1}}).status_code == 422


# -- nothing a person can change --

@pytest.mark.parametrize("part", [{"columns": ["note"]}, {"filters": []}, {"search": "x"}, {"group": "as_of_date"}, {"page_size": 50}])
def test_a_request_that_tries_to_change_the_list_is_refused(history, part):
    client, one, *_ = history
    response = ask(client, one, **part)
    assert response.status_code == 422 and "cannot be changed" in response.json()["detail"]


def test_a_persons_saved_choices_for_it_are_neither_read_nor_written(history):
    client, one, *_ = history
    with with_db(client) as conn:
        conn.execute("INSERT INTO user_list_prefs (user_id, list_key, page_size, created_by, updated_by) "
                     "SELECT id, 'account_balances', 50, id, id FROM users WHERE email = 'test@example.com'")
        conn.execute("INSERT INTO list_filters (owner_id, list_key, name, conditions, is_default, created_by, updated_by) "
                     "VALUES (NULL, 'account_balances', 'Shared', '[{\"field\":\"note\",\"operator\":\"is_empty\"}]', 1, 1, 1)")
        before = conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0]
    body = ask(client, one).json()
    assert (body["page_size"], body["total"], body["filters"], body["default_filter_id"]) == (12, 30, [], None)
    with with_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0] == before


@pytest.mark.parametrize("method, path, body", [
    ("get", "/filters", None), ("post", "/filters", {"name": "x", "conditions": []}), ("get", "/fields", None),
    ("get", "/choices/account", None), ("put", "/page-size", {"page_size": 50}), ("put", "/columns", {"columns": ["note"]}),
    ("post", "/export", {"params": {"account": 1}}),
])
def test_every_endpoint_that_keeps_or_offers_a_choice_refuses_it(history, method, path, body):
    client, *_ = history
    response = getattr(client, method)(LIST + path, **({"json": body} if body is not None else {}))
    assert response.status_code == 422


def test_it_needs_someone_signed_in_and_any_signed_in_person_may_read_it(history, anon_client, member_client):
    client, one, *_ = history
    assert anon_client.post(LIST, json={"params": {"account": one}}).status_code == 401
    assert member_client.post(LIST, json={"params": {"account": 1}}).status_code in (200, 404)    # an ordinary user is not refused


# -- the definition --

def test_the_definition_is_registered_fixed_and_scoped_to_the_account():
    definition = loader.get_list_definition("account_balances")
    assert (definition.customisable, definition.params, definition.page_size) == (False, ("account",), 12)
    assert definition.scope == "b.account_id = :account"


def test_a_scope_and_its_declared_parameters_must_match(client):
    with with_db(client) as conn:
        catalog = household_catalog(conn)
    base = dict(key="x", table="account_balances", columns=("as_of_date",), sort=("as_of_date", "asc"))
    check(catalog, ListDef(**base, scope="b.account_id = :account", params=("account",)))
    for scope, params in (("b.account_id = :account", ()), ("b.account_id = 1", ("account",)), ("b.account_id = :other", ("other",))):
        with pytest.raises(RegistryError):
            check(catalog, ListDef(**base, scope=scope, params=params))


def test_a_list_with_a_changeable_page_size_still_needs_one_of_the_offered_sizes(client):
    with with_db(client) as conn:
        catalog = household_catalog(conn)
    base = dict(key="x", table="account_balances", columns=("as_of_date",), sort=("as_of_date", "asc"))
    with pytest.raises(RegistryError):
        check(catalog, ListDef(**base, page_size=12))
    check(catalog, ListDef(**base, page_size=12, customisable=False))
