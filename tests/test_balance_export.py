"""Exporting an account's balances as CSV, and reading that file back in. Synthetic data only."""

import base64
import csv
import io

import pytest

from northstar import balance_export, csvparse
from conftest import add_account, add_balance, with_db

ASSET = 1


@pytest.fixture
def account(client):
    with with_db(client) as conn:
        account_id = add_account(conn, "Demo Savings", ASSET, "Savings")
        add_balance(conn, account_id, "2026-03-31", 120000)
        add_balance(conn, account_id, "2026-01-31", 100000)
        add_balance(conn, account_id, "2026-02-28", -8000)
        conn.commit()
    return account_id


def export(client, account_id):
    return client.get(f"/api/accounts/{account_id}/export")


def rows(response):
    return list(csv.reader(io.StringIO(response.text)))


def test_amounts_are_plain_decimals_from_cents():
    assert [balance_export.format_cents(c) for c in (123456, -8000, 5, -5, 0, 100)] == ["1234.56", "-80.00", "0.05", "-0.05", "0.00", "1.00"]


def test_the_file_has_the_four_columns_and_a_row_per_balance_oldest_first(client, account):
    response = export(client, account)
    assert response.status_code == 200
    assert rows(response) == [
        ["Account ID", "Account Name", "Balance Date", "Balance Amount"],
        [str(account), "Demo Savings", "2026-01-31", "1000.00"],
        [str(account), "Demo Savings", "2026-02-28", "-80.00"],
        [str(account), "Demo Savings", "2026-03-31", "1200.00"],
    ]


def test_it_is_a_download_with_a_name_that_says_what_it_is(client, account):
    response = export(client, account)
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith('attachment; filename="northstar-balances-Demo-Savings-')
    assert response.headers["content-disposition"].endswith('.csv"')
    assert response.headers["cache-control"] == "no-store"


def test_a_name_is_cut_down_for_the_file_name_only():
    from datetime import date
    assert balance_export.file_name('Joint "Checking", ü/2', date(2026, 11, 2)) == "northstar-balances-Joint-Checking-2-2026-11-02.csv"
    assert balance_export.file_name("§§", date(2026, 11, 2)) == "northstar-balances-2026-11-02.csv"


def test_a_name_with_a_comma_or_quote_stays_one_cell(client):
    with with_db(client) as conn:
        account_id = add_account(conn, 'Joint, "main"', ASSET, "Savings")
        add_balance(conn, account_id, "2026-01-31", 100)
        conn.commit()
    assert rows(export(client, account_id))[1][1] == 'Joint, "main"'


def test_an_account_with_no_balances_is_just_the_header(client):
    with with_db(client) as conn:
        account_id = add_account(conn, "Empty", ASSET, "Savings")
        conn.commit()
    assert rows(export(client, account_id)) == [balance_export.HEADER]


def test_a_closed_account_can_be_exported(client, account):
    with with_db(client) as conn:
        conn.execute("UPDATE accounts SET is_open = 0 WHERE id = ?", (account,))
        conn.commit()
    assert export(client, account).status_code == 200


def test_only_that_accounts_balances_are_in_it(client, account):
    with with_db(client) as conn:
        other = add_account(conn, "Other", ASSET, "Savings")
        add_balance(conn, other, "2026-01-31", 999)
        conn.commit()
    assert {row[0] for row in rows(export(client, account))[1:]} == {str(account)}


def test_an_unknown_account_is_not_found(client):
    assert export(client, 999).status_code == 404


def test_signed_out_is_refused(anon_client):
    assert anon_client.get("/api/accounts/1/export").status_code == 401


def test_an_ordinary_user_may_export(member_client):
    with with_db(member_client) as conn:
        account_id = add_account(conn, "Demo", ASSET, "Savings")
        conn.commit()
    assert export(member_client, account_id).status_code == 200


def test_the_import_maps_the_export_by_itself(client, account):
    table = csvparse.read_table(export(client, account).content)
    mapping = csvparse.suggest_mapping(table.headers)
    assert (mapping.date, mapping.balance, mapping.note, mapping.currency) == (2, 3, None, None)


def test_importing_an_export_back_into_the_same_account_changes_nothing(client, account):
    data = export(client, account).content
    body = {"content": base64.b64encode(data).decode("ascii"), "file_name": "export.csv",
            "mapping": {"date": 2, "balance": 3, "note": None, "currency": None}, "policy": "skip", "date_format": None}
    review = client.post(f"/api/accounts/{account}/import/review", json=body)
    assert review.status_code == 200
    assert review.json()["can_commit"] is True
    assert review.json()["counts"] == {"add": 0, "replace": 0, "unchanged": 3, "skip": 0}


def test_importing_an_export_into_a_new_account_recreates_the_balances(client, account):
    data = export(client, account).content
    with with_db(client) as conn:
        target = add_account(conn, "Copy", ASSET, "Savings")
        conn.commit()
    body = {"content": base64.b64encode(data).decode("ascii"), "file_name": "export.csv",
            "mapping": {"date": 2, "balance": 3, "note": None, "currency": None}, "policy": "skip", "date_format": None}
    review = client.post(f"/api/accounts/{target}/import/review", json=body)
    assert review.json()["counts"]["add"] == 3
    done = client.post(f"/api/accounts/{target}/import/commit", json={**body, "reviewed": review.json()["reviewed"]})
    assert done.status_code == 200
    with with_db(client) as conn:
        got = [tuple(r) for r in conn.execute("SELECT as_of_date, amount_cents FROM live_balances WHERE account_id = ? ORDER BY as_of_date", (target,))]
    assert got == [("2026-01-31", 100000), ("2026-02-28", -8000), ("2026-03-31", 120000)]
