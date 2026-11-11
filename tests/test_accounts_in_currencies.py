"""Accounts in other currencies: what a new account can be in, creating one, and every account view carrying its currency.
Synthetic data only."""

from datetime import date

import pytest

from conftest import add_balance, balances_of, op, type_id, with_db
from northstar import accounts, balances, clock, currencies, networth, rates
from northstar.errors import ValidationError

TODAY = date(2026, 6, 3)
URL = "/api/accounts"


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: TODAY)


def usable(conn, code, rate="1.5", start="2020-01-01"):
    """Switch a currency on and give it a rate, so a new account can be in it."""
    currencies.update_currency(op(conn), code, True, start, TODAY)
    rates.add_rate(op(conn), code, "2026-05-01", rate, TODAY)


def codes(conn):
    return [c["code"] for c in currencies.choosable(conn)]


def new(conn, name, code=None, amount=None):
    return balances.add_account_with_balance(op(conn), "asset", name, type_id(conn, "Savings"), None, amount,
                                             "2026-05-12" if amount else None, TODAY, None, code)


# -- what a new account can be in --

def test_the_system_currency_alone_is_choosable_until_another_is_enabled_with_a_rate(conn):
    assert codes(conn) == ["USD"]
    currencies.update_currency(op(conn), "EUR", True, "2020-01-01", TODAY)
    assert codes(conn) == ["USD"]                                  # enabled, but no rate yet
    rates.add_rate(op(conn), "EUR", "2026-05-01", "1.0850", TODAY)
    assert codes(conn) == ["USD", "EUR"]


def test_the_system_currency_comes_first_and_the_others_by_code_and_a_disabled_one_is_left_out(conn):
    usable(conn, "GBP")
    usable(conn, "EUR")
    usable(conn, "JPY", "0.0067")
    currencies.update_currency(op(conn), "JPY", False, None, TODAY)
    assert codes(conn) == ["USD", "EUR", "GBP"]
    assert currencies.choosable(conn)[1] == {"code": "EUR", "name": "Euro", "minor_units": 2}


def test_nothing_is_choosable_while_the_system_currency_is_unset(conn):
    conn.execute("UPDATE system_properties SET value = NULL, read_only = 0 WHERE name = 'system.currency'")
    assert currencies.choosable(conn) == []


# -- creating an account in a currency --

def test_an_account_is_created_in_the_chosen_currency_and_its_first_balance_is_read_in_it(conn):
    usable(conn, "JPY", "0.0067")
    usable(conn, "KWD", "3.25")
    yen = new(conn, "Test yen", "JPY", "1,234")
    dinars = new(conn, "Test dinars", "KWD", "1.234")
    assert currencies.account_currency(conn, yen).code == "JPY" and currencies.account_currency(conn, dinars).code == "KWD"
    assert conn.execute("SELECT amount_cents FROM live_balances WHERE account_id = ?", (yen,)).fetchone()[0] == 1234
    assert conn.execute("SELECT amount_cents FROM live_balances WHERE account_id = ?", (dinars,)).fetchone()[0] == 1234


def test_no_currency_given_means_the_system_currency_and_naming_it_is_the_same(conn):
    usable(conn, "EUR")
    assert currencies.account_currency(conn, new(conn, "Test one")).code == "USD"
    assert currencies.account_currency(conn, new(conn, "Test two", "USD")).code == "USD"


def test_an_amount_with_more_decimals_than_the_currency_has_is_refused_and_no_account_is_left(conn):
    usable(conn, "JPY", "0.0067")
    with pytest.raises(ValidationError, match="no decimal places"):
        new(conn, "Test yen", "JPY", "12.5")
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0


def test_a_currency_that_is_not_enabled_or_has_no_rate_or_is_not_in_the_catalog_is_refused(conn):
    with pytest.raises(ValidationError, match="Choose a currency that is enabled"):
        new(conn, "Test euros", "EUR")
    currencies.update_currency(op(conn), "EUR", True, "2020-01-01", TODAY)
    with pytest.raises(ValidationError, match="EUR has no exchange rate yet"):
        new(conn, "Test euros", "EUR")
    with pytest.raises(ValidationError, match="Choose a currency from the list"):
        new(conn, "Test odd", "ZZZ")
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0


# -- the views carry the account's currency --

@pytest.fixture
def mixed(client):
    with with_db(client) as conn:
        usable(conn, "EUR", "1.0850")
        usable(conn, "KWD", "3.25")
        dollars = new(conn, "Test dollars", None, "1,000.00")
        euros = new(conn, "Test euros", "EUR", "100.00")
        dinars = new(conn, "Test dinars", "KWD", "1.234")
        conn.commit()
    return {"dollars": dollars, "euros": euros, "dinars": dinars}


EUR = {"code": "EUR", "name": "Euro", "minor_units": 2}
KWD = {"code": "KWD", "name": "Kuwaiti Dinar", "minor_units": 3}
USD = {"code": "USD", "name": "US Dollar", "minor_units": 2}


def accounts_list(client):
    """The Accounts list as the page reads it, every account: each row's currency and last balance with its own digits."""
    return {row["name"]: row for row in client.post("/api/lists/accounts", json={"filters": []}).json()["rows"]}


def test_the_options_say_what_a_new_account_can_be_in_and_each_listed_account_its_own_currency(client, mixed):
    body = client.get(f"{URL}/options").json()
    assert body["currency"] == USD and body["currencies"] == [USD, EUR, KWD]
    rows = accounts_list(client)
    assert {name: row["currency"] for name, row in rows.items()} == {"Test dollars": "USD", "Test euros": "EUR", "Test dinars": "KWD"}
    assert {name: row["last_cents"] for name, row in rows.items()} == {
        "Test dollars": {"value": 100000, "scale": 2, "unit": "USD"}, "Test euros": {"value": 10000, "scale": 2, "unit": "EUR"},
        "Test dinars": {"value": 1234, "scale": 3, "unit": "KWD"}}


def test_the_reporting_values_are_in_the_system_currency_whatever_the_accounts_are_in(client, mixed):
    # 1,000.00 + 100.00 EUR at 1.0850 + 1.234 KWD at 3.25 (4.0105 dollars, so 401 cents)
    values = {name: row["reporting_value"] for name, row in accounts_list(client).items()}
    assert values == {name: {"value": cents, "scale": 2, "unit": "USD"}
                      for name, cents in {"Test dollars": 100000, "Test euros": 10850, "Test dinars": 401}.items()}
    with with_db(client) as conn:
        assert networth.net_worth_on(conn, TODAY)["assets"] == 100000 + 10850 + 401


def test_adding_an_account_through_the_api_takes_a_currency_code(client, mixed):
    type_id_ = client.get(f"{URL}/options").json()["classes"][0]["types"][0]["id"]
    response = client.post(URL, json={"account_class": "asset", "name": "More euros", "type_id": type_id_, "currency": "EUR",
                                      "amount": "1,234.50", "date": "2026-05-12"})
    assert response.status_code == 201
    added = accounts_list(client)["More euros"]
    assert response.json() == {"id": added["_id"]}
    assert (added["currency"], added["last_cents"]) == ("EUR", {"value": 123450, "scale": 2, "unit": "EUR"})
    refused = client.post(URL, json={"account_class": "asset", "name": "Odd", "type_id": type_id_, "currency": "ZZZ"})
    assert refused.status_code == 422 and "Choose a currency from the list" in refused.json()["detail"]
    unusable = client.post(URL, json={"account_class": "asset", "name": "Yen", "type_id": type_id_, "currency": "JPY"})
    assert unusable.status_code == 422 and "enabled" in unusable.json()["detail"]


def test_an_account_page_carries_its_currency_and_a_balance_is_read_in_it(client, mixed):
    page = client.get(f"{URL}/{mixed['dinars']}").json()
    assert page["currency"] == KWD
    added = client.post(f"{URL}/{mixed['dinars']}/balances", json={"date": "2026-05-20", "amount": "2.500"})
    assert added.status_code == 200
    assert balances_of(client, mixed["dinars"])[0]["amount_cents"] == 2500
    refused = client.post(f"{URL}/{mixed['dinars']}/balances", json={"date": "2026-05-21", "amount": "2.5000"})
    assert refused.status_code == 422


def test_the_update_screen_rows_carry_each_accounts_currency_and_read_amounts_in_it(client, mixed):
    rows = {r["name"]: r for r in client.get("/api/balances/update").json()["rows"]}
    assert (rows["Test dollars"]["currency"], rows["Test euros"]["currency"], rows["Test dinars"]["currency"]) == (USD, EUR, KWD)
    saved = client.post("/api/balances/update", json={
        "date": "2026-06-03", "amounts": {str(mixed["dinars"]): "3.250", str(mixed["euros"]): "120.00"},
        "versions": {str(mixed["dinars"]): None, str(mixed["euros"]): None}})
    assert saved.status_code == 200
    again = {r["name"]: r for r in saved.json()["rows"]}
    assert (again["Test dinars"]["existing_cents"], again["Test euros"]["existing_cents"]) == (3250, 12000)


def test_a_net_worth_series_for_one_account_is_in_its_own_currency(client, mixed):
    body = client.get(f"/api/networth?account_id={mixed['euros']}").json()
    assert body["series"][-1]["net_worth"] == 10000 and body["limited"] is None
