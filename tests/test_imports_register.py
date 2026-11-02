"""The register of past imports: what it lists, in what order, and who may see it. Synthetic data only."""

import base64

import pytest

from northstar import accounts, import_register, users
from conftest import add_account, op, with_db

ASSET = 1
CSV = "Date,Balance\n2026-01-31,1000.00\n2026-02-28,1100.50\n2026-03-31,1200.00\n"
MAPPING = {"date": 0, "balance": 1, "note": None, "currency": None}


def body(text=CSV, name="statement.csv", policy="skip"):
    return {"content": base64.b64encode(text.encode("utf-8")).decode("ascii"), "file_name": name,
            "mapping": MAPPING, "policy": policy, "date_format": None}


def run_import(client, account_id, **kwargs):
    review = client.post(f"/api/accounts/{account_id}/import/review", json=body(**kwargs))
    assert review.status_code == 200
    done = client.post(f"/api/accounts/{account_id}/import/commit", json={**body(**kwargs), "reviewed": review.json()["reviewed"]})
    assert done.status_code == 200
    return done


@pytest.fixture
def account(client):
    with with_db(client) as conn:
        account_id = add_account(conn, "Demo Savings", ASSET, "Savings")
        conn.commit()
    return account_id


def listed(client):
    response = client.get("/api/imports")
    assert response.status_code == 200
    return response.json()


def test_an_import_is_listed_with_who_when_where_which_file_and_the_counts(client, account):
    run_import(client, account, name="folder/savings 2026.csv")
    [entry] = listed(client)["imports"]
    assert entry["by"] == "Test User"
    assert entry["account_id"] == account and entry["account_name"] == "Demo Savings"
    assert entry["account_deleted"] is False and entry["account_open"] is True
    assert entry["file"] == "savings 2026.csv"                  # the base name only
    assert (entry["added"], entry["replaced"]) == (3, 0)
    assert len(entry["date"]) == 10 and entry["reverted_on"] is None


def test_a_replace_is_counted_as_replaced(client, account):
    run_import(client, account)
    run_import(client, account, text=CSV.replace("1100.50", "1111.00"), policy="replace", name="fix.csv")
    newest, older = listed(client)["imports"]
    assert (newest["file"], newest["added"], newest["replaced"]) == ("fix.csv", 0, 1)
    assert older["file"] == "statement.csv"


def test_newest_first(client, account):
    for number, name in enumerate(("one.csv", "two.csv", "three.csv")):
        run_import(client, account, text=CSV + f"2026-04-30,{number + 1}.00\n", name=name, policy="replace")
    assert [entry["file"] for entry in listed(client)["imports"]] == ["three.csv", "two.csv", "one.csv"]


def test_an_import_that_wrote_nothing_is_not_listed(client, account):
    run_import(client, account)
    review = client.post(f"/api/accounts/{account}/import/review", json=body())
    assert review.json()["counts"]["add"] == 0
    assert len(listed(client)["imports"]) == 1


def test_only_imports_are_listed(client, account):
    with with_db(client) as conn:
        conn.execute("UPDATE accounts SET notes = 'x' WHERE id = ?", (account,))
        conn.commit()
    client.post(f"/api/accounts/{account}/balances", json={"date": "2026-01-31", "amount": "5.00"})
    assert listed(client)["imports"] == []


def test_nothing_listed_yet_is_an_empty_list(client):
    assert listed(client) == {"imports": [], "more": False, "limit": import_register.LIMIT}


def test_it_lists_the_newest_25_and_says_there_are_more(client, account):
    run_import(client, account)
    with with_db(client) as conn:
        header = conn.execute("SELECT * FROM sys_operations WHERE kind = 'import'").fetchone()
        for _ in range(import_register.LIMIT):          # copies of the header, as if there had been more imports
            conn.execute("INSERT INTO sys_operations (kind, user_id, detail) VALUES ('import', ?, ?)", (header["user_id"], header["detail"]))
        conn.commit()
    result = listed(client)
    assert len(result["imports"]) == import_register.LIMIT and result["more"] is True


def test_a_deleted_account_is_marked_and_a_closed_one_is_not_open(client, account):
    run_import(client, account)
    with with_db(client) as conn:
        other = add_account(conn, "Demo Checking", ASSET, "Savings")
        conn.commit()
    run_import(client, other, name="other.csv", text="Date,Balance\n2026-01-31,0.00\n")
    with with_db(client) as conn:
        accounts.close_account(op(conn), other)
        accounts.delete_account(op(conn), account)
        conn.commit()
    gone, closed = None, None
    for entry in listed(client)["imports"]:
        gone, closed = (entry, closed) if entry["account_id"] == account else (gone, entry)
    assert gone["account_deleted"] is True
    assert closed["account_deleted"] is False and closed["account_open"] is False


def test_the_account_is_shown_by_its_current_name(client, account):
    run_import(client, account)
    with with_db(client) as conn:
        type_id = conn.execute("SELECT type_id FROM accounts WHERE id = ?", (account,)).fetchone()["type_id"]
    assert client.patch(f"/api/accounts/{account}", json={"name": "Renamed", "type_id": type_id}).status_code == 200
    assert listed(client)["imports"][0]["account_name"] == "Renamed"


def test_a_deleted_user_still_shows_as_who_imported(client, account):
    with with_db(client) as conn:
        other = users.create_user(op(conn), "other@example.com", "Other Person", "test-password-123", is_admin=True)
        conn.commit()
    run_import(client, account)
    with with_db(client) as conn:
        conn.execute("UPDATE sys_operations SET user_id = ? WHERE kind = 'import'", (other,))
        conn.execute("UPDATE users SET deleted = 1 WHERE id = ?", (other,))
        conn.commit()
    assert listed(client)["imports"][0]["by"] == "Other Person"


def test_an_undone_import_shows_when(client, account):
    run_import(client, account)
    with with_db(client) as conn:
        header = conn.execute("SELECT id, user_id FROM sys_operations WHERE kind = 'import'").fetchone()
        conn.execute("INSERT INTO sys_operations (kind, user_id, undoes_operation_id, created_at) VALUES ('undo', ?, ?, '2026-11-05T10:00:00Z')",
                     (header["user_id"], header["id"]))
        conn.commit()
    assert listed(client)["imports"][0]["reverted_on"] == "2026-11-05"


def test_a_header_without_an_account_still_lists(client, account):
    run_import(client, account)
    with with_db(client) as conn:
        conn.execute("UPDATE sys_operations SET detail = json_remove(detail, '$.account_id') WHERE kind = 'import'")
        conn.commit()
    entry = listed(client)["imports"][0]
    assert entry["account_id"] is None and entry["account_name"] is None and entry["account_deleted"] is False


def test_the_register_never_shows_balances_or_notes(client, account):
    run_import(client, account)
    assert "1100" not in client.get("/api/imports").text and "amount" not in client.get("/api/imports").text


def test_only_admins_may_see_it(member_client, anon_client):
    assert member_client.get("/api/imports").status_code == 403
    assert anon_client.get("/api/imports").status_code == 401
