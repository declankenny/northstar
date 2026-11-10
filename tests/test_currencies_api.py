"""The admin Currencies list (a list of the framework, `/api/lists/currencies`): every currency of the catalog with its stored
precision and flag and how many accounts use it. Synthetic data only."""

from conftest import add_account, op, type_id, with_db
from northstar import accounts, currencies

LIST = "/api/lists/currencies"
ASSET, LIABILITY = 1, 2


def every_row(client, **request):
    """All the rows, however many pages: the list shows 100 at a time and the catalog is longer."""
    rows, page = [], 1
    while True:
        body = client.post(LIST, json={**request, "page": page}).json()
        rows += body["rows"]
        if page >= body["pages"]:
            return rows
        page += 1


def by_code(client):
    return {row["code"]: row for row in every_row(client)}


def test_it_lists_the_whole_catalog_in_code_order_across_pages(client):
    first = client.post(LIST, json={}).json()
    assert (first["total"], first["pages"], first["page_size"], len(first["rows"])) == (155, 2, 100, 100)
    rows = every_row(client)
    assert len(rows) == 155
    assert [r["code"] for r in rows] == sorted(r["code"] for r in rows)


def test_it_opens_with_no_filter_and_the_columns_the_old_page_had(client):
    body = client.post(LIST, json={}).json()
    assert body["filters"] == [] and body["default_filter_id"] is None
    assert body["default_columns"] == ["code", "name", "minor_units", "is_enabled", "account_count"]
    assert [c["label"] for c in body["columns"]] == ["Code", "Name", "Decimal places", "Enabled", "Accounts"]


def test_a_row_has_the_stored_precision_and_flag_and_its_code_opens_its_page(client):
    rows = by_code(client)
    assert (rows["JPY"]["name"], rows["JPY"]["minor_units"], rows["JPY"]["is_enabled"]) == ("Yen", 0, 0)
    assert rows["KWD"]["minor_units"] == 3 and rows["USD"]["minor_units"] == 2
    assert rows["EUR"]["_links"] == {"code": "/currencies/EUR"}


def test_the_flag_is_the_stored_one_and_the_system_currency_is_not_special(client):
    with with_db(client) as conn:
        conn.execute("UPDATE currencies SET is_enabled = 1 WHERE code = 'EUR'")
    rows = by_code(client)
    assert rows["EUR"]["is_enabled"] == 1
    assert rows["USD"]["is_enabled"] == 1            # the system currency is always enabled, and the list does not know it is the one


def test_the_list_is_the_same_whether_or_not_the_system_currency_is_set(client):
    before = client.post(LIST, json={}).json()
    with with_db(client) as conn:
        conn.execute("UPDATE system_properties SET value = NULL, read_only = 0 WHERE name = 'system.currency'")
    assert client.post(LIST, json={}).json() == before


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
        conn.execute("INSERT INTO exchange_rates (currency_id, rate_date, rate, source, created_by, updated_by) "
                     "VALUES ((SELECT id FROM currencies WHERE code = 'KWD'), '2026-01-01', '3.25', 'manual', 1, 1)")
        accounts.add_account(op(conn), "Test one", ASSET, type_id(conn, "Savings"), None,
                             currencies.by_code(conn, "KWD").id)
        add_account(conn, "Test two", ASSET, "Savings")
    rows = by_code(client)
    assert (rows["KWD"]["account_count"], rows["USD"]["account_count"]) == (1, 1)


def test_enabled_and_in_use_are_filters_a_person_makes(client):
    with with_db(client) as conn:
        add_account(conn, "Test one", ASSET, "Savings")
        conn.execute("UPDATE currencies SET is_enabled = 1 WHERE code IN ('EUR', 'KWD')")
    enabled = every_row(client, filters=[{"field": "is_enabled", "operator": "is_yes"}])
    assert [r["code"] for r in enabled] == ["EUR", "KWD", "USD"]
    in_use = every_row(client, filters=[{"field": "account_count", "operator": "at_least", "value": 1}])
    assert [r["code"] for r in in_use] == ["USD"]


def test_search_finds_a_currency_by_code_or_name(client):
    assert [r["code"] for r in every_row(client, search="kuwait")] == ["KWD"]
    assert "USD" in [r["code"] for r in every_row(client, search="usd")]


def test_it_sorts_by_accounts_used(client):
    with with_db(client) as conn:
        add_account(conn, "Test one", ASSET, "Savings")
    top = client.post(LIST, json={"sort": {"field": "account_count", "direction": "desc"}}).json()["rows"][0]
    assert (top["code"], top["account_count"]) == ("USD", 1)


def test_it_exports_what_it_shows(client):
    response = client.post(f"{LIST}/export", json={"filters": [{"field": "code", "operator": "contains", "value": "KWD"}]})
    lines = response.content.decode("utf-8-sig").splitlines()
    assert lines == ["Code,Name,Decimal places,Enabled,Accounts", "KWD,Kuwaiti Dinar,3,false,0"]


def test_an_ordinary_user_is_refused_and_so_is_someone_signed_out(member_client, anon_client):
    assert member_client.post(LIST, json={}).status_code == 403
    assert member_client.post(f"{LIST}/export", json={}).status_code == 403
    assert anon_client.post(LIST, json={}).status_code == 401


def test_the_old_list_endpoint_is_gone_and_the_catalog_cannot_be_created_replaced_or_deleted(client):
    assert client.get("/api/currencies").status_code in (404, 405)
    assert client.post("/api/currencies", json={}).status_code in (404, 405)
    assert client.put("/api/currencies/USD", json={"is_enabled": True}).status_code in (404, 405)
    assert client.delete("/api/currencies/USD").status_code in (404, 405)
