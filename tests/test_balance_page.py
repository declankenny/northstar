"""The balance page's endpoint: one balance with its account's page and the details beside it. Synthetic data only."""

import datetime
import re

import pytest
from fastapi.testclient import TestClient

from conftest import add_account, add_balance, balances_of, op, sign_in, with_db
from northstar import currencies, rates
from northstar.web.app import create_app

TODAY = datetime.date(2026, 6, 3)


@pytest.fixture
def household(client):
    """Dollars and euros: a dollar account, a euro account with one rate (1 March 2026) and a closed one, with known balances."""
    with with_db(client) as conn:
        currencies.update_currency(op(conn), "EUR", True, "2020-01-01", TODAY)
        rates.add_rate(op(conn), "EUR", "2026-03-01", "1.10", TODAY)
        usd = add_account(conn, "Test dollars", 1, "Savings")
        card = add_account(conn, "Test card", 2, "Credit card")
        eur = conn.execute("INSERT INTO accounts (name, type_id, currency_id, created_by, updated_by) VALUES "
                           "('Test euros', (SELECT id FROM account_types WHERE name = 'Savings'), "
                           "(SELECT id FROM currencies WHERE code = 'EUR'), 1, 1)").lastrowid
        for account, day, cents in ((usd, "2026-04-01", 10_000), (eur, "2026-04-20", 30_000), (eur, "2026-02-01", 20_000),    # the last is before the first euro rate
                                    (card, "2026-04-15", 5_000)):
            add_balance(conn, account, day, cents)
        found = lambda account, day: conn.execute("SELECT id FROM balances WHERE account_id = ? AND as_of_date = ?", (account, day)).fetchone()[0]
        ids = {"usd": found(usd, "2026-04-01"), "eur": found(eur, "2026-04-20"), "eur_early": found(eur, "2026-02-01"), "card": found(card, "2026-04-15")}
        conn.execute("UPDATE accounts SET is_open = 0 WHERE id = ?", (card,))
        conn.commit()
    return {"usd_account": usd, "eur_account": eur, "card_account": card, **ids}


def get(client, balance_id):
    return client.get(f"/api/balances/{balance_id}")


def test_it_gives_the_balance_with_its_accounts_page(client, household):
    body = get(client, household["eur"]).json()
    assert body["balance"]["id"] == household["eur"] and body["balance"]["as_of_date"] == "2026-04-20" and body["balance"]["amount_cents"] == 30_000
    assert isinstance(body["balance"]["version"], int)
    assert body["account"]["name"] == "Test euros" and body["account"]["currency"]["code"] == "EUR"
    assert (body["account"]["type_name"], body["account"]["class_name"], body["account"]["is_open"]) == ("Savings", "Asset", True)
    assert body["balance"]["version"] == next(b["version"] for b in balances_of(client, body["account"]["id"]) if b["id"] == household["eur"])
    assert set(body["account"]) == {"id", "name", "currency", "class_name", "type_name", "is_open"}    # a few facts, not the account's page


def test_a_balance_in_another_currency_shows_its_value_in_the_system_currency_and_the_date_of_the_rate(client, household):
    reporting = get(client, household["eur"]).json()["reporting"]
    assert reporting == {"value": 33_000, "scale": 2, "unit": "USD", "rate_date": "2026-03-01"}          # 300.00 EUR at 1.10


def test_a_balance_before_any_rate_has_no_value_and_no_rate_date_rather_than_zero(client, household):
    assert get(client, household["eur_early"]).json()["reporting"] == {"value": None, "scale": 2, "unit": "USD", "rate_date": None}


def test_a_balance_in_the_system_currency_has_nothing_to_convert(client, household):
    assert get(client, household["usd"]).json()["reporting"] is None


def test_the_value_is_the_one_the_list_shows(client, household):
    shown = {r["_id"]: r["reporting_value"] for r in client.post("/api/lists/balances", json={"page_size": 100}).json()["rows"]}
    for key in ("eur", "eur_early"):
        reporting = get(client, household[key]).json()["reporting"]
        assert (shown[household[key]] and shown[household[key]]["value"]) == reporting["value"]


def test_it_says_who_entered_the_balance_and_who_last_changed_it_with_the_dates(tmp_path, client, household):
    first = get(client, household["eur"]).json()
    assert (first["entered_by"], first["changed_by"]) == ("System", "System")                        # the fixture writes as the system user
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", first["entered_on"]) and first["changed_on"] == first["entered_on"]
    other = sign_in(TestClient(create_app(tmp_path / "web.db")), "other@example.com", "Other Person", is_admin=False)
    changed = other.patch(f"/api/balances/{household['eur']}", json={"date": "2026-04-20", "amount": "310.00", "note": "corrected",
                                                                      "version": first["balance"]["version"]})
    assert changed.status_code == 200
    second = get(client, household["eur"]).json()
    assert (second["entered_by"], second["changed_by"]) == ("System", "Other Person")
    assert second["balance"]["amount_cents"] == 31_000 and second["balance"]["note"] == "corrected"
    assert second["reporting"]["value"] == 34_100 and second["balance"]["version"] != first["balance"]["version"]


def test_a_closed_accounts_balance_can_be_read_and_says_the_account_is_closed(client, household):
    body = get(client, household["card"]).json()
    assert body["account"]["is_open"] is False and body["balance"]["amount_cents"] == 5_000


def test_a_balance_that_is_gone_is_not_found(client, household):
    assert get(client, 99_999).status_code == 404
    version = get(client, household["usd"]).json()["balance"]["version"]
    assert client.delete(f"/api/balances/{household['usd']}?version={version}").status_code == 200
    gone = get(client, household["usd"])
    assert gone.status_code == 404 and "no longer exists" in gone.json()["detail"]


def test_a_balance_of_a_deleted_account_is_not_found(client, household):
    with with_db(client) as conn:
        conn.execute("UPDATE accounts SET deleted = 1 WHERE id = ?", (household["usd_account"],))
        conn.commit()
    assert get(client, household["usd"]).status_code == 404


def test_it_is_for_people_who_are_signed_in(anon_client):
    assert anon_client.get("/api/balances/1").status_code == 401


def test_a_person_who_is_not_an_admin_can_read_it_too(tmp_path, client, household):
    member = sign_in(TestClient(create_app(tmp_path / "web.db")), "member@example.com", "Member", is_admin=False)
    assert get(member, household["eur"]).status_code == 200


def test_the_list_links_a_balances_date_to_its_page(client, household):
    rows = client.post("/api/lists/balances", json={"page_size": 100}).json()["rows"]
    assert all(row["_links"]["as_of_date"] == f"/balances/{row['_id']}" for row in rows) and rows


def test_the_balances_update_page_is_not_taken_for_a_balance(client, household):
    """`/api/balances/update` is the Update balances page's own endpoint; a balance's address is a number."""
    assert client.get("/api/balances/update").status_code == 200
    assert client.get("/api/balances/abc").status_code in (404, 405)               # not a balance: only a number is
