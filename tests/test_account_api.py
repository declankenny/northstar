from datetime import date, timedelta

import pytest

from northstar import networth

from conftest import add_account, add_balance, type_id, with_db

TODAY = date(2026, 10, 30)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("northstar.clock.today", lambda: TODAY)


@pytest.fixture
def household(client):
    """Synthetic. Returns the ids. Balances are in cents."""
    with with_db(client) as conn:
        ids = {
            "checking": add_account(conn, "Checking", 1, "Checking"),
            "savings": add_account(conn, "Savings", 1, "Savings"),
            "mortgage": add_account(conn, "Mortgage", 2, "Mortgage"),
        }
        add_balance(conn, ids["checking"], "2026-03-15", 100000)
        add_balance(conn, ids["checking"], "2026-06-01", 150000)
        add_balance(conn, ids["savings"], "2026-02-01", 200050)
        add_balance(conn, ids["mortgage"], "2026-01-01", 25000000)
        add_balance(conn, ids["mortgage"], "2026-06-01", 24900000)
    return ids


# ---- the series for one account ----

def test_account_series_covers_only_that_account_and_starts_at_its_first_balance(client, household):
    body = client.get("/api/networth", params={"account_id": household["checking"], "period": "month"}).json()
    assert body["start"] == "2026-03-15"
    rows = [(p["date"], p["assets"], p["liabilities"], p["net_worth"]) for p in body["series"]]
    assert rows[0] == ("2026-03-15", 100000, 0, 100000)
    assert ("2026-05-31", 100000, 0, 100000) in rows
    assert rows[-1] == ("2026-10-30", 150000, 0, 150000)


def test_a_liability_lands_in_liabilities_and_makes_net_worth_negative(client, household):
    body = client.get("/api/networth", params={"account_id": household["mortgage"], "period": "month"}).json()
    assert body["series"][0] == {"date": "2026-01-01", "assets": 0, "liabilities": 25000000, "net_worth": -25000000}
    assert body["series"][-1]["liabilities"] == 24900000


def test_the_accounts_series_add_up_to_the_household_series(client, household):
    everything = client.get("/api/networth", params={"start": "2026-03-15", "period": "week"}).json()["series"]
    parts = [client.get("/api/networth", params={"account_id": i, "start": "2026-03-15", "period": "week"}).json()["series"]
             for i in household.values()]
    for point, *pieces in zip(everything, *parts):
        assert point["date"] == pieces[0]["date"]
        for key in ("assets", "liabilities", "net_worth"):
            assert point[key] == sum(piece[key] for piece in pieces)


def test_net_worth_on_one_account_matches_a_plain_latest_balance_every_day(client, household):
    with with_db(client) as conn:
        entries = conn.execute(
            "SELECT as_of_date, amount_cents FROM balances WHERE account_id = ? ORDER BY as_of_date",
            (household["checking"],)).fetchall()
        day = date(2026, 1, 1)
        while day <= TODAY:
            known = [e["amount_cents"] for e in entries if e["as_of_date"] <= day.isoformat()]
            assert networth.net_worth_on(conn, day, household["checking"])["assets"] == (known[-1] if known else 0)
            day += timedelta(days=1)


def test_an_unknown_account_is_a_404_on_the_series(client, household):
    assert client.get("/api/networth", params={"account_id": 9999}).status_code == 404


def test_an_account_with_no_balances_has_an_empty_series(client):
    with with_db(client) as conn:
        account = add_account(conn, "New", 1, "Checking")
    body = client.get("/api/networth", params={"account_id": account}).json()
    assert body["series"] == []


# ---- reading the account ----

def test_the_account_page_has_everything_it_shows(client, household):
    body = client.get(f"/api/accounts/{household['checking']}").json()
    assert (body["name"], body["class_name"], body["type_name"], body["is_open"]) == ("Checking", "Asset", "Checking", True)
    assert (body["balance_count"], body["earliest_date"], body["last_date"], body["last_cents"]) == (2, "2026-03-15", "2026-06-01", 150000)
    assert body["today"] == "2026-10-30" and body["days_since"] == 151 and body["stale"] is True
    assert [b["as_of_date"] for b in body["balances"]] == ["2026-06-01", "2026-03-15"]      # newest first
    assert {t["name"] for t in body["types"]} >= {"Checking", "Savings"}
    assert body["other_class"]["name"] == "Liability" and body["other_class"]["types"]


def test_an_unknown_account_is_a_404(client):
    assert client.get("/api/accounts/9999").status_code == 404


# ---- changing the account ----

def test_edit_changes_the_name_type_and_notes(client, household):
    with with_db(client) as conn:
        savings_type = type_id(conn, "Savings")
    body = client.patch(f"/api/accounts/{household['checking']}",
                        json={"name": " Everyday ", "type_id": savings_type, "notes": "joint"}).json()
    assert (body["name"], body["type_name"], body["notes"]) == ("Everyday", "Savings", "joint")


@pytest.mark.parametrize("change, message", [
    ({"name": " ", "type_id": 1}, "Name is required"),
    ({"name": "X", "type_id": 99999}, "Choose a type"),
])
def test_a_bad_edit_is_refused_with_422(client, household, change, message):
    response = client.patch(f"/api/accounts/{household['checking']}", json=change)
    assert response.status_code == 422 and message in response.text


def test_change_class_moves_the_account_and_its_history(client, household):
    with with_db(client) as conn:
        loan = type_id(conn, "Mortgage")
    body = client.post(f"/api/accounts/{household['checking']}/change-class", json={"type_id": loan}).json()
    assert (body["class_name"], body["type_name"]) == ("Liability", "Mortgage")
    series = client.get("/api/networth", params={"account_id": household["checking"]}).json()["series"]
    assert series[0]["liabilities"] == 100000 and series[0]["assets"] == 0


def test_change_class_to_a_type_in_the_same_class_is_refused(client, household):
    with with_db(client) as conn:
        savings_type = type_id(conn, "Savings")
    response = client.post(f"/api/accounts/{household['checking']}/change-class", json={"type_id": savings_type})
    assert response.status_code == 422 and "other class" in response.text


def test_close_needs_a_zero_balance_then_reopen(client, household):
    url = f"/api/accounts/{household['checking']}"
    refused = client.post(url + "/close")
    assert refused.status_code == 422 and "not zero" in refused.text
    assert client.post(url + "/balances", json={"date": "2026-10-30", "amount": "0"}).status_code == 200
    closed = client.post(url + "/close").json()
    assert closed["is_open"] is False and closed["stale"] is False      # a closed account is never stale
    assert client.post(url + "/close").status_code == 422
    assert client.post(url + "/reopen").json()["is_open"] is True


def test_a_closed_account_refuses_balance_changes(client, household):
    url = f"/api/accounts/{household['checking']}"
    client.post(url + "/balances", json={"date": "2026-10-30", "amount": "0"})
    client.post(url + "/close")
    assert client.post(url + "/balances", json={"date": "2026-10-30", "amount": "5"}).status_code == 422
    entry = client.get(url).json()["balances"][0]
    assert client.patch(f"/api/balances/{entry['id']}", json={"date": "2026-10-29", "amount": "5"}).status_code == 422
    assert client.delete(f"/api/balances/{entry['id']}").status_code == 422


def test_delete_removes_the_account_and_its_balances(client, household):
    url = f"/api/accounts/{household['checking']}"
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404
    with with_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM balances WHERE account_id = ?", (household["checking"],)).fetchone()[0] == 0
    assert client.delete(url).status_code == 404


# ---- changing balances ----

def test_add_a_balance_returns_the_updated_account(client, household):
    url = f"/api/accounts/{household['savings']}/balances"
    body = client.post(url, json={"date": "2026-10-29", "amount": "$2,100.25", "note": " bonus "}).json()
    assert (body["last_date"], body["last_cents"], body["balance_count"]) == ("2026-10-29", 210025, 2)
    assert body["balances"][0]["note"] == "bonus"


def test_adding_on_a_date_that_has_a_balance_edits_it(client, household):
    url = f"/api/accounts/{household['savings']}/balances"
    body = client.post(url, json={"date": "2026-02-01", "amount": "5.00"}).json()
    assert body["balance_count"] == 1 and body["last_cents"] == 500


@pytest.mark.parametrize("entry, message", [
    ({"date": "2026-10-31", "amount": "1"}, "future"),
    ({"date": "nonsense", "amount": "1"}, "valid date"),
    ({"date": "2026-10-01", "amount": "abc"}, "Enter an amount"),
    ({"date": "2026-10-01", "amount": "1", "note": "x" * 501}, "too long"),
])
def test_a_bad_balance_is_refused_with_422_and_saves_nothing(client, household, entry, message):
    response = client.post(f"/api/accounts/{household['savings']}/balances", json=entry)
    assert response.status_code == 422 and message in response.text
    assert client.get(f"/api/accounts/{household['savings']}").json()["balance_count"] == 1


def test_edit_a_balance_changes_its_date_amount_and_note(client, household):
    entry = client.get(f"/api/accounts/{household['checking']}").json()["balances"][1]    # 2026-03-15
    body = client.patch(f"/api/balances/{entry['id']}", json={"date": "2026-03-10", "amount": "1,010.00", "note": "fixed"}).json()
    assert [(b["as_of_date"], b["amount_cents"], b["note"]) for b in body["balances"]] == [
        ("2026-06-01", 150000, None), ("2026-03-10", 101000, "fixed")]


def test_moving_a_balance_onto_another_date_is_refused(client, household):
    entry = client.get(f"/api/accounts/{household['checking']}").json()["balances"][1]
    response = client.patch(f"/api/balances/{entry['id']}", json={"date": "2026-06-01", "amount": "1"})
    assert response.status_code == 422 and "already a balance" in response.text


def test_delete_a_balance_returns_the_account_without_it(client, household):
    entry = client.get(f"/api/accounts/{household['checking']}").json()["balances"][0]
    body = client.delete(f"/api/balances/{entry['id']}").json()
    assert body["balance_count"] == 1 and body["last_cents"] == 100000
    assert client.delete(f"/api/balances/{entry['id']}").status_code == 404
    assert client.patch(f"/api/balances/{entry['id']}", json={"date": "2026-01-01", "amount": "1"}).status_code == 404


# ---- who may ----

def test_signed_out_requests_get_401(anon_client):
    assert anon_client.get("/api/accounts/1").status_code == 401
    assert anon_client.post("/api/accounts/1/balances", json={"date": "2026-01-01", "amount": "1"}).status_code == 401
    assert anon_client.delete("/api/balances/1").status_code == 401


def test_a_cross_site_change_is_refused(client, household):
    response = client.post(f"/api/accounts/{household['savings']}/balances",
                           json={"date": "2026-10-29", "amount": "1"}, headers={"origin": "https://evil.example"})
    assert response.status_code == 403
    assert client.get(f"/api/accounts/{household['savings']}").json()["balance_count"] == 1


def test_an_ordinary_user_can_change_accounts_because_all_data_is_shared(member_client):
    with with_db(member_client) as conn:
        account = add_account(conn, "Checking", 1, "Checking")
    response = member_client.post(f"/api/accounts/{account}/balances", json={"date": "2026-10-29", "amount": "1"})
    assert response.status_code == 200
