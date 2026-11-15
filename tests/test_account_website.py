"""An account's website (#266): the one rule that checks and cleans it, what is stored and logged, the edit API, the Accounts list column and
the migration. Synthetic data only."""

import json
import shutil

import pytest

from northstar import accounts, db
from northstar.errors import ValidationError

from conftest import add_account, op, type_id, use_dollars, with_db

LIST = "/api/lists/accounts"


# ---- the rule ----

@pytest.mark.parametrize("text", [None, "", "   ", "\t\n "])
def test_blank_clears_the_website(text):
    assert accounts.clean_website(text) == (None, [])


@pytest.mark.parametrize("text, stored", [
    ("https://www.bank.example/", "https://www.bank.example/"),
    ("  https://www.bank.example/login  ", "https://www.bank.example/login"),
    ("http://bank.example", "http://bank.example"),
    ("https://bank.example:8443/a/b", "https://bank.example:8443/a/b"),
    ("https://[::1]/x", "https://[::1]/x"),
    ("HTTPS://WWW.Bank.Example/Path", "https://www.bank.example/Path"),         # the scheme and host are lower case, the path is left as it is
    ("https://bank.example/?", "https://bank.example/"),                         # an empty query is nothing to say was removed
])
def test_a_clean_address_is_kept_whole(text, stored):
    assert accounts.clean_website(text) == (stored, [])


@pytest.mark.parametrize("text, stored, removed", [
    ("https://user:secret@bank.example/a", "https://bank.example/a", ["login"]),
    ("https://user@bank.example/a", "https://bank.example/a", ["login"]),
    ("https://bank.example/a?session=abc&x=1", "https://bank.example/a", ["query"]),
    ("https://bank.example/a#token=abc", "https://bank.example/a", ["fragment"]),
    ("https://user:secret@bank.example:8443/a?s=1#f", "https://bank.example:8443/a", ["login", "query", "fragment"]),
])
def test_sign_in_details_the_query_and_the_fragment_are_removed_and_said(text, stored, removed):
    assert accounts.clean_website(text) == (stored, removed)


@pytest.mark.parametrize("text", [
    "bank.example", "www.bank.example/login", "//bank.example", "ftp://bank.example", "javascript:alert(1)", "data:text/html,x",
    "https://", "http:///path", "https:/bank.example", "https:bank.example", "https://@/", "https://user@:80/",
    "https://bank.example:abc/", "https://bank .example/", "https://bank.example/a b", "https://bank.example/\\x", "https://bank.example/\x00",
    "https://bank.example/\nSet-Cookie: x=1",
])
def test_anything_else_is_refused_with_one_message(text):
    with pytest.raises(ValidationError) as refused:
        accounts.clean_website(text)
    assert str(refused.value) == accounts.WEBSITE_REFUSED


def test_the_length_limit_is_checked_first_on_the_trimmed_input():
    start = "https://bank.example/"
    exactly = start + "a" * (accounts.WEBSITE_MAX - len(start))
    assert accounts.clean_website(f"  {exactly}  ") == (exactly, [])
    with pytest.raises(ValidationError, match="at most 2048 characters"):
        accounts.clean_website(exactly + "a")
    with pytest.raises(ValidationError, match="at most 2048 characters"):
        accounts.clean_website("not even an address " * 200)         # too long is said before the address is looked at


# ---- what is stored and logged ----

def account_and_op(conn):
    admin = conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]
    return add_account(conn, "Visa Card", 2, "Credit card"), admin


def test_only_the_cleaned_address_is_stored_and_logged(conn):
    account_id, admin = account_and_op(conn)
    removed = accounts.update_account(op(conn, admin), account_id, "Visa Card", type_id(conn, "Credit card"), None,
                                      "https://user:s3cret@bank.example/pay?token=abc123#frag9")
    assert removed == ["login", "query", "fragment"]
    assert conn.execute("SELECT website FROM accounts WHERE id = ?", (account_id,)).fetchone()[0] == "https://bank.example/pay"
    everything = json.dumps([dict(r) for r in conn.execute("SELECT * FROM sys_record_changes")]
                            + [dict(r) for r in conn.execute("SELECT * FROM sys_operations")])
    for secret in ("s3cret", "user:", "abc123", "token", "frag9"):
        assert secret not in everything
    change = conn.execute("SELECT new_json FROM sys_record_changes WHERE tablename = 'accounts' AND record_id = ? ORDER BY id DESC",
                          (account_id,)).fetchone()[0]
    assert json.loads(change)["website"] == "https://bank.example/pay"


def test_a_website_that_is_refused_writes_nothing(conn):
    account_id, admin = account_and_op(conn)
    before = conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0]
    with pytest.raises(ValidationError):
        accounts.update_account(op(conn, admin), account_id, "Renamed", type_id(conn, "Credit card"), None, "bank.example")
    assert conn.execute("SELECT name, website FROM accounts WHERE id = ?", (account_id,)).fetchone()[:] == ("Visa Card", None)
    assert conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0] == before


def test_leaving_it_out_keeps_it_and_none_or_blank_clears_it(conn):
    account_id, admin = account_and_op(conn)
    kind = type_id(conn, "Credit card")
    accounts.update_account(op(conn, admin), account_id, "Visa Card", kind, None, "https://bank.example/")
    accounts.update_account(op(conn, admin), account_id, "Visa Card", kind, "a note")           # website not sent
    assert accounts.get_account(conn, account_id)["website"] == "https://bank.example/"
    accounts.update_account(op(conn, admin), account_id, "Visa Card", kind, "a note", "   ")
    assert accounts.get_account(conn, account_id)["website"] is None
    accounts.update_account(op(conn, admin), account_id, "Visa Card", kind, None, "https://bank.example/")
    accounts.update_account(op(conn, admin), account_id, "Visa Card", kind, None, None)
    assert accounts.get_account(conn, account_id)["website"] is None


def test_the_database_refuses_a_stored_address_that_is_too_long(conn):
    account_id, _ = account_and_op(conn)
    with pytest.raises(Exception, match="CHECK"):
        conn.execute("UPDATE accounts SET website = ? WHERE id = ?", ("h" * (accounts.WEBSITE_MAX + 1), account_id))


# ---- the API ----

def account_for(client, name="Visa Card", class_id=2, type_name="Credit card"):
    with with_db(client) as conn:
        account_id = add_account(conn, name, class_id, type_name)
        conn.commit()
    return account_id


@pytest.fixture
def visa(client):
    account_id = account_for(client)
    with with_db(client) as conn:
        kind = type_id(conn, "Credit card")
    return account_id, kind


def patch(client, visa, **fields):
    account_id, kind = visa
    return client.patch(f"/api/accounts/{account_id}", json={"name": "Visa Card", "type_id": kind, **fields})


def test_an_edit_answers_with_the_cleaned_website_and_what_was_removed(client, visa):
    body = patch(client, visa, website="https://u:p@bank.example/x?y=1").json()
    assert (body["website"], body["website_removed"]) == ("https://bank.example/x", ["login", "query"])
    page = client.get(f"/api/accounts/{visa[0]}").json()
    assert (page["website"], page["website_removed"]) == ("https://bank.example/x", [])        # only an edit's answer says what was removed


def test_an_edit_that_keeps_the_address_whole_removes_nothing(client, visa):
    body = patch(client, visa, website="https://bank.example/").json()
    assert (body["website"], body["website_removed"]) == ("https://bank.example/", [])


def test_leaving_it_out_keeps_it_and_null_or_blank_clears_it(client, visa):
    patch(client, visa, website="https://bank.example/")
    assert patch(client, visa, notes="hello").json()["website"] == "https://bank.example/"       # not sent: unchanged
    assert patch(client, visa, website=None).json()["website"] is None
    patch(client, visa, website="https://bank.example/")
    assert patch(client, visa, website="  ").json()["website"] is None


@pytest.mark.parametrize("website", ["bank.example", "ftp://bank.example", "https://", "x" * 2049, 5, ["https://bank.example/"]])
def test_a_refused_website_is_a_422_and_nothing_is_saved(client, visa, website):
    patch(client, visa, website="https://bank.example/")
    response = patch(client, visa, notes="should not be saved", website=website)
    assert response.status_code == 422
    page = client.get(f"/api/accounts/{visa[0]}").json()
    assert (page["website"], page["notes"]) == ("https://bank.example/", None)


def test_any_signed_in_user_who_can_edit_an_account_can_set_it(member_client):
    account_id = account_for(member_client)
    with with_db(member_client) as conn:
        kind = type_id(conn, "Credit card")
    response = member_client.patch(f"/api/accounts/{account_id}", json={"name": "Visa Card", "type_id": kind, "website": "https://bank.example/"})
    assert response.status_code == 200 and response.json()["website"] == "https://bank.example/"


def test_signed_out_it_is_refused(anon_client):
    assert anon_client.patch("/api/accounts/1", json={"name": "x", "type_id": 1, "website": "https://bank.example/"}).status_code == 401


def test_a_closed_account_keeps_its_website(client, visa):
    patch(client, visa, website="https://bank.example/")
    assert client.post(f"/api/accounts/{visa[0]}/close").status_code == 200
    assert client.get(f"/api/accounts/{visa[0]}").json()["website"] == "https://bank.example/"
    assert client.post(f"/api/accounts/{visa[0]}/reopen").json()["website"] == "https://bank.example/"


# ---- the Accounts list ----

def test_website_is_a_column_a_person_can_add_and_is_not_shown_by_default(client, visa):
    patch(client, visa, website="https://bank.example/x")
    page = client.post(LIST, json={}).json()
    assert "website" not in page["default_columns"] and "website" not in [c["key"] for c in page["columns"]]
    assert client.put(f"{LIST}/columns", json={"columns": ["name", "website"]}).status_code == 200
    page = client.post(LIST, json={}).json()
    assert [c["key"] for c in page["columns"]] == ["name", "website"] and [c["label"] for c in page["columns"]] == ["Account", "Website"]
    assert [(row["name"], row["website"]) for row in page["rows"]] == [("Visa Card", "https://bank.example/x")]


def test_the_website_column_sorts_and_searches(client):
    for name, site in (("A card", "https://b.example/"), ("B card", "https://a.example/"), ("C card", None)):
        account_id = account_for(client, name)
        if site:
            with with_db(client) as conn:
                conn.execute("UPDATE accounts SET website = ? WHERE id = ?", (site, account_id))
                conn.commit()
    client.put(f"{LIST}/columns", json={"columns": ["name", "website"]})
    ordered = client.post(LIST, json={"sort": {"field": "website", "direction": "asc"}}).json()["rows"]
    assert [row["website"] for row in ordered if row["website"]] == ["https://a.example/", "https://b.example/"]
    found = client.post(LIST, json={"search": "a.example"}).json()["rows"]
    assert [row["name"] for row in found] == ["B card"]


# ---- the migration ----

def test_upgrading_from_0032_adds_the_column_and_changes_no_data(tmp_path):
    folder = tmp_path / "before"
    folder.mkdir()
    for file in db.MIGRATIONS_DIR.glob("*.sql"):
        if not file.name.startswith("0033"):
            shutil.copy(file, folder)
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path, folder)
    conn = db.connect(path)
    use_dollars(conn)
    account_id = add_account(conn, "Test upgrade", 1, "Savings")
    conn.commit()
    accounts_before = [tuple(r) for r in conn.execute("SELECT id, name, type_id, notes, is_open FROM accounts ORDER BY id")]
    log_before = conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0]
    assert "website" not in [r[1] for r in conn.execute("PRAGMA table_info(accounts)")]
    conn.close()

    assert db.upgrade(path) == ["0033_account_website"]
    conn = db.connect(path)
    assert [tuple(r) for r in conn.execute("SELECT id, name, type_id, notes, is_open FROM accounts ORDER BY id")] == accounts_before
    assert conn.execute("SELECT website FROM accounts WHERE id = ?", (account_id,)).fetchone()[0] is None
    assert conn.execute("SELECT website FROM live_accounts WHERE id = ?", (account_id,)).fetchone()[0] is None      # the views carry it
    assert conn.execute("SELECT website FROM account_summaries WHERE id = ?", (account_id,)).fetchone()[0] is None
    assert tuple(conn.execute("SELECT is_logged FROM sys_audited_fields WHERE tablename = 'accounts' AND fieldname = 'website'").fetchone()) == (1,)
    assert conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0] == log_before
    conn.close()
