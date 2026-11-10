"""The Accounts list (a list of the framework, `/api/lists/accounts`), what the Add account dialog offers (`/api/accounts/options`)
and adding an account (`POST /api/accounts`). Synthetic data only."""

from datetime import date

import pytest

from northstar import balances

from conftest import add_account, add_balance, type_id, with_db, op

TODAY = date(2026, 10, 30)
LIST = "/api/lists/accounts"


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("northstar.clock.today", lambda: TODAY)


@pytest.fixture
def household(client):
    """Synthetic. Savings is 43 days old against a 35 day limit, so it is stale."""
    with with_db(client) as conn:
        ids = {
            "checking": add_account(conn, "Checking", 1, "Checking"),
            "savings": add_account(conn, "Savings", 1, "Savings"),
            "mortgage": add_account(conn, "Mortgage", 2, "Mortgage"),
            "empty": add_account(conn, "Nothing yet", 1, "Checking"),
            "old": add_account(conn, "Old savings", 1, "Savings"),
        }
        add_balance(conn, ids["checking"], "2026-10-27", 842311)
        add_balance(conn, ids["savings"], "2026-08-01", 100)
        add_balance(conn, ids["savings"], "2026-09-17", 4080851)
        add_balance(conn, ids["mortgage"], "2026-10-12", 19369751)
        add_balance(conn, ids["old"], "2026-01-05", 5000)
        add_balance(conn, ids["old"], "2026-02-01", 0)
        conn.execute("UPDATE accounts SET is_open = 0 WHERE id = ?", (ids["old"],))
    return ids


def rows(client, **request):
    """The list as the page reads it. With no `filters` it opens as a person's list does, with the shared default filter."""
    return client.post(LIST, json=request).json()["rows"]


def by_name(listed):
    return {row["name"]: row for row in listed}


# ---- the list ----

def test_it_opens_with_the_open_accounts_shared_filter_and_sorted_by_account(client, household):
    page = client.post(LIST, json={}).json()
    assert page["filters"] == [{"field": "is_open", "operator": "is_yes"}] and page["default_filter_id"] is not None
    assert page["sort"] == {"field": "name", "direction": "asc"}
    assert [row["name"] for row in page["rows"]] == ["Checking", "Mortgage", "Nothing yet", "Savings"]      # open only


def test_the_default_columns_are_the_ones_agreed(client, household):
    page = client.post(LIST, json={}).json()
    assert page["default_columns"] == ["name", "type.class", "type", "currency", "last_cents", "reporting_value",
                                       "last_date", "days_since", "is_stale", "balance_count"]
    assert [c["label"] for c in page["columns"]] == ["Account", "Class", "Type", "Currency", "Last balance", "Reporting value",
                                                      "Balance date", "Balance age (days)", "Stale", "Balances"]


def test_each_account_has_its_last_balance_age_and_stale_flag(client, household):
    accounts = by_name(rows(client))
    assert (accounts["Checking"]["last_date"], accounts["Checking"]["last_cents"]["value"], accounts["Checking"]["days_since"]) == (
        "2026-10-27", 842311, 3)
    assert accounts["Checking"]["is_stale"] == 0
    assert (accounts["Savings"]["last_cents"]["value"], accounts["Savings"]["days_since"], accounts["Savings"]["is_stale"]) == (
        4080851, 43, 1)
    assert accounts["Savings"]["balance_count"] == 2
    assert (accounts["Mortgage"]["type.class"], accounts["Mortgage"]["type"]) == ("Liability", "Mortgage")


def test_an_open_account_with_no_balance_is_listed_and_stale(client, household):
    row = by_name(rows(client))["Nothing yet"]
    assert (row["last_date"], row["last_cents"], row["reporting_value"], row["days_since"], row["balance_count"], row["is_stale"]) == (
        None, None, None, None, 0, 1)


def test_the_name_opens_the_account(client, household):
    row = by_name(rows(client))["Checking"]
    assert row["_links"]["name"] == f"/accounts/{household['checking']}"


def test_clearing_the_filter_shows_closed_accounts_too_and_they_are_never_stale(client, household):
    accounts = by_name(rows(client, filters=[]))
    assert set(accounts) == {"Checking", "Savings", "Mortgage", "Nothing yet", "Old savings"}
    assert (accounts["Old savings"]["is_stale"], accounts["Old savings"]["days_since"]) == (0, 271)


def test_the_closed_accounts_are_the_filter_open_is_no(client, household):
    closed = rows(client, filters=[{"field": "is_open", "operator": "is_no"}])
    assert [row["name"] for row in closed] == ["Old savings"]


def test_it_sorts_and_filters_by_the_age_and_whether_stale_which_the_database_works_out(client, household):
    stale = rows(client, filters=[{"field": "is_stale", "operator": "is_yes"}], sort={"field": "days_since", "direction": "desc"})
    assert [row["name"] for row in stale] == ["Savings", "Nothing yet"]            # an empty age sorts last when descending
    oldest = rows(client, filters=[], sort={"field": "days_since", "direction": "desc"})
    assert [row["name"] for row in oldest][:2] == ["Old savings", "Savings"]


def test_a_deleted_account_is_not_listed(client, household):
    with with_db(client) as conn:
        conn.execute("UPDATE accounts SET deleted = 1 WHERE id = ?", (household["savings"],))
    assert "Savings" not in by_name(rows(client, filters=[]))


def test_it_exports_what_it_shows(client, household):
    response = client.post(f"{LIST}/export", json={})
    assert response.status_code == 200
    text = response.content.decode("utf-8-sig").splitlines()
    assert text[0] == "Account,Type › Class,Type,Currency,Last balance,Reporting value,Balance date,Balance age (days),Stale,Balances"
    assert text[1].startswith("Checking,Asset,Checking,USD,8423.11,8423.11,2026-10-27,3,false,1")
    assert len(text) == 5                                                           # the header and the four open accounts


# ---- what the Add account dialog offers ----

def test_the_options_carry_the_types_the_add_dialog_offers(client, household):
    body = client.get("/api/accounts/options").json()
    assert [c["name"] for c in body["classes"]] == ["Asset", "Liability"]
    assert "Savings" in [t["name"] for t in body["classes"][0]["types"]] and "Mortgage" in [t["name"] for t in body["classes"][1]["types"]]
    assert body["today"] == "2026-10-30"
    assert body["currency"] == {"code": "USD", "name": "US Dollar", "minor_units": 2}
    assert [c["code"] for c in body["currencies"]] == ["USD"]


def test_options_is_not_read_as_an_account_id(client):
    assert client.get("/api/accounts/options").status_code == 200
    assert client.get("/api/accounts/9999").status_code == 404


# ---- adding ----

def new(client, **fields):
    with with_db(client) as conn:
        savings = type_id(conn, "Savings")
    body = {"account_class": "asset", "name": "Joint Savings", "type_id": savings}
    body.update(fields)
    return client.post("/api/accounts", json=body)


def test_adding_answers_with_the_new_accounts_id_and_the_list_shows_it(client):
    response = new(client, amount="", date="2026-10-01")
    assert response.status_code == 201
    row = by_name(rows(client))["Joint Savings"]
    assert response.json() == {"id": row["_id"]}
    assert (row["balance_count"], row["last_cents"]) == (0, None)


def test_adding_with_an_amount_makes_the_account_and_its_first_balance(client):
    response = new(client, name=" Joint Savings ", notes=" shared ", amount="$1,234.50", date="2026-10-01")
    assert response.status_code == 201
    row = by_name(rows(client))["Joint Savings"]
    assert (row["balance_count"], row["last_date"], row["last_cents"]["value"]) == (1, "2026-10-01", 123450)
    with with_db(client) as conn:
        assert conn.execute("SELECT notes FROM accounts WHERE id = ?", (response.json()["id"],)).fetchone()[0] == "shared"


def test_a_typed_amount_with_no_date_is_as_of_today(client):
    new(client, amount="10")
    assert by_name(rows(client))["Joint Savings"]["last_date"] == "2026-10-30"


def test_a_liability_takes_a_positive_amount_owed(client):
    with with_db(client) as conn:
        mortgage = type_id(conn, "Mortgage")
    client.post("/api/accounts", json={"account_class": "liability", "name": "Home", "type_id": mortgage, "amount": "250,000"})
    assert by_name(rows(client))["Home"]["last_cents"]["value"] == 25000000


@pytest.mark.parametrize("fields, message", [
    ({"name": " "}, "Name is required"),
    ({"type_id": 99999}, "Choose a type"),
    ({"account_class": "other"}, "Choose Asset or Liability"),
    ({"amount": "abc"}, "Enter an amount"),
    ({"amount": "5", "date": "2026-10-31"}, "future"),
    ({"amount": "5", "date": "nonsense"}, "valid date"),
])
def test_a_bad_new_account_is_refused_and_leaves_nothing_behind(client, fields, message):
    response = new(client, **fields)
    assert response.status_code == 422 and message in response.text
    assert rows(client, filters=[]) == []


def test_a_type_from_the_other_class_is_refused(client):
    with with_db(client) as conn:
        mortgage = type_id(conn, "Mortgage")
    response = new(client, type_id=mortgage)
    assert response.status_code == 422 and "Choose a type" in response.text


def test_a_failed_balance_rolls_the_account_back(conn):
    # The plain function on its own: a balance that fails after the account was made leaves no account.
    savings = type_id(conn, "Savings")
    with pytest.raises(Exception):
        balances.add_account_with_balance(op(conn), "asset", "Joint", savings, None, "5", "2026-10-31", TODAY)
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0


# ---- who may ----

def test_signed_out_requests_get_401(anon_client):
    assert anon_client.get("/api/accounts/options").status_code == 401
    assert anon_client.post(LIST, json={}).status_code == 401
    assert anon_client.post("/api/accounts", json={"account_class": "asset", "name": "x", "type_id": 1}).status_code == 401


def test_a_cross_site_add_is_refused(client):
    response = new(client, name="x")
    assert response.status_code == 201
    with with_db(client) as conn:
        savings = type_id(conn, "Savings")
    refused = client.post("/api/accounts", json={"account_class": "asset", "name": "y", "type_id": savings},
                          headers={"origin": "https://evil.example"})
    assert refused.status_code == 403
    assert len(rows(client, filters=[])) == 1


def test_an_ordinary_user_sees_the_list_but_not_a_currency_link(member_client, household=None):
    with with_db(member_client) as conn:
        add_account(conn, "Checking", 1, "Checking")
    row = by_name(member_client.post(LIST, json={}).json()["rows"])["Checking"]
    assert "name" in row["_links"] and "currency" not in row["_links"]
