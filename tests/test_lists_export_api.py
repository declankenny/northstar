"""The export endpoint: a list's applied view as a CSV download. The lists named here exist only in these tests. Synthetic data only."""

import csv
import io

import pytest
from fastapi.testclient import TestClient

from conftest import add_account, add_balance, op, sign_in, with_db
from northstar import clock, currencies, rates
from northstar.lists import loader
from northstar.lists.listdef import ListDef
from northstar.web.app import create_app

BALANCES = ListDef("balances_export_test", "live_balance_values",
                   ("as_of_date", "account", "account.type", "amount_cents", "account.currency", "reporting_value", "note"), ("as_of_date", "desc"))
SECRET = ListDef("secret_export_test", "currencies", ("code", "name"), ("code", "asc"), admin_only=True)
TODAY = clock.today()


@pytest.fixture(autouse=True)
def lists():
    for definition in (BALANCES, SECRET):
        loader.register(definition)
    yield
    for definition in (BALANCES, SECRET):
        loader._DEFINITIONS.pop(definition.key)


@pytest.fixture
def household(client):
    """Dollars and euros: a dollar account and a euro account with a rate from 1 March 2026, and fifteen balances, one of them negative."""
    with with_db(client) as conn:
        currencies.update_currency(op(conn), "EUR", True, "2020-01-01", TODAY)
        rates.add_rate(op(conn), "EUR", "2026-03-01", "1.10", TODAY)
        usd = add_account(conn, "Test dollars", 1, "Savings")
        card = add_account(conn, "Test card", 2, "Credit card")
        eur = conn.execute("INSERT INTO accounts (name, type_id, currency_id, created_by, updated_by) VALUES "
                           "('Test euros', (SELECT id FROM account_types WHERE name = 'Savings'), "
                           "(SELECT id FROM currencies WHERE code = 'EUR'), 1, 1)").lastrowid
        for number in range(1, 13):
            add_balance(conn, [usd, eur][number % 2], f"2026-04-{number:02d}", 10_000 + number)
        add_balance(conn, eur, "2026-02-01", 20_000)                                 # before the first euro rate
        add_balance(conn, card, "2026-04-15", -8_050)                                # a negative amount
        add_balance(conn, usd, "2026-05-01", 500)
        conn.execute("UPDATE balances SET note = '=1+1' WHERE as_of_date = '2026-05-01'")
        conn.execute("UPDATE balances SET note = 'has \"quotes\", commas\nand lines' WHERE as_of_date = '2026-04-15'")
        conn.commit()
    return {"usd": usd, "eur": eur, "card": card}


def export(client, body=None, key="balances_export_test"):
    return client.post(f"/api/lists/{key}/export", json=body or {})


def rows(response):
    text = response.content.decode("utf-8")
    assert text.startswith("﻿")
    return list(csv.reader(io.StringIO(text[1:], newline="")))


def test_it_is_a_csv_download_named_for_the_list_and_the_day_that_is_never_stored(client, household):
    response = export(client)
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == f'attachment; filename="northstar-balances-export-test-{TODAY.isoformat()}.csv"'
    assert response.headers["cache-control"] == "no-store"
    assert response.content[:3] == b"\xef\xbb\xbf"                                   # a byte-order mark, so a spreadsheet reads the accents


def test_it_has_the_lists_columns_as_they_read_on_screen_and_every_row_whatever_a_page_would_hold(client, household):
    result = rows(export(client, {"page": 2, "page_size": 10}))
    assert result[0] == ["Date", "Account", "Account › Type", "Value", "Account › Currency", "Reporting value", "Note"]
    assert len(result) - 1 == 15 == client.post("/api/lists/balances_export_test", json={}).json()["total"]
    assert [r[0] for r in result[1:]] == sorted((r[0] for r in result[1:]), reverse=True)           # the list's own order: newest first


def test_amounts_are_plain_decimals_in_their_own_currency_and_the_reporting_value_in_the_system_currency(client, household):
    by = {(r[0], r[1]): r for r in rows(export(client))[1:]}
    euros = by[("2026-04-01", "Test euros")]
    assert euros[3] == "100.01" and euros[4] == "EUR" and euros[5] == "110.01"                     # 100.01 EUR at 1.10 is 110.011: to the cent
    dollars = by[("2026-04-02", "Test dollars")]
    assert dollars[3] == "100.02" and dollars[4] == "USD" and dollars[5] == "100.02"                # in the system currency, the value is its own
    assert by[("2026-04-15", "Test card")][3] == "-80.50"                                          # a negative keeps its sign and is not made text


def test_a_balance_with_no_rate_yet_has_an_empty_reporting_value_cell(client, household):
    early = [r for r in rows(export(client))[1:] if r[0] == "2026-02-01"][0]
    assert early[3] == "200.00" and early[5] == ""


def test_notes_with_quotes_commas_and_line_breaks_read_back_exactly_and_a_formula_is_made_text(client, household):
    notes = {r[0]: r[6] for r in rows(export(client))[1:]}
    assert notes["2026-04-15"] == 'has "quotes", commas\nand lines'
    assert notes["2026-05-01"] == "'=1+1"


def test_it_uses_the_persons_own_columns_and_default_filter_like_the_list_does_and_a_request_that_names_them_wins(client, household):
    assert client.put("/api/lists/balances_export_test/columns", json={"columns": ["note", "as_of_date"]}).status_code == 200
    saved = client.post("/api/lists/balances_export_test/filters", json={
        "name": "Euros", "conditions": [{"field": "account.currency", "operator": "is_any_of", "value": [_currency_id(client, "EUR")]}]}).json()
    client.put(f"/api/lists/balances_export_test/filters/{saved['filters'][0]['id']}", json={"is_default": True})
    mine = rows(export(client))
    assert mine[0] == ["Note", "Date"] and len(mine) - 1 == 7 == client.post("/api/lists/balances_export_test", json={}).json()["total"]
    named = rows(export(client, {"columns": ["as_of_date"], "filters": []}))
    assert named[0] == ["Date"] and len(named) - 1 == 15


def test_it_applies_a_search_a_sort_and_a_group_like_the_list_does(client, household):
    found = rows(export(client, {"columns": ["account", "note"], "search": "quotes"}))
    assert [r[0] for r in found[1:]] == ["Test card"]
    ascending = [r[0] for r in rows(export(client, {"columns": ["as_of_date"], "sort": {"field": "as_of_date", "direction": "asc"}}))[1:]]
    assert ascending == sorted(ascending)
    grouped = rows(export(client, {"columns": ["account", "as_of_date"], "group": "account"}))
    accounts = [r[0] for r in grouped[1:]]
    assert accounts == sorted(accounts, key=str.lower) and len(accounts) == 15                    # grouped order, and no row for a group's header


def test_an_empty_result_is_the_headers_alone(client, household):
    result = export(client, {"columns": ["account", "as_of_date"], "search": "nothing like this"})
    assert result.status_code == 200 and result.content.decode("utf-8") == "﻿Account,Date\r\n"


def test_it_changes_nothing_the_person_has_saved(client, household):
    with with_db(client) as conn:
        before = [tuple(r) for r in conn.execute("SELECT * FROM user_list_prefs")], conn.execute("SELECT COUNT(*) FROM sys_operations").fetchone()[0]
    export(client, {"columns": ["account"], "page_size": 100})
    with with_db(client) as conn:
        assert ([tuple(r) for r in conn.execute("SELECT * FROM user_list_prefs")], conn.execute("SELECT COUNT(*) FROM sys_operations").fetchone()[0]) == before


@pytest.mark.parametrize("body", [{"columns": ["no_such_column"]}, {"columns": []}, {"columns": ["account", "account"]},
                                  {"filters": [{"field": "note", "operator": "nonsense", "value": "x"}]}, {"sort": {"field": "nope", "direction": "asc"}},
                                  {"group": "amount_cents"}, {"surprise": 1}])
def test_a_request_that_breaks_a_rule_is_refused_before_a_file_starts(client, household, body):
    response = export(client, body)
    assert response.status_code == 422 and response.headers["content-type"].startswith("application/json")


def test_it_is_for_people_who_are_signed_in_and_for_a_list_they_may_see(tmp_path, client, anon_client, household):
    assert anon_client.post("/api/lists/balances_export_test/export", json={}).status_code == 401
    member = sign_in(TestClient(create_app(tmp_path / "web.db")), "member@example.com", "Member", is_admin=False)
    assert export(member).status_code == 200                                                       # not only for admins
    assert export(member, key="secret_export_test").status_code == 403
    assert export(client, key="secret_export_test").status_code == 200
    assert export(client, key="no_such_list").status_code == 404


def test_the_real_balances_list_exports_under_its_own_name(client, household):
    response = client.post("/api/lists/balances/export", json={})
    assert response.status_code == 200
    assert response.headers["content-disposition"] == f'attachment; filename="northstar-balances-{TODAY.isoformat()}.csv"'
    result = rows(response)
    assert result[0] == ["Date", "Account", "Account › Type", "Value", "Account › Currency", "Reporting value", "Note"]
    assert len(result) - 1 == 15


def _currency_id(client, code):
    with with_db(client) as conn:
        return conn.execute("SELECT id FROM currencies WHERE code = ?", (code,)).fetchone()[0]
