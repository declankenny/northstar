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


def test_account_names_in_the_list_link_to_the_detail_page_and_edit_link_is_gone(client):
    acct = make_account(client)
    page = client.get("/accounts").text
    assert f'<a href="/accounts/{acct}">Test account</a>' in page
    assert f"/accounts/{acct}/edit" not in page


def test_account_names_on_the_update_screen_link_to_the_detail_page(client):
    acct = make_account(client)
    assert f'<a href="/accounts/{acct}">Test account</a>' in client.get("/balances/update").text


def test_detail_page_shows_summary_and_history_newest_first(client):
    acct = make_account(client, "Everyday")
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-01-31", 100000)
        add_balance(conn, acct, "2026-10-20", 123456)
        conn.execute("UPDATE balances SET note = 'after payday' WHERE as_of_date = '2026-10-20'")
    page = client.get(f"/accounts/{acct}").text
    assert "Everyday" in page and "Asset" in page and "Checking" in page
    assert "$1,234.56" in page and "as of 2026-10-20" in page
    assert "10 days" in page and "Stale" not in page
    assert "2 since 2026-01-31" in page
    assert page.index("2026-10-20</td>") < page.index("2026-01-31</td>")   # newest first
    assert "after payday" in page and "manual" in page and "$1,000.00" in page


def test_detail_page_flags_a_stale_account(client):
    acct = make_account(client)
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-08-01", 100)
    assert "Stale" in client.get(f"/accounts/{acct}").text


def test_detail_page_of_account_without_balances(client):
    acct = make_account(client)
    page = client.get(f"/accounts/{acct}").text
    assert "None yet" in page and "No balance yet" in page and "No balances yet" in page
    assert f'action="/accounts/{acct}/balances"' in page   # the Add a balance form is offered


def test_detail_page_of_closed_account_shows_badge_and_reopen(client):
    acct = make_account(client)
    client.post(f"/accounts/{acct}/close")
    page = client.get(f"/accounts/{acct}").text
    assert "Closed" in page and f"/accounts/{acct}/reopen" in page and f"/accounts/{acct}/close" not in page
    assert "Reopen the account to add or change its balances" in page


def test_detail_page_of_closed_account_is_never_flagged_stale(client):
    acct = make_account(client)
    with with_db(client) as conn:
        add_balance(conn, acct, "2025-01-01", 0)
    client.post(f"/accounts/{acct}/close")
    page = client.get(f"/accounts/{acct}").text
    assert "Stale" not in page and 'class="stale"' not in page


def test_detail_page_offers_edit_close_and_delete(client):
    acct = make_account(client)
    page = client.get(f"/accounts/{acct}").text
    for target in ("edit", "close", "delete"):
        assert f"/accounts/{acct}/{target}" in page


def test_detail_page_of_a_liability_shows_the_amount_owed(client):
    acct = make_account(client, "Mortgage", 2, "Mortgage")
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-10-01", 25000000)
    page = client.get(f"/accounts/{acct}").text
    assert "Liability" in page and "$250,000.00" in page


def test_detail_page_escapes_names_notes_and_balance_notes(client):
    acct = make_account(client, "<b>x</b>")
    with with_db(client) as conn:
        conn.execute("UPDATE accounts SET notes = '<script>alert(1)</script>' WHERE id = ?", (acct,))
        add_balance(conn, acct, "2026-10-01", 1)
        conn.execute("UPDATE balances SET note = '<i>n</i>'")
    page = client.get(f"/accounts/{acct}").text
    for raw in ("<b>x</b>", "<script>alert(1)</script>", "<i>n</i>"):
        assert raw not in page
    assert "&lt;script&gt;" in page


def test_missing_account_shows_message(client):
    response = client.get("/accounts/999")
    assert response.status_code == 404 and "no longer exists" in response.text


def test_new_is_still_the_add_form_not_an_account(client):
    assert "Add asset account" in client.get("/accounts/new?class=asset").text


def test_saving_an_edit_returns_to_the_detail_page(client):
    acct = make_account(client)
    response = client.post(f"/accounts/{acct}", data={"name": "Renamed", "type_id": "2", "notes": ""})
    assert response.url.path == f"/accounts/{acct}" and "Renamed" in response.text


def test_edit_page_cancel_goes_back_to_the_detail_page(client):
    acct = make_account(client)
    assert f'href="/accounts/{acct}">Cancel' in client.get(f"/accounts/{acct}/edit").text


def test_changing_class_returns_to_the_detail_page(client):
    acct = make_account(client)
    with with_db(client) as conn:
        loan = conn.execute("SELECT id FROM account_types WHERE name = 'Loan'").fetchone()["id"]
    response = client.post(f"/accounts/{acct}/change-class", data={"type_id": str(loan)})
    assert response.url.path == f"/accounts/{acct}" and "Liability" in response.text


def test_failed_edit_stays_on_the_edit_form(client):
    acct = make_account(client)
    response = client.post(f"/accounts/{acct}", data={"name": "", "type_id": "1"})
    assert response.status_code == 400 and "Name is required" in response.text
