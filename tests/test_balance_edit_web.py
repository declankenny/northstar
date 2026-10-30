from datetime import date

import pytest

from conftest import add_account, add_balance, with_db

TODAY = date(2026, 10, 30)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("northstar.clock.today", lambda: TODAY)


def make_account(client, name="Test account", class_id=1, type_name="Checking"):
    with with_db(client) as conn:
        return add_account(conn, name, class_id, type_name)


def balances_of(client, account_id):
    with with_db(client) as conn:
        return {r["as_of_date"]: (r["amount_cents"], r["note"]) for r in
                conn.execute("SELECT * FROM balances WHERE account_id = ?", (account_id,))}


def bid(client, account_id, as_of):
    with with_db(client) as conn:
        return conn.execute("SELECT id FROM balances WHERE account_id = ? AND as_of_date = ?",
                            (account_id, as_of)).fetchone()["id"]


def add(client, account_id, **fields):
    return client.post(f"/accounts/{account_id}/balances", data=fields)


# -- Add a balance form --

def test_detail_page_has_an_add_form_defaulting_to_today(client):
    acct = make_account(client)
    page = client.get(f"/accounts/{acct}").text
    assert f'action="/accounts/{acct}/balances"' in page and 'value="2026-10-30"' in page


def test_add_a_balance_and_see_it_with_a_notice(client):
    acct = make_account(client)
    response = add(client, acct, date="2026-10-15", amount="1,234.56", note="after payday")
    assert response.status_code == 200 and response.url.path == f"/accounts/{acct}"
    assert "Balance added." in response.text and "after payday" in response.text and "$1,234.56" in response.text
    assert balances_of(client, acct) == {"2026-10-15": (123456, "after payday")}


def test_adding_an_existing_date_replaces_it(client):
    acct = make_account(client)
    add(client, acct, date="2026-10-15", amount="10", note="first")
    response = add(client, acct, date="2026-10-15", amount="12.50", note="second")
    assert "Balance updated." in response.text
    assert balances_of(client, acct) == {"2026-10-15": (1250, "second")}


def test_adding_identical_values_says_nothing_changed(client):
    acct = make_account(client)
    add(client, acct, date="2026-10-15", amount="10", note="")
    assert "Nothing changed" in add(client, acct, date="2026-10-15", amount="10", note="").text


@pytest.mark.parametrize("fields, message", [
    ({"date": "2026-10-31", "amount": "5"}, "future"),
    ({"date": "junk", "amount": "5"}, "valid date"),
    ({"date": "2026-10-15", "amount": "1.234"}, "Enter an amount"),
    ({"date": "2026-10-15", "amount": ""}, "Enter an amount"),
    ({"date": "2026-10-15", "amount": "5", "note": "x" * 501}, "too long"),
])
def test_bad_add_shows_the_error_keeps_typing_and_saves_nothing(client, fields, message):
    acct = make_account(client)
    response = add(client, acct, **fields)
    assert response.status_code == 400 and message in response.text
    assert f'value="{fields["amount"]}"' in response.text
    assert balances_of(client, acct) == {}


def test_add_to_a_closed_account_is_refused_even_if_posted_directly(client):
    acct = make_account(client)
    client.post(f"/accounts/{acct}/close")
    response = add(client, acct, date="2026-10-15", amount="5")
    assert response.status_code == 400 and "Reopen it before changing its balances" in response.text
    assert balances_of(client, acct) == {}


def test_add_form_and_row_links_are_hidden_on_closed_accounts(client):
    acct = make_account(client)
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-10-01", 0)
    client.post(f"/accounts/{acct}/close")
    page = client.get(f"/accounts/{acct}").text
    assert f'action="/accounts/{acct}/balances"' not in page
    assert "/balances/" not in page.split("<table")[1]      # no Edit or Delete links on the rows


def test_a_saved_notice_cannot_be_forged_from_the_address(client):
    acct = make_account(client)
    page = client.get(f"/accounts/{acct}?saved=<script>alert(1)</script>").text
    assert "<script>alert(1)</script>" not in page and 'role="status"' not in page


# -- row links --

def test_each_row_links_to_edit_and_delete(client):
    acct = make_account(client)
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-10-01", 100)
    row = bid(client, acct, "2026-10-01")
    page = client.get(f"/accounts/{acct}").text
    assert f"/balances/{row}/edit" in page and f"/balances/{row}/delete" in page


# -- edit --

def test_edit_page_is_prefilled(client):
    acct = make_account(client, "Everyday")
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-10-01", 123456)
        conn.execute("UPDATE balances SET note = 'n1'")
    page = client.get(f"/balances/{bid(client, acct, '2026-10-01')}/edit").text
    assert 'value="2026-10-01"' in page and 'value="1234.56"' in page and 'value="n1"' in page
    assert "Everyday" in page and f'href="/accounts/{acct}">Cancel' in page


def test_edit_a_balance_and_return_to_the_account(client):
    acct = make_account(client)
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-10-01", 100)
    row = bid(client, acct, "2026-10-01")
    response = client.post(f"/balances/{row}/edit", data={"date": "2026-09-20", "amount": "7.77", "note": "fixed"})
    assert response.url.path == f"/accounts/{acct}" and "Balance updated." in response.text
    assert balances_of(client, acct) == {"2026-09-20": (777, "fixed")}


def test_edit_to_a_date_in_use_is_refused_and_keeps_typing(client):
    acct = make_account(client)
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-10-01", 100)
        add_balance(conn, acct, "2026-09-01", 200)
    row = bid(client, acct, "2026-10-01")
    response = client.post(f"/balances/{row}/edit", data={"date": "2026-09-01", "amount": "9.99", "note": ""})
    assert response.status_code == 400 and "already a balance on 2026-09-01" in response.text
    assert 'value="9.99"' in response.text
    assert balances_of(client, acct)["2026-10-01"] == (100, None)


@pytest.mark.parametrize("data, message", [
    ({"date": "2026-10-31", "amount": "1"}, "future"),
    ({"date": "2026-10-01", "amount": "abc"}, "Enter an amount"),
    ({"date": "", "amount": "1"}, "valid date"),
])
def test_bad_edit_is_refused(client, data, message):
    acct = make_account(client)
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-10-01", 100)
    response = client.post(f"/balances/{bid(client, acct, '2026-10-01')}/edit", data=data)
    assert response.status_code == 400 and message in response.text
    assert balances_of(client, acct) == {"2026-10-01": (100, None)}


def test_edit_on_a_closed_account_is_refused(client):
    acct = make_account(client)
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-10-01", 0)
    row = bid(client, acct, "2026-10-01")
    client.post(f"/accounts/{acct}/close")
    assert "Reopen the account" in client.get(f"/balances/{row}/edit").text
    response = client.post(f"/balances/{row}/edit", data={"date": "2026-10-01", "amount": "5", "note": ""})
    assert response.status_code == 400 and balances_of(client, acct) == {"2026-10-01": (0, None)}


# -- delete --

def test_delete_confirmation_then_delete(client):
    acct = make_account(client)
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-10-01", 123456)
        add_balance(conn, acct, "2026-09-01", 200)
    row = bid(client, acct, "2026-10-01")
    page = client.get(f"/balances/{row}/delete").text
    assert "$1,234.56" in page and "2026-10-01" in page
    assert len(balances_of(client, acct)) == 2                      # the GET deleted nothing
    response = client.post(f"/balances/{row}/delete")
    assert response.url.path == f"/accounts/{acct}" and "Balance deleted." in response.text
    assert list(balances_of(client, acct)) == ["2026-09-01"]


def test_delete_on_a_closed_account_is_refused(client):
    acct = make_account(client)
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-10-01", 0)
    row = bid(client, acct, "2026-10-01")
    client.post(f"/accounts/{acct}/close")
    response = client.post(f"/balances/{row}/delete")
    assert response.status_code == 400 and balances_of(client, acct) == {"2026-10-01": (0, None)}


def test_missing_balance_shows_a_message(client):
    for method, path in (("get", "/balances/999/edit"), ("get", "/balances/999/delete"),
                         ("post", "/balances/999/edit"), ("post", "/balances/999/delete")):
        response = getattr(client, method)(path)
        assert response.status_code == 404 and "no longer exists" in response.text


def test_update_balances_page_still_works_next_to_the_new_routes(client):
    assert client.get("/balances/update").status_code == 200
    assert client.post("/balances/update", data={"date": "2026-10-30"}).status_code == 200


def test_cross_site_posts_are_refused(client):
    acct = make_account(client)
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-10-01", 100)
    row = bid(client, acct, "2026-10-01")
    evil = {"Origin": "https://evil.example"}
    assert add_response(client, acct, evil).status_code == 403
    assert client.post(f"/balances/{row}/edit", data={"date": "2026-10-01", "amount": "9"}, headers=evil).status_code == 403
    assert client.post(f"/balances/{row}/delete", headers=evil).status_code == 403
    assert balances_of(client, acct) == {"2026-10-01": (100, None)}


def add_response(client, acct, headers):
    return client.post(f"/accounts/{acct}/balances", data={"date": "2026-10-15", "amount": "5"}, headers=headers)


def test_notes_and_names_are_escaped_on_every_page(client):
    acct = make_account(client, "<b>x</b>")
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-10-01", 1)
        conn.execute("UPDATE balances SET note = '<i>n</i>'")
    row = bid(client, acct, "2026-10-01")
    for path in (f"/balances/{row}/edit", f"/balances/{row}/delete", f"/accounts/{acct}"):
        page = client.get(path).text
        assert "<b>x</b>" not in page and "<i>n</i>" not in page
