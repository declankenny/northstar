"""Undoing an import: all or nothing, admin only, and never over a later change. Synthetic data only."""

import json

import pytest

from northstar import accounts, import_register
from conftest import add_account, op, with_db
from test_imports_register import CSV, run_import

ASSET = 1


@pytest.fixture
def account(client):
    with with_db(client) as conn:
        account_id = add_account(conn, "Demo Savings", ASSET, "Savings")
        conn.commit()
    return account_id


def import_ids(client):
    with with_db(client) as conn:
        return [row[0] for row in conn.execute("SELECT id FROM sys_operations WHERE kind = 'import' ORDER BY id")]


def balances_of(client, account_id):
    with with_db(client) as conn:
        return [tuple(row) for row in conn.execute(
            "SELECT as_of_date, amount_cents, note, source FROM live_balances WHERE account_id = ? ORDER BY as_of_date", (account_id,))]


def balance_id(client, account_id, day):
    with with_db(client) as conn:
        return conn.execute("SELECT id FROM balances WHERE account_id = ? AND as_of_date = ?", (account_id, day)).fetchone()[0]


def everything(client):
    """All the data an undo could touch, to show a refused one touched nothing."""
    with with_db(client) as conn:
        return ([tuple(row) for row in conn.execute("SELECT * FROM balances ORDER BY id")],
                conn.execute("SELECT COUNT(*) FROM sys_operations").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0])


def plan(client, import_id):
    return client.get(f"/api/imports/{import_id}/undo")


def undo(client, import_id):
    return client.post(f"/api/imports/{import_id}/undo")


def version_of(client, bid):
    with with_db(client) as conn:
        return conn.execute("SELECT version FROM balances WHERE id = ?", (bid,)).fetchone()[0]


def edit(client, account_id, day, amount):
    bid = balance_id(client, account_id, day)
    response = client.patch(f"/api/balances/{bid}", json={"date": day, "amount": amount, "version": version_of(client, bid)})
    assert response.status_code == 200


def remove(client, account_id, day):
    bid = balance_id(client, account_id, day)
    return client.delete(f"/api/balances/{bid}", params={"version": version_of(client, bid)})


def refused(client, import_id, kind):
    before = everything(client)
    response = undo(client, import_id)
    assert response.status_code == 409
    assert response.json()["reason"] == kind
    assert everything(client) == before          # nothing was written
    return response.json()


# -- what it does --

def test_undoing_an_import_that_added_balances_deletes_them(client, account):
    run_import(client, account)
    [import_id] = import_ids(client)
    response = undo(client, import_id)
    assert response.status_code == 200
    assert (response.json()["deleted"], response.json()["restored"]) == (3, 0)
    assert balances_of(client, account) == []


def test_undoing_an_import_that_replaced_balances_puts_back_the_old_amount_note_and_source(client, account):
    client.post(f"/api/accounts/{account}/balances", json={"date": "2026-02-28", "amount": "50.00", "note": "typed by hand"})
    run_import(client, account, text="Date,Balance\n2026-02-28,99.00\n", policy="replace")
    assert balances_of(client, account) == [("2026-02-28", 9900, "typed by hand", "csv")]
    [import_id] = import_ids(client)
    response = undo(client, import_id)
    assert (response.json()["deleted"], response.json()["restored"]) == (0, 1)
    assert balances_of(client, account) == [("2026-02-28", 5000, "typed by hand", "manual")]


def test_a_mix_of_added_and_replaced_is_undone_together(client, account):
    run_import(client, account)
    before = balances_of(client, account)
    run_import(client, account, text="Date,Balance\n2026-02-28,111.00\n2026-04-30,400.00\n", policy="replace", name="second.csv")
    first, second = import_ids(client)
    # the second import replaced a balance that the first one wrote, so the first can no longer be undone first
    undo_second = undo(client, second)
    assert (undo_second.json()["deleted"], undo_second.json()["restored"]) == (1, 1)
    assert balances_of(client, account) == before


def test_the_undo_is_one_logged_operation_pointing_at_the_import(client, account):
    run_import(client, account)
    [import_id] = import_ids(client)
    undo(client, import_id)
    with with_db(client) as conn:
        header = conn.execute("SELECT * FROM sys_operations WHERE kind = 'undo'").fetchone()
        changes = conn.execute("SELECT change, tablename FROM sys_record_changes WHERE operation_id = ?", (header["id"],)).fetchall()
    assert header["undoes_operation_id"] == import_id
    assert json.loads(header["detail"]) == {"undoes": import_id, "deleted": 3, "restored": 0}
    assert [tuple(row) for row in changes] == [("DELETE", "balances")] * 3


def test_a_restored_balance_carries_the_undo_as_its_version(client, account):
    client.post(f"/api/accounts/{account}/balances", json={"date": "2026-02-28", "amount": "50.00"})
    run_import(client, account, text="Date,Balance\n2026-02-28,99.00\n", policy="replace")
    [import_id] = import_ids(client)
    undo(client, import_id)
    with with_db(client) as conn:
        version = conn.execute("SELECT version FROM balances WHERE account_id = ?", (account,)).fetchone()[0]
        undo_id = conn.execute("SELECT id FROM sys_operations WHERE kind = 'undo'").fetchone()[0]
    assert version == undo_id


def test_the_register_then_says_when_it_was_reverted_and_the_file_can_be_imported_again(client, account):
    run_import(client, account)
    [import_id] = import_ids(client)
    undo(client, import_id)
    [entry] = client.get("/api/imports").json()["imports"]
    assert entry["reverted_on"] is not None and len(entry["reverted_on"]) == 10
    run_import(client, account)
    assert len(balances_of(client, account)) == 3


def test_the_undo_answers_with_the_register_as_it_now_is(client, account):
    run_import(client, account)
    [import_id] = import_ids(client)
    answer = undo(client, import_id).json()
    assert answer["after"]["imports"][0]["reverted_on"] is not None


# -- the plan, which writes nothing --

def test_the_plan_says_what_would_happen_and_writes_nothing(client, account):
    client.post(f"/api/accounts/{account}/balances", json={"date": "2026-02-28", "amount": "50.00"})
    run_import(client, account, policy="replace")
    [import_id] = import_ids(client)
    before = everything(client)
    response = plan(client, import_id)
    assert response.status_code == 200
    assert response.json() == {"import_id": import_id, "file": "statement.csv", "date": response.json()["date"], "by": "Test User",
                               "account_id": account, "account_name": "Demo Savings", "delete": 2, "restore": 1}
    assert everything(client) == before


# -- when it is refused, and that nothing is written --

def test_a_balance_edited_since_blocks_it(client, account):
    run_import(client, account)
    [import_id] = import_ids(client)
    edit(client, account, "2026-02-28", "1.00")
    answer = refused(client, import_id, "changed")
    assert answer["blocked"] == [{"date": "2026-02-28", "why": "Edited since the import"}] and answer["more"] == 0


def test_a_balance_deleted_since_blocks_it_and_the_date_is_still_named(client, account):
    run_import(client, account)
    [import_id] = import_ids(client)
    assert remove(client, account, "2026-03-31").status_code == 200
    answer = refused(client, import_id, "changed")
    assert answer["blocked"] == [{"date": "2026-03-31", "why": "Deleted since the import"}]


def test_a_replaced_balance_deleted_since_still_has_its_date_named(client, account):
    client.post(f"/api/accounts/{account}/balances", json={"date": "2026-02-28", "amount": "50.00"})
    run_import(client, account, text="Date,Balance\n2026-02-28,99.00\n", policy="replace")
    [import_id] = import_ids(client)
    assert remove(client, account, "2026-02-28").status_code == 200
    assert refused(client, import_id, "changed")["blocked"] == [{"date": "2026-02-28", "why": "Deleted since the import"}]


def test_a_balance_replaced_by_a_later_import_blocks_it_and_says_so(client, account):
    run_import(client, account)
    run_import(client, account, text="Date,Balance\n2026-02-28,111.00\n", policy="replace", name="later.csv")
    first, _ = import_ids(client)
    answer = refused(client, first, "changed")
    [entry] = answer["blocked"]
    assert entry["date"] == "2026-02-28" and entry["why"].startswith("Replaced by a later import (")


def test_a_closed_account_blocks_it_until_it_is_reopened(client, account):
    run_import(client, account, text="Date,Balance\n2026-01-31,0.00\n")
    [import_id] = import_ids(client)
    with with_db(client) as conn:
        accounts.close_account(op(conn), account)
        conn.commit()
    assert "is closed" in refused(client, import_id, "account_closed")["detail"]
    with with_db(client) as conn:
        accounts.reopen_account(op(conn), account)
        conn.commit()
    assert undo(client, import_id).status_code == 200


def test_a_deleted_account_blocks_it(client, account):
    run_import(client, account)
    [import_id] = import_ids(client)
    with with_db(client) as conn:
        accounts.delete_account(op(conn), account)
        conn.commit()
    assert "was deleted" in refused(client, import_id, "account_deleted")["detail"]


def test_only_ten_dates_are_named_and_the_rest_are_counted(client, account):
    text = "Date,Balance\n" + "".join(f"2026-01-{day:02d},{day}.00\n" for day in range(1, 13))
    run_import(client, account, text=text)
    [import_id] = import_ids(client)
    with with_db(client) as conn:
        conn.execute("UPDATE balances SET version = 0 WHERE account_id = ?", (account,))
        conn.commit()
    answer = refused(client, import_id, "changed")
    assert len(answer["blocked"]) == import_register.SHOWN and answer["more"] == 2
    assert [entry["date"] for entry in answer["blocked"]] == sorted(entry["date"] for entry in answer["blocked"])


def test_one_changed_balance_blocks_the_whole_undo_even_when_the_rest_are_untouched(client, account):
    run_import(client, account)
    [import_id] = import_ids(client)
    edit(client, account, "2026-01-31", "5.00")
    refused(client, import_id, "changed")
    assert len(balances_of(client, account)) == 3


def test_a_change_between_the_plan_and_the_undo_is_a_refusal_and_never_an_overwrite(client, account):
    run_import(client, account)
    [import_id] = import_ids(client)
    assert plan(client, import_id).status_code == 200
    edit(client, account, "2026-02-28", "7.00")
    refused(client, import_id, "changed")
    assert ("2026-02-28", 700, None, "csv") in balances_of(client, account)


# -- once only, and only imports --

def test_an_import_is_undone_once(client, account):
    run_import(client, account)
    [import_id] = import_ids(client)
    assert undo(client, import_id).status_code == 200
    answer = refused(client, import_id, "reverted")
    assert "already undone" in answer["detail"]
    assert plan(client, import_id).status_code == 409


def test_an_undo_cannot_be_undone_and_nothing_but_an_import_can_be_undone(client, account):
    run_import(client, account)
    client.post(f"/api/accounts/{account}/balances", json={"date": "2026-05-31", "amount": "5.00"})
    [import_id] = import_ids(client)
    undo(client, import_id)
    with with_db(client) as conn:
        others = [row[0] for row in conn.execute("SELECT id FROM sys_operations WHERE kind != 'import'")]
    assert others
    for operation_id in others:
        assert undo(client, operation_id).status_code == 404
        assert plan(client, operation_id).status_code == 404


def test_the_database_allows_one_undo_per_import_even_if_the_code_did_not(client, account):
    run_import(client, account)
    [import_id] = import_ids(client)
    undo(client, import_id)
    with with_db(client) as conn:
        user = conn.execute("SELECT user_id FROM sys_operations WHERE id = ?", (import_id,)).fetchone()[0]
        with pytest.raises(Exception, match="UNIQUE"):
            conn.execute("INSERT INTO sys_operations (kind, user_id, undoes_operation_id) VALUES ('undo', ?, ?)", (user, import_id))


def test_an_unknown_import_is_not_found(client):
    assert undo(client, 999).status_code == 404
    assert plan(client, 999).status_code == 404


# -- who may --

def test_only_admins_may_undo_or_see_the_plan(member_client, anon_client):
    assert member_client.get("/api/imports/1/undo").status_code == 403
    assert member_client.post("/api/imports/1/undo").status_code == 403
    assert anon_client.get("/api/imports/1/undo").status_code == 401
    assert anon_client.post("/api/imports/1/undo").status_code == 401


def test_a_second_admin_may_undo_an_import_the_first_made(client, account):
    run_import(client, account)
    [import_id] = import_ids(client)
    with with_db(client) as conn:
        from northstar import users
        other = users.create_user(op(conn), "second@example.com", "Second Admin", "test-password-123", is_admin=True)
        conn.commit()
    from conftest import sessions
    with with_db(client) as conn:
        client.cookies.set("northstar_session", sessions.create_session(conn, other))
    assert undo(client, import_id).status_code == 200
    with with_db(client) as conn:
        assert conn.execute("SELECT user_id FROM sys_operations WHERE kind = 'undo'").fetchone()[0] == other
