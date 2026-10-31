from datetime import date

import pytest

from northstar import balances, networth

from conftest import add_account, add_balance, type_id, with_db

TODAY = date(2026, 10, 30)


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


def by_name(body):
    return {a["name"]: a for a in body["accounts"]}


def test_the_open_list_has_each_accounts_latest_balance_age_and_stale_flag(client, household):
    body = client.get("/api/accounts").json()
    accounts = by_name(body)
    assert set(accounts) == {"Checking", "Savings", "Mortgage", "Nothing yet"}      # open only
    assert (accounts["Checking"]["last_date"], accounts["Checking"]["last_cents"], accounts["Checking"]["days_since"]) == (
        "2026-10-27", 842311, 3)
    assert accounts["Checking"]["stale"] is False
    assert (accounts["Savings"]["last_cents"], accounts["Savings"]["days_since"], accounts["Savings"]["stale"]) == (4080851, 43, True)
    assert accounts["Savings"]["balance_count"] == 2
    assert accounts["Mortgage"]["class_name"] == "Liability" and accounts["Mortgage"]["type_name"] == "Mortgage"


def test_an_open_account_with_no_balance_is_listed_and_stale(client, household):
    row = by_name(client.get("/api/accounts").json())["Nothing yet"]
    assert (row["last_date"], row["last_cents"], row["days_since"], row["balance_count"], row["stale"]) == (None, None, None, 0, True)


def test_accounts_are_grouped_by_class_then_type_then_name(client, household):
    names = [a["name"] for a in client.get("/api/accounts").json()["accounts"]]
    assert names == ["Checking", "Nothing yet", "Savings", "Mortgage"]


def test_the_closed_list_is_never_flagged_stale_and_has_no_totals(client, household):
    body = client.get("/api/accounts", params={"closed": "true"}).json()
    assert [a["name"] for a in body["accounts"]] == ["Old savings"]
    assert body["accounts"][0]["stale"] is False and body["totals"] is None and body["closed"] is True


def test_the_totals_are_net_worth_on_today_and_match_the_listed_balances(client, household):
    body = client.get("/api/accounts").json()
    with with_db(client) as conn:
        assert body["totals"] == {k: networth.net_worth_on(conn, TODAY)[k] for k in ("assets", "liabilities")}
    listed = body["accounts"]
    assert body["totals"]["assets"] == sum(a["last_cents"] or 0 for a in listed if a["class_name"] == "Asset")
    assert body["totals"]["liabilities"] == sum(a["last_cents"] or 0 for a in listed if a["class_name"] == "Liability")


def test_the_list_carries_the_types_the_add_dialog_offers(client, household):
    classes = client.get("/api/accounts").json()["classes"]
    assert [c["name"] for c in classes] == ["Asset", "Liability"]
    assert "Savings" in [t["name"] for t in classes[0]["types"]] and "Mortgage" in [t["name"] for t in classes[1]["types"]]
    assert client.get("/api/accounts").json()["today"] == "2026-10-30"


def test_an_empty_household_lists_nothing(client):
    body = client.get("/api/accounts").json()
    assert body["accounts"] == [] and body["totals"] == {"assets": 0, "liabilities": 0}


# ---- adding ----

def new(client, **fields):
    with with_db(client) as conn:
        savings = type_id(conn, "Savings")
    body = {"account_class": "asset", "name": "Joint Savings", "type_id": savings}
    body.update(fields)
    return client.post("/api/accounts", json=body)


def test_adding_with_a_blank_amount_makes_an_account_with_no_balance(client):
    response = new(client, amount="", date="2026-10-01")
    assert response.status_code == 201
    row = by_name(response.json())["Joint Savings"]
    assert (row["balance_count"], row["last_cents"]) == (0, None)


def test_adding_with_an_amount_makes_the_account_and_its_first_balance(client):
    response = new(client, name=" Joint Savings ", notes=" shared ", amount="$1,234.50", date="2026-10-01")
    assert response.status_code == 201
    row = by_name(response.json())["Joint Savings"]
    assert (row["balance_count"], row["last_date"], row["last_cents"], row["notes"]) == (1, "2026-10-01", 123450, "shared")
    assert response.json()["totals"]["assets"] == 123450


def test_a_typed_amount_with_no_date_is_as_of_today(client):
    row = by_name(new(client, amount="10").json())["Joint Savings"]
    assert row["last_date"] == "2026-10-30"


def test_a_liability_takes_a_positive_amount_owed(client):
    with with_db(client) as conn:
        mortgage = type_id(conn, "Mortgage")
    body = client.post("/api/accounts", json={"account_class": "liability", "name": "Home", "type_id": mortgage, "amount": "250,000"}).json()
    assert by_name(body)["Home"]["last_cents"] == 25000000 and body["totals"]["liabilities"] == 25000000


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
    assert client.get("/api/accounts").json()["accounts"] == []


def test_a_type_from_the_other_class_is_refused(client):
    with with_db(client) as conn:
        mortgage = type_id(conn, "Mortgage")
    response = new(client, type_id=mortgage)
    assert response.status_code == 422 and "Choose a type" in response.text


def test_a_failed_balance_rolls_the_account_back(conn):
    # The plain function on its own: a balance that fails after the account was made leaves no account.
    savings = type_id(conn, "Savings")
    with pytest.raises(Exception):
        balances.add_account_with_balance(conn, "asset", "Joint", savings, None, "5", "2026-10-31", TODAY)
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0


# ---- who may ----

def test_signed_out_requests_get_401(anon_client):
    assert anon_client.get("/api/accounts").status_code == 401
    assert anon_client.post("/api/accounts", json={"account_class": "asset", "name": "x", "type_id": 1}).status_code == 401


def test_a_cross_site_add_is_refused(client):
    response = new(client, name="x")
    assert response.status_code == 201
    with with_db(client) as conn:
        savings = type_id(conn, "Savings")
    refused = client.post("/api/accounts", json={"account_class": "asset", "name": "y", "type_id": savings},
                          headers={"origin": "https://evil.example"})
    assert refused.status_code == 403
    assert len(client.get("/api/accounts").json()["accounts"]) == 1
