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


def stored(client, account_id):
    with with_db(client) as conn:
        return {r["as_of_date"]: r["amount_cents"] for r in
                conn.execute("SELECT * FROM balances WHERE account_id = ?", (account_id,))}


def post(client, date_text, **amounts):
    data = {"date": date_text}
    data.update({f"amount_{key}": value for key, value in amounts.items()})
    return client.post("/balances/update", data=data)


def test_empty_state_points_to_accounts(client):
    page = client.get("/balances/update").text
    assert "No open accounts yet" in page


def test_page_defaults_to_today_and_shows_context_columns(client):
    acct = make_account(client, "Everyday")
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-08-01", 123456)  # 90 days old, limit 35
    page = client.get("/balances/update").text
    assert 'value="2026-10-30"' in page
    assert "Everyday" in page and "$1,234.56" in page and "90 days" in page and "Stale" in page


def test_account_with_no_balance_says_so(client):
    make_account(client)
    assert "No balance yet" in client.get("/balances/update").text


def test_closed_accounts_are_not_listed(client):
    make_account(client, "Open one")
    closed = make_account(client, "Closed one", type_name="Savings")
    client.post(f"/accounts/{closed}/close")
    page = client.get("/balances/update").text
    assert "Open one" in page and "Closed one" not in page


def test_date_form_works_without_javascript_and_marks_saved_amounts(client):
    acct = make_account(client)
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-10-30", 5000)
    page = client.get("/balances/update").text
    assert "<noscript><button>Show date</button></noscript>" in page   # fallback button
    assert 'data-saved="50.00"' in page                                # what is already saved
    other_date = client.get("/balances/update?date=2026-09-01").text
    assert 'data-saved="50.00"' not in other_date and 'data-saved=""' in other_date


def test_other_date_shows_that_dates_existing_amount(client):
    acct = make_account(client)
    with with_db(client) as conn:
        add_balance(conn, acct, "2026-09-30", 123456)
    page = client.get("/balances/update?date=2026-09-30").text
    assert 'value="1234.56"' in page
    assert 'value="1234.56"' not in client.get("/balances/update").text


def test_save_one_balance_and_see_the_confirmation(client):
    acct = make_account(client)
    response = post(client, "2026-10-30", **{str(acct): "1,234.56"})
    assert response.status_code == 200
    assert "Saved: 1 added, 0 updated, 0 unchanged." in response.text
    assert stored(client, acct) == {"2026-10-30": 123456}


def test_amounts_never_appear_in_the_address(client):
    acct = make_account(client)
    response = post(client, "2026-10-30", **{str(acct): "9876.54"})
    assert "9876" not in str(response.url)
    assert "9876" not in str(response.history[0].headers["location"])


def test_blank_rows_are_skipped_and_zero_is_recorded(client):
    a = make_account(client, "A")
    b = make_account(client, "B", type_name="Savings")
    c = make_account(client, "C", 2, "Loan")
    post(client, "2026-10-30", **{str(a): "0", str(b): "", str(c): "250000"})
    assert stored(client, a) == {"2026-10-30": 0}
    assert stored(client, b) == {}
    assert stored(client, c) == {"2026-10-30": 25000000}   # a liability is entered as the amount owed


def test_saving_an_existing_date_edits_it(client):
    acct = make_account(client)
    post(client, "2026-10-30", **{str(acct): "10"})
    response = post(client, "2026-10-30", **{str(acct): "12.50"})
    assert "0 added, 1 updated" in response.text
    assert stored(client, acct) == {"2026-10-30": 1250}


def test_bad_amount_saves_nothing_and_flags_the_row(client):
    good = make_account(client, "Good")
    bad = make_account(client, "Bad", type_name="Savings")
    response = post(client, "2026-10-30", **{str(good): "100", str(bad): "1.234"})
    assert response.status_code == 400
    assert "Nothing was saved" in response.text
    assert "Enter an amount like 1234.56" in response.text
    assert 'value="1.234"' in response.text and 'value="100"' in response.text   # typing kept
    assert stored(client, good) == {} and stored(client, bad) == {}


def test_future_date_is_refused(client):
    acct = make_account(client)
    response = post(client, "2026-10-31", **{str(acct): "100"})
    assert response.status_code == 400 and "future" in response.text
    assert stored(client, acct) == {}


def test_future_date_in_the_address_is_refused_and_page_falls_back_to_today(client):
    response = client.get("/balances/update?date=2030-01-01")
    assert response.status_code == 400 and "future" in response.text
    assert 'value="2026-10-30"' in response.text


def test_nonsense_date_is_refused(client):
    acct = make_account(client)
    assert post(client, "not-a-date", **{str(acct): "5"}).status_code == 400
    assert client.get("/balances/update?date=zzz").status_code == 400


def test_closed_account_cannot_get_a_balance_even_if_posted_directly(client):
    acct = make_account(client)
    client.post(f"/accounts/{acct}/close")
    post(client, "2026-10-30", **{str(acct): "99"})
    assert stored(client, acct) == {}


def test_unrelated_form_fields_are_ignored(client):
    acct = make_account(client)
    response = client.post("/balances/update", data={
        "date": "2026-10-30", f"amount_{acct}": "5", "amount_x": "9", "amount_": "9", "other": "9"})
    assert response.status_code == 200
    assert stored(client, acct) == {"2026-10-30": 500}


def test_account_names_are_escaped(client):
    make_account(client, "<script>alert(1)</script>")
    page = client.get("/balances/update").text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


def test_cross_site_post_is_refused(client):
    acct = make_account(client)
    response = client.post("/balances/update", data={"date": "2026-10-30", f"amount_{acct}": "5"},
                           headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert stored(client, acct) == {}
