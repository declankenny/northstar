"""Choosing a locale, adding a user in one, and the refusal when a form's locale is no longer the saved one. Synthetic data only."""

from datetime import date

import pytest

from conftest import add_account, balances_of, op, type_id, with_db
from northstar import balances, locales, system_properties as sp, users
from northstar.errors import ValidationError

ASSET = 1
TODAY = date(2026, 2, 1)


def saved_locale(conn, email="test@example.com"):
    return conn.execute("SELECT locale FROM users WHERE email = ?", (email,)).fetchone()[0]


def use_locale(client, tag, email="test@example.com"):
    with with_db(client) as conn:
        conn.execute("UPDATE users SET locale = ? WHERE email = ?", (tag, email))


# -- choosing your own --

def test_a_person_can_choose_a_locale_from_the_catalog(client):
    response = client.patch("/api/me", json={"locale": "de-DE"})
    assert response.status_code == 200 and response.json()["locale"]["tag"] == "de-DE"
    assert response.json()["locale"]["decimal_mark"] == ","
    with with_db(client) as conn:
        assert saved_locale(conn) == "de-DE"


def test_a_tag_that_is_not_in_the_catalog_is_refused_and_nothing_changes(client):
    for tag in ("xx-XX", "de-de", "German", ""):
        response = client.patch("/api/me", json={"locale": tag})
        assert response.status_code == 422 and "Choose a number and date format" in response.json()["detail"], tag
    with with_db(client) as conn:
        assert saved_locale(conn) == "en-US"


def test_the_locale_and_the_theme_can_be_changed_together_and_each_alone(client):
    client.patch("/api/me", json={"locale": "fr-FR", "theme": "light"})
    me = client.get("/api/me").json()
    assert (me["locale"]["tag"], me["theme"]) == ("fr-FR", "light")
    client.patch("/api/me", json={"theme": "dark"})
    assert client.get("/api/me").json()["locale"]["tag"] == "fr-FR"


def test_a_person_only_ever_changes_their_own_locale_and_it_is_not_logged(member_client):
    with with_db(member_client) as conn:
        before = conn.execute("SELECT COUNT(*) FROM sys_operations").fetchone()[0]
    assert member_client.patch("/api/me", json={"locale": "ja-JP"}).status_code == 200
    with with_db(member_client) as conn:
        assert saved_locale(conn, "member@example.com") == "ja-JP"
        assert conn.execute("SELECT COUNT(*) FROM sys_operations").fetchone()[0] == before


def test_an_ordinary_user_can_list_the_formats_and_see_the_default(member_client):
    answer = member_client.get("/api/me/locales").json()
    assert answer["default"] == "en-US"
    assert {"tag": "de-CH", "label": "German (Switzerland)"} in answer["locales"] and len(answer["locales"]) == 6
    assert [c["label"] for c in answer["locales"]] == sorted(c["label"] for c in answer["locales"])


def test_the_list_needs_a_signed_in_user(anon_client):
    assert anon_client.get("/api/me/locales").status_code == 401


def test_the_list_follows_the_system_default(client):
    client.put("/api/system-properties/ui.locale.default", json={"value": "fr-FR"})
    assert client.get("/api/me/locales").json()["default"] == "fr-FR"


# -- adding a user in a locale --

NEW = {"email": "new@example.com", "display_name": "Test New", "password": "synthetic-pass-123"}


def test_an_admin_adds_a_user_in_the_chosen_locale(client):
    assert client.post("/api/users", json={**NEW, "locale": "de-CH"}).status_code == 201
    with with_db(client) as conn:
        assert saved_locale(conn, "new@example.com") == "de-CH"


def test_a_user_added_without_a_choice_gets_the_system_default(client):
    client.put("/api/system-properties/ui.locale.default", json={"value": "ja-JP"})
    assert client.post("/api/users", json=NEW).status_code == 201
    with with_db(client) as conn:
        assert saved_locale(conn, "new@example.com") == "ja-JP"


def test_an_unsupported_choice_adds_nobody(client):
    response = client.post("/api/users", json={**NEW, "locale": "xx-XX"})
    assert response.status_code == 422 and "Choose a number and date format" in response.json()["detail"]
    with with_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE email = 'new@example.com'").fetchone()[0] == 0


def test_a_reactivated_user_takes_the_choice_made_on_the_form_not_the_old_one(client):
    first = client.post("/api/users", json={**NEW, "locale": "fr-FR"}).json()["id"]
    assert client.delete(f"/api/users/{first}").status_code == 204
    again = client.post("/api/users", json={**NEW, "locale": "en-GB"})
    assert again.json()["reactivated"] is True
    with with_db(client) as conn:
        assert saved_locale(conn, "new@example.com") == "en-GB"


def test_a_non_admin_cannot_add_a_user(member_client):
    assert member_client.post("/api/users", json={**NEW, "locale": "de-DE"}).status_code == 403


# -- a form whose locale is no longer the saved one --

def setup_account(client, tag="de-DE"):
    use_locale(client, tag)
    with with_db(client) as conn:
        return add_account(conn, "Test savings", ASSET, "Savings")


def amounts(client):
    with with_db(client) as conn:
        return [r[0] for r in conn.execute("SELECT amount_cents FROM live_balances ORDER BY id")]


def test_adding_a_balance_from_a_page_that_is_still_current_works(client):
    account = setup_account(client)
    ok = client.post(f"/api/accounts/{account}/balances", json={"date": "2026-01-31", "amount": "1.234,56", "locale": "de-DE"})
    assert ok.status_code == 200 and amounts(client) == [123456]


def test_a_stale_page_is_refused_with_the_new_format_and_nothing_is_saved(client):
    account = setup_account(client, "de-DE")
    refused = client.post(f"/api/accounts/{account}/balances", json={"date": "2026-01-31", "amount": "1,234.56", "locale": "en-US"})
    assert refused.status_code == 409
    assert refused.json()["locale_changed"] == {"tag": "de-DE", "label": "German (Germany)"}
    assert refused.json()["detail"] == "Your number and date format changed to German (Germany). Nothing was saved."
    assert amounts(client) == []


def test_the_refusal_comes_before_the_amount_is_read(client):
    account = setup_account(client, "de-DE")
    refused = client.post(f"/api/accounts/{account}/balances", json={"date": "2026-01-31", "amount": "nonsense", "locale": "en-US"})
    assert refused.status_code == 409          # not a 422 about the amount


def test_editing_a_balance_from_a_stale_page_is_refused_too(client):
    account = setup_account(client, "en-US")
    client.post(f"/api/accounts/{account}/balances", json={"date": "2026-01-31", "amount": "100.00", "locale": "en-US"})
    entry = balances_of(client, account)[0]
    use_locale(client, "fr-FR")
    refused = client.patch(f"/api/balances/{entry['id']}", json={
        "date": "2026-01-31", "amount": "200.00", "version": entry["version"], "locale": "en-US"})
    assert refused.status_code == 409 and refused.json()["locale_changed"]["tag"] == "fr-FR"
    assert amounts(client) == [10000]


def test_the_bulk_update_is_refused_from_a_stale_page(client):
    account = setup_account(client, "de-DE")
    refused = client.post("/api/balances/update", json={
        "date": "2026-01-31", "amounts": {str(account): "100,00"}, "versions": {str(account): None}, "locale": "en-US"})
    assert refused.status_code == 409 and refused.json()["locale_changed"]["tag"] == "de-DE"
    assert amounts(client) == []
    ok = client.post("/api/balances/update", json={
        "date": "2026-01-31", "amounts": {str(account): "100,00"}, "versions": {str(account): None}, "locale": "de-DE"})
    assert ok.status_code == 200 and amounts(client) == [10000]


def test_adding_an_account_with_a_first_balance_is_refused_from_a_stale_page_and_makes_no_account(client):
    use_locale(client, "de-DE")
    with with_db(client) as conn:
        savings = type_id(conn, "Savings")
    body = {"account_class": "asset", "name": "Test new", "type_id": savings, "amount": "1,5", "locale": "en-US"}
    refused = client.post("/api/accounts", json=body)
    assert refused.status_code == 409
    with with_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM live_accounts").fetchone()[0] == 0
    assert client.post("/api/accounts", json={**body, "locale": "de-DE"}).status_code == 201


def test_a_page_with_no_money_typed_is_never_refused_for_its_locale(client):
    use_locale(client, "de-DE")
    with with_db(client) as conn:
        savings = type_id(conn, "Savings")
        account = add_account(conn, "Test one", ASSET, "Savings")
    no_amount = {"account_class": "asset", "name": "Test two", "type_id": savings, "locale": "en-US"}
    assert client.post("/api/accounts", json=no_amount).status_code == 201
    assert client.post("/api/balances/update", json={"date": "2026-01-31", "amounts": {str(account): ""},
                                                       "versions": {}, "locale": "en-US"}).status_code == 200


def test_a_caller_that_names_no_locale_is_not_checked(client):
    account = setup_account(client, "de-DE")
    ok = client.post(f"/api/accounts/{account}/balances", json={"date": "2026-01-31", "amount": "1.234,56"})
    assert ok.status_code == 200 and amounts(client) == [123456]


def test_the_check_is_made_inside_the_write_transaction_not_only_before_it(conn, monkeypatch):
    admin = users.create_user(op(conn), "admin@example.com", "Test Admin", "synthetic-pass-123", is_admin=True)
    conn.execute("UPDATE users SET locale = 'de-DE' WHERE id = ?", (admin,))
    account = add_account(conn, "Test savings", ASSET, "Savings")
    # Suppose the early check passed because the preference had not yet changed: the one in the transaction must still refuse.
    monkeypatch.setattr(locales, "reading_locale", lambda c, user, tag: locales.get(c, tag))
    with pytest.raises(locales.LocaleChanged):
        balances.add_balance(op(conn, admin), account, "2026-01-31", "1,234.56", None, TODAY, locale_tag="en-US")
    assert conn.execute("SELECT COUNT(*) FROM live_balances").fetchone()[0] == 0


def test_the_command_line_never_names_a_locale_and_reads_us_english(conn):
    account = add_account(conn, "Test savings", ASSET, "Savings")
    assert balances.add_balance(op(conn), account, "2026-01-31", "1,234.56", None, TODAY) == "added"
    with pytest.raises(ValidationError):
        balances.add_balance(op(conn), account, "2026-02-01", "1.234,56", None, TODAY)
