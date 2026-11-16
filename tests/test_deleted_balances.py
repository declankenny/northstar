"""The admin Deleted balances list and restoring a balance (#271): what is listed and what is left out, a restore under the original id from the
change log, the refusals (a date that has a balance now, a closed or deleted account, a balance that is not deleted) that write nothing, an old-shaped
log entry, and who may do any of it. Synthetic data only."""

import json
from datetime import date

from northstar import accounts, balances, retention, writer
from northstar.writer import Operation
from conftest import add_account, op, sign_in, use_dollars, with_db

ASSET = 1
URL = "/api/deleted-balances"


def user_id(conn):
    return conn.execute("SELECT id FROM users WHERE email = 'test@example.com'").fetchone()[0]


def make(client, name="Savings pot", days=("2026-01-31", "2026-02-28"), note=None):
    with with_db(client) as conn:
        account_id = add_account(conn, name, ASSET, "Savings")
        for i, day in enumerate(days):
            balances.record_balance(op(conn), account_id, date.fromisoformat(day), 100_000 + i, note)
        conn.commit()
    return account_id


def bid(client, account_id, day):
    with with_db(client) as conn:
        return conn.execute("SELECT id FROM balances WHERE account_id = ? AND as_of_date = ?", (account_id, day)).fetchone()[0]


def delete(client, balance_id, kind="ui_edit"):
    with with_db(client) as conn:
        operation = Operation(conn, user_id(conn), kind)
        if kind == "undo":
            writer.delete(operation, "balances", balance_id)
        else:
            balances.delete_balance(operation, balance_id)
        conn.commit()


def listed(client):
    response = client.get(URL)
    assert response.status_code == 200
    return response.json()


def entry_of(client, balance_id):
    """The log entry of the balance's latest deletion, as the list gives it to a page (0 when it has none)."""
    with with_db(client) as conn:
        row = conn.execute("SELECT MAX(id) FROM sys_record_changes WHERE tablename = 'balances' AND record_id = ? AND change = 'DELETE'",
                           (balance_id,)).fetchone()
    return row[0] or 0


def restore(client, balance_id, entry_id=None):
    return client.post(f"{URL}/{balance_id}/restore", json={"entry_id": entry_of(client, balance_id) if entry_id is None else entry_id})


def live(client, balance_id):
    with with_db(client) as conn:
        return conn.execute("SELECT 1 FROM live_balances WHERE id = ?", (balance_id,)).fetchone() is not None


def row_count(client):
    with with_db(client) as conn:
        return conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0], conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0]


# -- the list --

def test_it_lists_what_was_deleted_with_who_and_when_newest_first(client):
    acct = make(client, note="Statement total")
    first, second = bid(client, acct, "2026-01-31"), bid(client, acct, "2026-02-28")
    delete(client, first)
    delete(client, second)
    data = listed(client)
    assert [b["id"] for b in data["balances"]] == [second, first]
    entry = data["balances"][1]
    assert entry["account_name"] == "Savings pot" and entry["as_of_date"] == "2026-01-31" and entry["amount_cents"] == 100_000
    assert entry["note"] == "Statement total" and entry["deleted_by"] == "Test User" and entry["currency"]["code"] == "USD"
    assert entry["account_open"] is True and data["cleanup_on"] is True and data["retention_days"] == 90


def test_the_permanent_deletion_date_follows_the_same_rule_as_deleted_accounts(client):
    acct = make(client, days=("2026-01-31",))
    delete(client, bid(client, acct, "2026-01-31"))
    with with_db(client) as conn:
        conn.execute("UPDATE sys_operations SET created_at = '2026-08-17T12:00:00Z' WHERE kind = 'ui_edit' AND id = (SELECT MAX(id) FROM sys_operations)")
        conn.commit()
    assert listed(client)["balances"][0]["purge_on"] == "2026-11-16"
    with with_db(client) as conn:
        conn.execute("UPDATE system_properties SET value = NULL WHERE name = 'data.deleted.cleanup_time'")
        conn.commit()
    data = listed(client)
    assert data["cleanup_on"] is False and data["balances"][0]["purge_on"] is None


def test_a_live_balance_is_not_listed_and_nothing_deleted_gives_an_empty_list(client):
    make(client)
    assert listed(client)["balances"] == []


def test_a_balance_removed_by_an_undo_is_not_listed(client):
    acct = make(client)
    delete(client, bid(client, acct, "2026-01-31"), kind="undo")
    assert listed(client)["balances"] == []


def test_the_balances_of_a_deleted_account_are_not_listed_until_it_is_restored(client):
    acct = make(client)
    deleted_alone = bid(client, acct, "2026-01-31")
    delete(client, deleted_alone)
    with with_db(client) as conn:
        accounts.delete_account(op(conn, user_id(conn)), acct)
        conn.commit()
    assert listed(client)["balances"] == []                     # hidden with its account
    assert client.post(f"/api/deleted-accounts/{acct}/restore", json={}).status_code == 200
    assert [b["id"] for b in listed(client)["balances"]] == [deleted_alone]      # and only the one deleted on its own


def test_a_balance_that_was_added_again_on_its_date_is_still_listed_as_deleted(client):
    acct = make(client, days=("2026-01-31",))
    old = bid(client, acct, "2026-01-31")
    delete(client, old)
    with with_db(client) as conn:
        balances.record_balance(op(conn), acct, date(2026, 1, 31), 5)
        conn.commit()
    assert [b["id"] for b in listed(client)["balances"]] == [old]


def test_a_purged_balance_is_gone_from_the_list_and_cannot_be_restored(client):
    acct = make(client, days=("2026-01-31",))
    gone = bid(client, acct, "2026-01-31")
    delete(client, gone)
    with with_db(client) as conn:
        retention.purge_balance(conn, gone, "9999-12-31T00:00:00Z")
        conn.commit()
    assert listed(client)["balances"] == [] and restore(client, gone).status_code == 404


# -- restoring --

def test_restoring_puts_the_balance_back_under_its_own_id_with_its_amount_and_note(client):
    acct = make(client, note="Statement total")
    original = bid(client, acct, "2026-01-31")
    delete(client, original)
    response = restore(client, original)
    assert response.status_code == 200 and response.json() == {"id": original, "account_id": acct, "as_of_date": "2026-01-31"}
    with with_db(client) as conn:
        row = conn.execute("SELECT amount_cents, note, source FROM live_balances WHERE id = ?", (original,)).fetchone()
        assert tuple(row) == (100_000, "Statement total", "manual")
        assert [r[0] for r in conn.execute("SELECT change FROM sys_record_changes WHERE tablename = 'balances' AND record_id = ? ORDER BY id", (original,))] \
            == ["INSERT", "DELETE", "INSERT"]
    assert listed(client)["balances"] == []


def test_the_restore_is_one_operation_of_its_kind_by_the_admin_and_is_in_the_balances_history(client):
    acct = make(client, days=("2026-01-31",))
    original = bid(client, acct, "2026-01-31")
    delete(client, original)
    restore(client, original)
    with with_db(client) as conn:
        kind, detail, user = conn.execute("SELECT kind, detail, user_id FROM sys_operations ORDER BY id DESC LIMIT 1").fetchone()
        assert kind == "restore" and json.loads(detail) == {"table": "balances", "record_id": original} and user == user_id(conn)
    history = client.post("/api/lists/balance_history", json={"params": {"balance": original}})
    assert history.status_code == 200, history.text
    assert [(r["is_current"], r["how"]) for r in history.json()["rows"]] == [(1, "Restored"), (0, "Manual edit")]


def test_a_restored_balance_that_is_deleted_again_is_listed_again(client):
    acct = make(client, days=("2026-01-31",))
    original = bid(client, acct, "2026-01-31")
    delete(client, original)
    restore(client, original)
    delete(client, original)
    assert [b["id"] for b in listed(client)["balances"]] == [original]
    assert restore(client, original).status_code == 200


def test_an_entry_from_before_a_column_existed_is_restored_with_the_columns_default(client):
    acct = make(client, days=("2026-01-31",))
    original = bid(client, acct, "2026-01-31")
    delete(client, original)
    with with_db(client) as conn:       # an older-shaped log entry: no source in it
        conn.execute("UPDATE sys_record_changes SET old_json = json_remove(old_json, '$.source') WHERE tablename = 'balances' AND change = 'DELETE'")
        conn.commit()
    assert restore(client, original).status_code == 200
    with with_db(client) as conn:
        assert conn.execute("SELECT source FROM live_balances WHERE id = ?", (original,)).fetchone()[0] == "manual"


# -- refusals write nothing --

def test_a_date_that_has_a_balance_now_is_refused_with_that_balance_named_and_nothing_is_written(client):
    acct = make(client, days=("2026-01-31",))
    original = bid(client, acct, "2026-01-31")
    delete(client, original)
    with with_db(client) as conn:
        balances.record_balance(op(conn), acct, date(2026, 1, 31), 777)
        conn.commit()
    other = bid(client, acct, "2026-01-31")
    before = row_count(client)
    response = restore(client, original)
    assert response.status_code == 409
    body = response.json()
    assert body["reason"] == "date_taken" and body["existing"] == {"balance_id": other, "amount_cents": 777}
    assert "already has a balance" in body["detail"] and row_count(client) == before and not live(client, original)
    assert [b["id"] for b in listed(client)["balances"]] == [original]          # still there to inspect


def test_a_closed_account_refuses_the_restore(client):
    acct = make(client, days=("2026-01-31",))
    original = bid(client, acct, "2026-01-31")
    delete(client, original)
    with with_db(client) as conn:
        conn.execute("UPDATE accounts SET is_open = 0 WHERE id = ?", (acct,))
        conn.commit()
    before = row_count(client)
    response = restore(client, original)
    assert response.status_code == 422 and "closed" in response.json()["detail"]
    assert row_count(client) == before and listed(client)["balances"][0]["account_open"] is False


def test_a_balance_whose_account_is_deleted_cannot_be_restored(client):
    acct = make(client, days=("2026-01-31",))
    original = bid(client, acct, "2026-01-31")
    delete(client, original)
    with with_db(client) as conn:
        accounts.delete_account(op(conn), acct)
        conn.commit()
    assert restore(client, original).status_code == 404


def test_a_balance_that_is_not_deleted_cannot_be_restored(client):
    acct = make(client, days=("2026-01-31",))
    assert restore(client, bid(client, acct, "2026-01-31")).status_code == 404
    assert restore(client, 9999).status_code == 404


def test_a_balance_removed_by_an_undo_cannot_be_restored_from_here(client):
    acct = make(client, days=("2026-01-31",))
    gone = bid(client, acct, "2026-01-31")
    delete(client, gone, kind="undo")
    assert restore(client, gone).status_code == 404


def test_restoring_twice_refuses_the_second(client):
    acct = make(client, days=("2026-01-31",))
    original = bid(client, acct, "2026-01-31")
    delete(client, original)
    assert restore(client, original).status_code == 200
    assert restore(client, original).status_code == 404


# -- who may --

def test_only_an_admin_can_list_or_restore_including_direct_requests(member_client, anon_client):
    assert member_client.get(URL).status_code == 403
    assert member_client.post(f"{URL}/1/restore", json={"entry_id": 1}).status_code == 403
    assert anon_client.get(URL).status_code == 401
    assert anon_client.post(f"{URL}/1/restore", json={"entry_id": 1}).status_code == 401


# -- backup and restore, and upgrading --

def test_a_deleted_balance_survives_a_backup_and_a_restore_and_can_be_restored_after_it(client, tmp_path):
    from fastapi.testclient import TestClient
    from northstar import backup, db, sessions
    from northstar.web.app import create_app

    acct = make(client, days=("2026-01-31",))
    original = bid(client, acct, "2026-01-31")
    delete(client, original)
    backup.create_backup(client.app.state.db_path, tmp_path / "copy.db")
    backup.restore_backup(tmp_path / "copy.db", tmp_path / "restored.db")
    again = TestClient(create_app(tmp_path / "restored.db"))
    with db.connect(tmp_path / "restored.db") as connection:             # the same people are in it: only a new session is needed
        again.cookies.set("northstar_session", sessions.create_session(connection, user_id(connection)))
    assert [b["id"] for b in again.get(URL).json()["balances"]] == [original]
    assert again.post(f"{URL}/{original}/restore", json={"entry_id": again.get(URL).json()["balances"][0]["entry_id"]}).status_code == 200
    assert again.get(URL).json()["balances"] == []


def test_a_balance_deleted_under_the_preceding_release_is_listed_and_restored_after_the_upgrade(tmp_path, monkeypatch):
    """Migrations 0029 onward are this release's. A database as the last migration of 0.6.0 left it, with a balance deleted (logged by the writer of
    that schema), is upgraded and the balance is then listed and restored."""
    import shutil
    from fastapi.testclient import TestClient
    from northstar import db
    from northstar.web.app import create_app

    folder = tmp_path / "before"
    folder.mkdir()
    for file in db.MIGRATIONS_DIR.glob("*.sql"):
        if int(file.name[:4]) < 29:
            shutil.copy(file, folder)
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path, folder)
    conn = db.connect(path)
    use_dollars(conn)
    account_id = add_account(conn, "Test upgrade", ASSET, "Savings")
    from northstar import accounts
    with monkeypatch.context() as before:           # the previous release's account query: its table has no `website` yet
        before.setattr(accounts, "_SELECT", accounts._SELECT.replace("a.website, a.due_day, ", ""))
        for day, cents in (("2026-01-31", 100_000), ("2026-02-28", 120_000)):
            balances.record_balance(op(conn), account_id, date.fromisoformat(day), cents, "Statement")
        gone = conn.execute("SELECT id FROM balances WHERE as_of_date = '2026-01-31'").fetchone()[0]
        balances.delete_balance(op(conn), gone)
    conn.commit()
    conn.close()

    assert db.upgrade(path)
    client = sign_in(TestClient(create_app(path)))
    [entry] = client.get(URL).json()["balances"]
    assert (entry["id"], entry["as_of_date"], entry["amount_cents"], entry["note"]) == (gone, "2026-01-31", 100_000, "Statement")
    assert client.post(f"{URL}/{gone}/restore", json={"entry_id": client.get(URL).json()["balances"][0]["entry_id"]}).status_code == 200
    with with_db(client) as conn:
        assert conn.execute("SELECT amount_cents, note FROM live_balances WHERE id = ?", (gone,)).fetchone()[0] == 100_000


# -- the confirmation is of one deletion (review of #277) --

def test_a_confirmation_that_is_stale_restores_nothing_when_the_balance_was_restored_changed_and_deleted_again(client):
    acct = make(client, days=("2026-01-31",))
    original = bid(client, acct, "2026-01-31")
    delete(client, original)
    shown = listed(client)["balances"][0]
    assert shown["amount_cents"] == 100_000 and shown["note"] is None
    with with_db(client) as conn:                  # someone else, meanwhile: restores, edits and deletes it again
        restored = Operation(conn, user_id(conn), "restore")
        writer.insert(restored, "balances", {"id": original, "account_id": acct, "as_of_date": "2026-01-31", "amount_cents": 100_000, "note": None})
        writer.update(Operation(conn, user_id(conn), "ui_edit"), "balances", original, {"amount_cents": 35_000, "note": "Later correction"})
        balances.delete_balance(Operation(conn, user_id(conn), "ui_edit"), original)
        conn.commit()
    before = row_count(client)
    response = restore(client, original, entry_id=shown["entry_id"])
    assert response.status_code == 409 and "changed by someone else" in response.json()["detail"]
    assert row_count(client) == before and not live(client, original)
    now = listed(client)["balances"][0]
    assert now["entry_id"] != shown["entry_id"] and (now["amount_cents"], now["note"]) == (35_000, "Later correction")
    assert restore(client, original, entry_id=now["entry_id"]).status_code == 200            # reviewed again, it restores


def test_the_entry_sent_must_be_one_of_that_balance(client):
    acct = make(client)
    first, second = bid(client, acct, "2026-01-31"), bid(client, acct, "2026-02-28")
    delete(client, first)
    delete(client, second)
    assert restore(client, first, entry_id=entry_of(client, second)).status_code == 409
    assert restore(client, first, entry_id=0).status_code == 409


def test_a_request_without_the_entry_is_refused(client):
    acct = make(client, days=("2026-01-31",))
    original = bid(client, acct, "2026-01-31")
    delete(client, original)
    assert client.post(f"{URL}/{original}/restore", json={}).status_code == 422


# -- a balance from before the log keeps its baseline (review of #277) --

def test_a_restored_balance_from_before_the_log_keeps_its_original_baseline_row_and_its_author(client):
    acct = make(client, days=())
    with with_db(client) as conn:
        balances.record_balance(op(conn), acct, date(2026, 1, 31), 10_000)         # written by the system user
        original = conn.execute("SELECT id FROM balances").fetchone()[0]
        conn.execute("DELETE FROM sys_record_changes WHERE tablename = 'balances' AND record_id = ?", (original,))      # the log never saw it created
        conn.execute("UPDATE balances SET created_at = '2026-01-31T09:00:00Z' WHERE id = ?", (original,))
        writer.update(Operation(conn, user_id(conn), "ui_edit"), "balances", original, {"amount_cents": 20_000})
        balances.delete_balance(Operation(conn, user_id(conn), "ui_edit"), original)
        conn.commit()
    assert restore(client, original).status_code == 200
    rows = client.post("/api/lists/balance_history", json={"params": {"balance": original}}).json()["rows"]
    assert [(r["amount_cents"]["value"], r["how"], r["is_current"]) for r in rows] == [(20_000, "Restored", 1), (20_000, "Manual edit", 0), (10_000, "Entered", 0)]
    entered = rows[-1]
    assert entered["changed_at"] == "2026-01-31T09:00:00Z" and entered["by_name"] != "Test User"       # as it was created, not as restored
    with with_db(client) as conn:       # and it is not in the way of a second restore after a second deletion
        balances.delete_balance(Operation(conn, user_id(conn), "ui_edit"), original)
        conn.commit()
    assert restore(client, original).status_code == 200
    rows = client.post("/api/lists/balance_history", json={"params": {"balance": original}}).json()["rows"]
    assert [r["how"] for r in rows].count("Entered") == 1 and rows[-1]["by_name"] != "Test User"


def test_a_balance_the_log_saw_created_has_no_baseline_row_after_a_restore(client):
    acct = make(client, days=("2026-01-31",))
    original = bid(client, acct, "2026-01-31")
    delete(client, original)
    restore(client, original)
    rows = client.post("/api/lists/balance_history", json={"params": {"balance": original}}).json()["rows"]
    assert [r["how"] for r in rows] == ["Restored", "Manual edit"]
