from datetime import date

import pytest

from conftest import add_account, add_balance, with_db

TODAY = date(2026, 10, 30)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("northstar.clock.today", lambda: TODAY)


@pytest.fixture
def household(client):
    """Synthetic. Savings was last updated 43 days ago against a 35 day limit, so it is stale."""
    with with_db(client) as conn:
        ids = {
            "checking": add_account(conn, "Checking", 1, "Checking"),
            "savings": add_account(conn, "Savings", 1, "Savings"),
            "mortgage": add_account(conn, "Mortgage", 2, "Mortgage"),
            "old": add_account(conn, "Old savings", 1, "Savings"),
        }
        add_balance(conn, ids["checking"], "2026-10-27", 842311)
        add_balance(conn, ids["savings"], "2026-09-17", 4080851)
        add_balance(conn, ids["mortgage"], "2026-10-12", 19369751)
        add_balance(conn, ids["old"], "2026-02-01", 0)
        conn.execute("UPDATE accounts SET is_open = 0 WHERE id = ?", (ids["old"],))
    return ids


def count_balances(client):
    with with_db(client) as conn:
        return conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0]


def rows_by_name(body):
    return {r["name"]: r for r in body["rows"]}


def test_the_default_date_is_todays_and_only_open_accounts_are_listed(client, household):
    body = client.get("/api/balances/update").json()
    assert (body["date"], body["today"]) == ("2026-10-30", "2026-10-30")
    assert [r["name"] for r in body["rows"]] == ["Checking", "Savings", "Mortgage"]


def test_each_row_has_its_last_balance_age_and_stale_flag(client, household):
    rows = rows_by_name(client.get("/api/balances/update").json())
    assert (rows["Checking"]["last_date"], rows["Checking"]["last_cents"], rows["Checking"]["days_since"]) == (
        "2026-10-27", 842311, 3)
    assert rows["Checking"]["stale"] is False
    assert (rows["Savings"]["days_since"], rows["Savings"]["stale"]) == (43, True)
    assert rows["Mortgage"]["class_name"] == "Liability"


def test_a_date_with_saved_balances_shows_them_and_other_rows_are_empty(client, household):
    body = client.get("/api/balances/update", params={"date": "2026-10-27"}).json()
    rows = rows_by_name(body)
    assert rows["Checking"]["existing_cents"] == 842311
    assert rows["Savings"]["existing_cents"] is None


def test_reading_another_date_writes_nothing(client, household):
    before = count_balances(client)
    for day in ("2026-10-27", "2026-01-01", "2026-10-30"):
        assert client.get("/api/balances/update", params={"date": day}).status_code == 200
    assert count_balances(client) == before


@pytest.mark.parametrize("bad", ["2026-10-31", "yesterday", "2026-13-01", "26-10-01"])
def test_a_future_or_malformed_date_is_a_422(client, household, bad):
    response = client.get("/api/balances/update", params={"date": bad})
    assert response.status_code == 422 and isinstance(response.json()["detail"], str)


def test_saving_adds_updates_and_skips_blanks_and_answers_with_the_date_as_saved(client, household):
    body = client.post("/api/balances/update", json={
        "date": "2026-10-27",
        "amounts": {str(household["checking"]): "9,000.00", str(household["savings"]): "100.50",
                    str(household["mortgage"]): ""},
    }).json()
    assert body["saved"] == {"added": 1, "updated": 1, "unchanged": 0}
    rows = rows_by_name(body)
    assert (rows["Checking"]["existing_cents"], rows["Savings"]["existing_cents"], rows["Mortgage"]["existing_cents"]) == (
        900000, 10050, None)


def test_saving_the_same_amount_again_is_unchanged(client, household):
    entry = {"date": "2026-10-27", "amounts": {str(household["checking"]): "8423.11"}}
    body = client.post("/api/balances/update", json=entry).json()
    assert body["saved"] == {"added": 0, "updated": 0, "unchanged": 1}


def test_a_zero_must_be_typed_and_is_saved(client, household):
    body = client.post("/api/balances/update", json={
        "date": "2026-10-30", "amounts": {str(household["mortgage"]): "0"}}).json()
    assert body["saved"]["added"] == 1 and rows_by_name(body)["Mortgage"]["existing_cents"] == 0


def test_one_bad_amount_saves_nothing_and_names_each_bad_account(client, household):
    before = count_balances(client)
    response = client.post("/api/balances/update", json={
        "date": "2026-10-30",
        "amounts": {str(household["checking"]): "5,000.00", str(household["savings"]): "12,3x",
                    str(household["mortgage"]): "1.234"},
    })
    body = response.json()
    assert response.status_code == 422
    assert body["detail"] == "Some amounts need fixing. Nothing was saved."
    assert set(body["errors"]) == {str(household["savings"]), str(household["mortgage"])}
    assert all(isinstance(message, str) and message for message in body["errors"].values())
    assert count_balances(client) == before


def test_a_future_date_is_refused_and_nothing_is_saved(client, household):
    before = count_balances(client)
    response = client.post("/api/balances/update", json={
        "date": "2026-10-31", "amounts": {str(household["checking"]): "1.00"}})
    assert response.status_code == 422 and "future" in response.json()["detail"]
    assert count_balances(client) == before


def test_a_closed_account_is_ignored_even_if_its_id_is_sent(client, household):
    before = count_balances(client)
    body = client.post("/api/balances/update", json={
        "date": "2026-10-30", "amounts": {str(household["old"]): "5.00"}}).json()
    assert body["saved"] == {"added": 0, "updated": 0, "unchanged": 0}
    assert count_balances(client) == before


def test_saving_leaves_existing_notes_alone(client, household):
    with with_db(client) as conn:
        conn.execute("UPDATE balances SET note = 'kept' WHERE account_id = ?", (household["checking"],))
    client.post("/api/balances/update", json={
        "date": "2026-10-27", "amounts": {str(household["checking"]): "1.00"}})
    with with_db(client) as conn:
        note = conn.execute("SELECT note FROM balances WHERE account_id = ?", (household["checking"],)).fetchone()[0]
    assert note == "kept"


def test_the_endpoints_need_a_signed_in_user_but_not_an_admin(anon_client, member_client, household):
    assert anon_client.get("/api/balances/update").status_code == 401
    assert anon_client.post("/api/balances/update", json={"date": "2026-10-30", "amounts": {}}).status_code == 401
    assert member_client.get("/api/balances/update").status_code == 200
