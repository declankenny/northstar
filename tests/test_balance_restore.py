"""Restoring an earlier value of a balance: the amount alone is put back, as a new change by the person restoring it, and nothing in the
history is removed. Synthetic data only."""

import json

import pytest

from conftest import add_account, add_balance, with_db
from test_balance_history import ASSET, LIST, add, balance, edit

DAY = "2026-01-31"


@pytest.fixture
def account(client):
    with with_db(client) as conn:
        account_id = add_account(conn, "Test savings", ASSET, "Savings")
        conn.commit()
    return account_id


def rows(client, account_id, day=DAY):
    row = balance(client, account_id, day)
    response = client.post(LIST, json={"params": {"balance": row["id"]}})
    assert response.status_code == 200, response.text
    return response.json()["rows"]


def history_id(client, account_id, amount, day=DAY):
    """The id of the row of a balance's history that set `amount` (in cents): a person picks the row, the page sends its id."""
    [row] = [r for r in rows(client, account_id, day) if r["amount_cents"]["value"] == amount and r["restorable"] == 1]
    return row["_id"]


def restore(client, account_id, amount, day=DAY, client_to_use=None):
    row = balance(client, account_id, day)
    return (client_to_use or client).post(f"/api/balances/{row['id']}/restore", json={"history_id": history_id(client, account_id, amount, day), "version": row["version"]})


def now(client, account_id, day=DAY):
    with with_db(client) as conn:
        return tuple(conn.execute("SELECT amount_cents, note, source, as_of_date FROM balances WHERE account_id = ? AND as_of_date = ?", (account_id, day)).fetchone())


@pytest.fixture
def edited(client, account):
    """A balance entered at 1000.00, changed to 1100.00 and then to 1250.00, with a note that stays through it."""
    add(client, account, DAY, "1000.00", "Includes the refund")
    edit(client, account, DAY, "1100.00", "Includes the refund")
    edit(client, account, DAY, "1250.00", "Includes the refund")
    return client, account


# -- what it does --

def test_it_puts_the_amount_back_and_leaves_the_note_the_date_and_the_source(edited):
    client, account = edited
    response = restore(client, account, 110_000)
    assert response.status_code == 200, response.text
    assert now(client, account) == (110_000, "Includes the refund", "manual", DAY)


def test_it_is_a_new_row_by_the_person_restoring_and_removes_nothing(edited):
    client, account = edited
    before = [r["amount_cents"]["value"] for r in rows(client, account)]
    assert restore(client, account, 110_000).status_code == 200
    after = rows(client, account)
    assert [r["amount_cents"]["value"] for r in after] == [110_000] + before
    assert (after[0]["is_current"], after[0]["by_name"]) == (1, "Test User")
    assert after[0]["how"] == f"Restored · value of {after[2]['changed_at'][:10]}"      # the date of the row it restored
    assert [r["is_current"] for r in after[1:]] == [0, 0, 0]


def test_the_row_it_replaced_can_be_restored_in_turn(edited):
    client, account = edited
    assert restore(client, account, 110_000).status_code == 200
    assert restore(client, account, 125_000).status_code == 200
    assert now(client, account)[0] == 125_000


def test_it_can_restore_the_value_a_balance_from_before_the_log_started_with(client, account):
    with with_db(client) as conn:
        add_balance(conn, account, DAY, 100_000)
        conn.commit()
    edit(client, account, DAY, "1100.00")
    assert restore(client, account, 100_000).status_code == 200
    assert now(client, account)[0] == 100_000


def test_the_log_says_it_was_a_restore_and_changed_the_amount_only(edited):
    client, account = edited
    restore(client, account, 110_000)
    with with_db(client) as conn:
        header = conn.execute("SELECT id, kind, detail FROM sys_operations WHERE kind = 'restore'").fetchone()
        change = conn.execute("SELECT change, old_json, new_json FROM sys_record_changes WHERE operation_id = ?", (header["id"],)).fetchone()
    assert set(json.loads(header["detail"])) == {"history_id", "from"}
    assert (change["change"], json.loads(change["old_json"]), json.loads(change["new_json"])) == ("UPDATE", {"amount_cents": 125_000}, {"amount_cents": 110_000})


def test_other_dates_and_accounts_are_unchanged(edited):
    client, account = edited
    add(client, account, "2026-02-28", "2000.00")
    with with_db(client) as conn:
        other = add_account(conn, "Test other", ASSET, "Savings")
        add_balance(conn, other, DAY, 777)
        conn.commit()
    assert restore(client, account, 110_000).status_code == 200
    assert now(client, account, "2026-02-28")[0] == 200_000
    assert now(client, other)[0] == 777


# -- who may, and what may not be restored --

def test_a_household_member_who_is_not_an_admin_can_restore(edited, member_client):
    client, account = edited
    row = balance(client, account, DAY)
    response = member_client.post(f"/api/balances/{row['id']}/restore", json={"history_id": history_id(client, account, 110_000), "version": row["version"]})
    assert response.status_code == 200, response.text


def test_the_current_amount_and_a_change_of_the_note_alone_are_not_restorable(client, account):
    add(client, account, DAY, "1000.00")
    edit(client, account, DAY, "1200.00")
    edit(client, account, DAY, "1200.00", "A note")
    assert [r["restorable"] for r in rows(client, account)] == [0, 0, 1]      # the note-only change (current), the amount it repeats, the first
    note_only = rows(client, account)[0]
    row = balance(client, account, DAY)
    for target in (note_only, rows(client, account)[1]):
        response = client.post(f"/api/balances/{row['id']}/restore", json={"history_id": target["_id"], "version": row["version"]})
        assert response.status_code in (400, 422)
        assert "cannot be restored" in response.text
    assert now(client, account)[0] == 120_000


def test_a_row_that_is_not_in_this_balances_history_is_not_found(edited):
    client, account = edited
    add(client, account, "2026-02-28", "2000.00")
    edit(client, account, "2026-02-28", "2100.00")
    foreign = rows(client, account, "2026-02-28")[1]["_id"]
    row = balance(client, account, DAY)
    assert client.post(f"/api/balances/{row['id']}/restore", json={"history_id": foreign, "version": row["version"]}).status_code == 404
    assert client.post(f"/api/balances/{row['id']}/restore", json={"history_id": 987654, "version": row["version"]}).status_code == 404
    assert now(client, account)[0] == 125_000


def test_a_closed_account_is_refused_and_nothing_is_written(edited):
    client, account = edited
    chosen = history_id(client, account, 110_000)
    row = balance(client, account, DAY)
    with with_db(client) as conn:
        conn.execute("UPDATE accounts SET is_open = 0 WHERE id = ?", (account,))
        conn.commit()
        log = conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0]
    response = client.post(f"/api/balances/{row['id']}/restore", json={"history_id": chosen, "version": row["version"]})
    assert response.status_code in (400, 422) and "closed" in response.text
    assert now(client, account)[0] == 125_000
    with with_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0] == log


def test_a_balance_that_does_not_exist_is_not_found(client):
    assert client.post("/api/balances/99999/restore", json={"history_id": 1, "version": 0}).status_code == 404


# -- a change since the person opened the page --

def test_a_stale_restore_is_refused_naming_the_change_and_writes_nothing(edited):
    client, account = edited
    chosen = history_id(client, account, 110_000)
    row = balance(client, account, DAY)
    edit(client, account, DAY, "1300.00", "Includes the refund")           # someone else changes it after the page was opened
    log = None
    with with_db(client) as conn:
        log = conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0]
    response = client.post(f"/api/balances/{row['id']}/restore", json={"history_id": chosen, "version": row["version"]})
    assert response.status_code == 409
    conflict = response.json()["conflicts"][0]
    assert (conflict["kind"], conflict["amount_cents"], conflict["by"]) == ("changed", 130_000, "Test User")
    assert now(client, account)[0] == 130_000
    with with_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0] == log


def test_a_balance_deleted_since_is_a_conflict_too(edited):
    client, account = edited
    chosen = history_id(client, account, 110_000)
    row = balance(client, account, DAY)
    assert client.delete(f"/api/balances/{row['id']}", params={"version": row["version"]}).status_code == 200
    response = client.post(f"/api/balances/{row['id']}/restore", json={"history_id": chosen, "version": row["version"]})
    assert response.status_code == 409
    assert response.json()["conflicts"][0]["kind"] == "deleted"
