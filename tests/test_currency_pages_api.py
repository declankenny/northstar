"""The endpoints behind a currency's page: its state, switching it on and off, adding and correcting rates. Synthetic data only."""

from datetime import date

import pytest

from conftest import add_balance, op, type_id, with_db
from northstar import accounts, clock, currencies

URL = "/api/currencies"
TODAY = date(2026, 6, 3)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: TODAY)


@pytest.fixture
def usd_client(client):
    """The signed-in admin's client, on an installation whose system currency is US dollars (the fixtures set it)."""
    return client


def page(client, code="EUR"):
    response = client.get(f"{URL}/{code}")
    assert response.status_code == 200
    return response.json()


def switch_on(client, code="EUR", start="2020-01-01"):
    return client.patch(f"{URL}/{code}", json={"is_enabled": True, "rates_start": start})


def add(client, day, rate, code="EUR", **extra):
    return client.post(f"{URL}/{code}/rates", json={"date": day, "rate": rate, **extra})


def test_the_page_of_a_currency_that_is_off(usd_client):
    body = page(usd_client)
    assert (body["code"], body["name"], body["minor_units"], body["is_enabled"], body["is_system"]) == ("EUR", "Euro", 2, False, False)
    assert (body["system_code"], body["rates_start"], body["default_rates_start"], body["today"]) == ("USD", None, "2000-01-01", "2026-06-03")
    assert (body["can_add_rates"], body["rates"], body["stale"], body["account_count"]) == (False, [], None, 0)


def test_the_page_of_the_system_currency(usd_client):
    body = page(usd_client, "USD")
    assert (body["is_enabled"], body["is_system"], body["can_add_rates"], body["rates_start"]) == (True, True, False, None)


def test_an_unknown_currency_is_a_404(usd_client):
    assert usd_client.get(f"{URL}/ZZZ").status_code == 404
    assert usd_client.patch(f"{URL}/ZZZ", json={"is_enabled": True, "rates_start": "2020-01-01"}).status_code == 404


def test_switching_on_saves_the_flag_and_the_date_together_and_answers_with_the_page(usd_client):
    response = switch_on(usd_client)
    assert response.status_code == 200
    body = response.json()
    assert (body["is_enabled"], body["rates_start"], body["can_add_rates"]) == (True, "2020-01-01", True)
    row = {r["code"]: r for r in usd_client.get(URL).json()["currencies"]}["EUR"]
    assert row["is_enabled"] is True


def test_switching_on_without_a_date_is_a_422_that_names_the_date(usd_client):
    response = usd_client.patch(f"{URL}/EUR", json={"is_enabled": True})
    assert response.status_code == 422 and "date rates start from" in response.json()["detail"]
    assert page(usd_client)["is_enabled"] is False


def test_switching_off_needs_no_date_and_keeps_the_one_it_had(usd_client):
    switch_on(usd_client, start="2021-02-03")
    body = usd_client.patch(f"{URL}/EUR", json={"is_enabled": False}).json()
    assert (body["is_enabled"], body["rates_start"]) == (False, "2021-02-03")


def test_the_start_date_alone_can_be_changed_and_a_future_one_is_refused(usd_client):
    switch_on(usd_client)
    assert usd_client.patch(f"{URL}/EUR", json={"rates_start": "2018-05-06"}).json()["rates_start"] == "2018-05-06"
    refused = usd_client.patch(f"{URL}/EUR", json={"rates_start": "2026-06-04"})
    assert refused.status_code == 422 and "after today" in refused.json()["detail"]


def test_the_system_currency_cannot_be_switched_off_by_the_endpoint(usd_client):
    refused = usd_client.patch(f"{URL}/USD", json={"is_enabled": False})
    assert refused.status_code == 422 and "system currency" in refused.json()["detail"]
    assert page(usd_client, "USD")["is_enabled"] is True


def test_a_rate_is_added_and_the_page_lists_it_with_its_source(usd_client):
    switch_on(usd_client)
    response = add(usd_client, "2026-05-01", "1.0850")
    assert response.status_code == 201
    row = response.json()["rates"][0]
    assert (row["date"], row["rate"], row["source"], row["until"]) == ("2026-05-01", "1.0850", "manual", None)
    assert row["id"] > 0 and row["changed"]


def test_a_rate_for_a_taken_date_a_future_date_or_a_bad_value_is_a_422_with_the_reason(usd_client):
    switch_on(usd_client)
    add(usd_client, "2026-05-01", "1.0850")
    for day, rate, text in (("2026-05-01", "1.2", "already exists"), ("2026-06-04", "1.2", "after today"),
                            ("2026-05-02", "0", "greater than zero"), ("2026-05-02", "x", "Enter a rate like")):
        refused = add(usd_client, day, rate)
        assert refused.status_code == 422 and text in refused.json()["detail"], (day, rate)
    assert len(page(usd_client)["rates"]) == 1


def test_a_rate_cannot_be_added_to_a_currency_that_is_off_or_to_the_system_currency(usd_client):
    off = add(usd_client, "2026-05-01", "1.0850")
    assert off.status_code == 422 and "Switch on EUR" in off.json()["detail"]
    system = add(usd_client, "2026-05-01", "1", "USD")
    assert system.status_code == 422 and "needs no rates" in system.json()["detail"]


def test_a_rate_is_read_in_the_format_the_page_was_using_and_refused_if_the_saved_one_changed(usd_client):
    switch_on(usd_client)
    refused = add(usd_client, "2026-05-01", "1,0850", locale="de-DE")
    assert refused.status_code == 409 and refused.json()["locale_changed"]["tag"] == "en-US"
    assert page(usd_client)["rates"] == []
    assert add(usd_client, "2026-05-01", "1.0850", locale="en-US").status_code == 201


def test_a_rate_is_corrected_by_its_id_and_its_date_stays(usd_client):
    switch_on(usd_client)
    first = add(usd_client, "2026-05-01", "1.0850").json()["rates"][0]["id"]
    add(usd_client, "2026-05-05", "1.0815")
    response = usd_client.put(f"{URL}/EUR/rates/{first}", json={"rate": "1.09"})
    assert response.status_code == 200
    rates = {r["date"]: r for r in response.json()["rates"]}
    assert (rates["2026-05-01"]["rate"], rates["2026-05-01"]["until"], rates["2026-05-05"]["rate"]) == ("1.09", "2026-05-05", "1.0815")
    assert usd_client.put(f"{URL}/EUR/rates/9999", json={"rate": "1.1"}).status_code == 404
    assert usd_client.put(f"{URL}/EUR/rates/{first}", json={"rate": "0"}).status_code == 422


def test_there_is_no_way_to_delete_a_rate_or_change_its_date_through_the_api(usd_client):
    switch_on(usd_client)
    first = add(usd_client, "2026-05-01", "1.0850").json()["rates"][0]["id"]
    assert usd_client.delete(f"{URL}/EUR/rates/{first}").status_code in (404, 405)
    assert usd_client.put(f"{URL}/EUR/rates/{first}", json={"rate": "1.1", "date": "2026-05-02"}).json()["rates"][0]["date"] == "2026-05-01"


def test_the_page_warns_when_the_newest_rate_is_stale_and_an_account_is_open(usd_client):
    switch_on(usd_client)
    add(usd_client, "2026-05-12", "1.0840")
    with with_db(usd_client) as conn:
        accounts.add_account(op(conn), "Test euros", 1, type_id(conn, "Savings"), None, currencies.by_code(conn, "EUR").id)
    assert page(usd_client)["stale"] == {"last_date": "2026-05-12", "days": 22, "threshold": 14}


def test_an_ordinary_user_is_refused_and_so_is_someone_signed_out(member_client, anon_client):
    for method, path, body in (("get", "/EUR", None), ("patch", "/EUR", {"is_enabled": True, "rates_start": "2020-01-01"}),
                               ("post", "/EUR/rates", {"date": "2026-05-01", "rate": "1"}), ("put", "/EUR/rates/1", {"rate": "1"})):
        assert getattr(member_client, method)(URL + path, **({} if body is None else {"json": body})).status_code == 403
        assert getattr(anon_client, method)(URL + path, **({} if body is None else {"json": body})).status_code == 401


def test_the_net_worth_endpoint_says_where_a_series_starts_and_which_currency_has_no_rate_before(usd_client):
    switch_on(usd_client)
    add(usd_client, "2026-05-01", "1.0850")
    with with_db(usd_client) as conn:
        dollars = accounts.add_account(op(conn), "Test dollars", 1, type_id(conn, "Savings"))
        euros = accounts.add_account(op(conn), "Test euros", 1, type_id(conn, "Savings"), None, currencies.by_code(conn, "EUR").id)
        add_balance(conn, dollars, "2026-01-01", 100000)
        add_balance(conn, euros, "2026-03-01", 10000)
    body = usd_client.get("/api/networth").json()
    assert body["limited"] == {"starts_on": "2026-05-01", "currencies": ["EUR"]}
    assert [(p["date"], p["net_worth"]) for p in body["series"]] == [
        ("2026-05-01", 110850), ("2026-05-31", 110850), ("2026-06-03", 110850)]
    per_account = usd_client.get(f"/api/networth?account_id={euros}").json()
    assert per_account["limited"] is None and per_account["series"][0]["net_worth"] == 10000
