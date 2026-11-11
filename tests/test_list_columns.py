"""The columns a person chooses for a list: saved beside their page size, applied when a request names none, and what happens when the
list stops offering one. Migration 0023 is tested on a copy of a database as 0022 left it. Synthetic data only."""

import json
import shutil
import sqlite3

import pytest

from conftest import add_account, add_balance, sign_in, with_db
from fastapi.testclient import TestClient
from northstar import db, list_prefs
from northstar.lists import loader
from northstar.lists.listdef import ListDef
from northstar.web.app import create_app

BALANCES = ListDef("balances_columns_test", "live_balance_values", ("as_of_date", "account", "amount_cents", "note"), ("as_of_date", "desc"))
CURRENCIES = ListDef("currencies_columns_test", "currencies", ("code", "name"), ("code", "asc"), admin_only=True)
SYSTEM = "(SELECT id FROM users WHERE is_system = 1)"


@pytest.fixture(autouse=True)
def lists():
    for definition in (BALANCES, CURRENCIES):
        loader.register(definition)
    yield
    for definition in (BALANCES, CURRENCIES):
        loader._DEFINITIONS.pop(definition.key)


@pytest.fixture
def household(client):
    with with_db(client) as conn:
        account = add_account(conn, "Test savings", 1, "Savings")
        for number in range(3):
            add_balance(conn, account, f"2026-04-{number + 1:02d}", 10_000 + number)
        conn.commit()


def ask(client, body=None, key="balances_columns_test"):
    return client.post(f"/api/lists/{key}", json=body or {})


def save(client, columns, key="balances_columns_test"):
    return client.put(f"/api/lists/{key}/columns", json={"columns": columns})


def keys(response):
    return [column["key"] for column in response.json()["columns"]]


def prefs(client):
    with with_db(client) as conn:
        return [dict(r) for r in conn.execute("SELECT user_id, list_key, page_size, columns FROM user_list_prefs")]


# -- choosing --

def test_a_list_shows_its_own_columns_until_the_person_chooses(client, household):
    body = ask(client).json()
    assert [c["key"] for c in body["columns"]] == ["as_of_date", "account", "amount_cents", "note"]
    assert (body["default_columns"], body["customised"], body["skipped_columns"]) == (["as_of_date", "account", "amount_cents", "note"], False, [])


def test_chosen_columns_are_shown_in_the_order_given_and_kept_for_the_next_visit(client, household):
    saved = save(client, ["amount_cents", "account.currency", "as_of_date"])
    assert saved.json() == {"columns": ["amount_cents", "account.currency", "as_of_date"], "customised": True}
    body = ask(client).json()
    assert [c["key"] for c in body["columns"]] == ["amount_cents", "account.currency", "as_of_date"]
    assert body["customised"] is True and body["default_columns"] == ["as_of_date", "account", "amount_cents", "note"]
    assert set(body["rows"][0]) >= {"amount_cents", "account.currency", "as_of_date"}


def test_a_request_that_names_columns_wins_and_does_not_change_the_choice(client, household):
    save(client, ["note"])
    body = ask(client, {"columns": ["as_of_date", "amount_cents"]}).json()
    assert [c["key"] for c in body["columns"]] == ["as_of_date", "amount_cents"] and body["customised"] is False
    assert keys(ask(client)) == ["note"]


def test_forgetting_the_choice_brings_back_the_lists_own_columns(client, household):
    save(client, ["note"])
    assert save(client, None).json() == {"columns": ["as_of_date", "account", "amount_cents", "note"], "customised": False}
    assert ask(client).json()["customised"] is False
    assert save(client, None).status_code == 200                       # forgetting what was never chosen is not an error
    assert len(prefs(client)) == 1                                     # the row stays, and with it the page size if there is one


def test_the_columns_and_the_page_size_are_chosen_separately_and_neither_disturbs_the_other(client, household):
    save(client, ["note", "as_of_date"])
    assert prefs(client)[0]["page_size"] is None                       # no page size chosen: the list's own is still used
    assert ask(client).json()["page_size"] == 25
    client.put("/api/lists/balances_columns_test/page-size", json={"page_size": 10})
    assert (ask(client).json()["page_size"], keys(ask(client))) == (10, ["note", "as_of_date"])
    save(client, None)
    assert ask(client).json()["page_size"] == 10
    assert len(prefs(client)) == 1


def test_one_persons_columns_are_not_anothers_and_not_another_lists(tmp_path):
    first = sign_in(TestClient(create_app(tmp_path / "web.db")), "first@example.com", "First")
    second = sign_in(TestClient(create_app(tmp_path / "web.db")), "second@example.com", "Second", is_admin=False)
    save(first, ["note"])
    assert keys(ask(first)) == ["note"]
    assert keys(ask(second)) == ["as_of_date", "account", "amount_cents", "note"]
    assert save(first, ["code"], "currencies_columns_test").status_code == 200
    assert keys(ask(first)) == ["note"]


# -- what is refused --

@pytest.mark.parametrize("columns", [[], ["no_such_column"], ["note", "note"], ["account.no_such"], [""], ["x" * 300], ["note"] * 61])
def test_columns_the_list_does_not_offer_are_refused_and_nothing_is_saved(client, household, columns):
    assert save(client, columns).status_code == 422
    assert prefs(client) == []


@pytest.mark.parametrize("columns", [[1], [None], "note", {"note": 1}, [["note"]]])
def test_columns_that_are_not_a_list_of_keys_are_refused(client, household, columns):
    assert save(client, columns).status_code == 422
    assert prefs(client) == []


def test_a_missing_columns_field_is_refused_and_null_is_the_only_way_to_forget(client, household):
    assert client.put("/api/lists/balances_columns_test/columns", json={}).status_code == 422


def test_an_unknown_list_and_a_list_only_for_admins_are_not_for_saving_columns(tmp_path, client):
    assert save(client, ["note"], "no_such_list").status_code == 404
    member = sign_in(TestClient(create_app(tmp_path / "web.db")), "member@example.com", "Member", is_admin=False)
    assert save(member, ["code"], "currencies_columns_test").status_code == 403
    assert prefs(client) == []


def test_it_is_for_people_who_are_signed_in(anon_client):
    assert anon_client.put("/api/lists/balances_columns_test/columns", json={"columns": ["note"]}).status_code == 401


# -- a column the list stops offering --

def test_a_saved_column_the_list_no_longer_offers_is_dropped_and_said(client, household):
    save(client, ["note", "amount_cents"])
    with with_db(client) as conn:                                      # as if the list had since changed
        conn.execute("UPDATE user_list_prefs SET columns = ?", (json.dumps(["note", "gone", "amount_cents", "account.also_gone"]),))
        conn.commit()
    body = ask(client).json()
    assert [c["key"] for c in body["columns"]] == ["note", "amount_cents"] and body["customised"] is True
    assert [s["field"] for s in body["skipped_columns"]] == ["gone", "account.also_gone"]
    assert all(s["reason"] for s in body["skipped_columns"])


def test_when_every_saved_column_is_gone_the_lists_own_apply_and_the_loss_is_said(client, household):
    save(client, ["note"])
    with with_db(client) as conn:
        conn.execute("UPDATE user_list_prefs SET columns = ?", (json.dumps(["gone"]),))
        conn.commit()
    body = ask(client).json()
    assert [c["key"] for c in body["columns"]] == ["as_of_date", "account", "amount_cents", "note"]
    assert (body["customised"], [s["field"] for s in body["skipped_columns"]]) == (False, ["gone"])


# -- logging --

def test_the_first_choice_makes_one_logged_row_and_changing_it_logs_nothing_more(client, household):
    def operations():
        with with_db(client) as conn:
            return conn.execute("SELECT COUNT(*) FROM sys_operations").fetchone()[0]
    start = operations()
    save(client, ["note"])
    created = operations()
    assert created == start + 1
    save(client, ["amount_cents", "note"])
    save(client, None)
    assert operations() == created                                     # the columns are not a logged field, like the page size


def test_the_module_forgets_nothing_it_never_had(conn):
    assert list_prefs.saved_columns(conn, 1, "anything") is None


# -- migration 0023 --

@pytest.fixture
def before(tmp_path):
    """A database as migration 0022 left it, with a person's page size saved for a list."""
    folder = tmp_path / "before"
    folder.mkdir()
    for file in db.MIGRATIONS_DIR.glob("*.sql"):
        if not file.name.startswith(("0023", "0024", "0025", "0026", "0027")):
            shutil.copy(file, folder)
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path, folder)
    conn = db.connect(path)
    conn.execute(f"INSERT INTO user_list_prefs (user_id, list_key, page_size, created_by, updated_by) VALUES ({SYSTEM}, 'test_list', 50, {SYSTEM}, {SYSTEM})")
    conn.commit()
    conn.close()
    return path


def test_the_upgrade_keeps_every_saved_page_size_and_adds_columns_that_are_empty(before):
    assert db.upgrade(before) == ["0023_user_list_columns", "0024_account_summaries", "0025_accounts_list", "0026_currency_summaries", "0027_account_balances"]
    conn = db.connect(before)
    row = conn.execute("SELECT list_key, page_size, columns FROM user_list_prefs").fetchone()
    assert tuple(row) == ("test_list", 50, None)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("SELECT is_logged FROM sys_audited_fields WHERE tablename = 'user_list_prefs' AND fieldname = 'columns'").fetchone()[0] == 0
    assert conn.execute("PRAGMA index_list(user_list_prefs)").fetchall()           # the unique (user, list) is still there
    conn.close()


def test_after_the_upgrade_a_row_may_have_columns_and_no_page_size_and_the_database_refuses_the_rest(before):
    db.upgrade(before)
    conn = db.connect(before)
    insert = f"INSERT INTO user_list_prefs (user_id, list_key, page_size, columns, created_by, updated_by) VALUES ({SYSTEM}, ?, ?, ?, {SYSTEM}, {SYSTEM})"
    conn.execute(insert, ("another_list", None, '["a","b"]'))                             # valid
    for bad in ('{"a": 1}', "not json", '"text"', json.dumps(["x" * 8000])):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, ("bad_list", None, bad))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("test_list", 10, None))                                      # still one row for each person and list
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("page_list", 7, None))                                       # a page size is still one of the offered
    conn.close()
