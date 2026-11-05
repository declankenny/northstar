"""The admin Currencies page's endpoint. Synthetic data only."""

from conftest import add_account, op, type_id, with_db
from northstar import accounts, currencies

URL = "/api/currencies"
ASSET, LIABILITY = 1, 2


def by_code(client):
    return {row["code"]: row for row in client.get(URL).json()["currencies"]}


def test_it_lists_the_whole_catalog_in_code_order(client):
    rows = client.get(URL).json()["currencies"]
    assert len(rows) == 155
    assert [r["code"] for r in rows] == sorted(r["code"] for r in rows)
    assert rows[0].keys() == {"code", "name", "minor_units", "is_enabled", "account_count"}


def test_a_row_has_the_stored_precision_and_flag(client):
    rows = by_code(client)
    assert (rows["JPY"]["name"], rows["JPY"]["minor_units"], rows["JPY"]["is_enabled"]) == ("Yen", 0, False)
    assert rows["KWD"]["minor_units"] == 3 and rows["USD"]["minor_units"] == 2


def test_the_flag_is_the_stored_one_and_the_system_currency_is_not_special(client):
    with with_db(client) as conn:
        conn.execute("UPDATE currencies SET is_enabled = 1 WHERE code = 'EUR'")
    rows = by_code(client)
    assert rows["EUR"]["is_enabled"] is True
    assert rows["USD"]["is_enabled"] is False        # it is the system currency, and the list does not know that


def test_the_list_is_the_same_whether_or_not_the_system_currency_is_set(client):
    before = client.get(URL).json()
    with with_db(client) as conn:
        conn.execute("UPDATE system_properties SET value = NULL, read_only = 0 WHERE name = 'system.currency'")
    assert client.get(URL).json() == before


def test_it_counts_open_and_closed_accounts_and_not_deleted_ones(client):
    with with_db(client) as conn:
        add_account(conn, "Test one", ASSET, "Savings")
        closed = add_account(conn, "Test two", ASSET, "Savings")
        gone = add_account(conn, "Test three", ASSET, "Savings")
        add_account(conn, "Test four", LIABILITY, "Mortgage")
        accounts.close_account(op(conn), closed)
        accounts.delete_account(op(conn), gone)
    rows = by_code(client)
    assert rows["USD"]["account_count"] == 3                 # one open, one closed, one liability; the deleted one is not counted
    assert {code: row["account_count"] for code, row in rows.items() if code != "USD"} == {
        code: 0 for code in rows if code != "USD"}


def test_each_account_is_counted_under_its_own_currency(client):
    with with_db(client) as conn:
        conn.execute("UPDATE currencies SET is_enabled = 1 WHERE code = 'KWD'")
        accounts.add_account(op(conn), "Test one", ASSET, type_id(conn, "Savings"), None,
                             currencies.by_code(conn, "KWD").id)
        add_account(conn, "Test two", ASSET, "Savings")
    rows = by_code(client)
    assert (rows["KWD"]["account_count"], rows["USD"]["account_count"]) == (1, 1)


def test_an_ordinary_user_is_refused_and_so_is_someone_signed_out(member_client, anon_client):
    assert member_client.get(URL).status_code == 403
    assert anon_client.get(URL).status_code == 401


def test_it_only_reads(client):
    assert client.post(URL, json={}).status_code in (404, 405)
    assert client.put(f"{URL}/USD", json={"is_enabled": True}).status_code in (404, 405)
    assert client.delete(f"{URL}/USD").status_code in (404, 405)
