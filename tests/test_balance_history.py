"""A balance's history (a fixed list of the framework, `/api/lists/balance_history`): the changes the log recorded for one live balance,
newest first. Synthetic data only."""

import pytest

from conftest import add_account, add_balance, op, use_dollars, with_db
from northstar import accounts
from test_imports_register import run_import

LIST = "/api/lists/balance_history"
ASSET = 1


@pytest.fixture
def account(client):
    with with_db(client) as conn:
        account_id = add_account(conn, "Test savings", ASSET, "Savings")
        conn.commit()
    return account_id


def balance(client, account_id, day):
    with with_db(client) as conn:
        return conn.execute("SELECT id, version FROM balances WHERE account_id = ? AND as_of_date = ?", (account_id, day)).fetchone()


def add(client, account_id, day, amount, note=None):
    response = client.post(f"/api/accounts/{account_id}/balances", json={"date": day, "amount": amount, "note": note})
    assert response.status_code in (200, 201), response.text


def edit(client, account_id, day, amount, note=""):
    row = balance(client, account_id, day)
    response = client.patch(f"/api/balances/{row['id']}", json={"date": day, "amount": amount, "note": note, "version": row["version"]})
    assert response.status_code == 200, response.text


def history(client, account_id, day, **request):
    row = balance(client, account_id, day)
    response = client.post(LIST, json={"params": {"balance": row["id"]}, **request})
    assert response.status_code == 200, response.text
    return response.json()


def shown(rows):
    """What a person reads: the amount in cents, whether it is current, and how it was made."""
    return [(r["amount_cents"]["value"], r["is_current"], r["how"]) for r in rows]


# -- what a balance's history holds --

def test_a_balance_entered_by_hand_has_one_current_row_by_its_author(client, account):
    add(client, account, "2026-01-31", "1000.00")
    body = history(client, account, "2026-01-31")
    assert body["total"] == 1
    assert shown(body["rows"]) == [(100_000, 1, "Manual edit")]
    assert body["rows"][0]["by_name"] == "Test User"
    assert body["rows"][0]["amount_cents"] == {"value": 100_000, "scale": 2, "unit": "USD"}


def test_each_change_is_a_row_newest_first_and_only_the_latest_is_current(client, account):
    add(client, account, "2026-01-31", "1000.00")
    edit(client, account, "2026-01-31", "1100.00")
    edit(client, account, "2026-01-31", "1250.00")
    rows = history(client, account, "2026-01-31")["rows"]
    assert shown(rows) == [(125_000, 1, "Manual edit"), (110_000, 0, "Manual edit"), (100_000, 0, "Manual edit")]


def test_a_change_to_the_note_alone_keeps_the_amount_and_says_the_note_changed(client, account):
    add(client, account, "2026-01-31", "1000.00")
    edit(client, account, "2026-01-31", "1000.00", note="Includes the refund")
    rows = history(client, account, "2026-01-31")["rows"]
    assert shown(rows) == [(100_000, 1, "Manual edit · note changed"), (100_000, 0, "Manual edit")]


def test_an_amount_change_after_a_note_change_does_not_lose_the_amount_in_between(client, account):
    add(client, account, "2026-01-31", "1000.00")
    edit(client, account, "2026-01-31", "1000.00", note="First note")
    edit(client, account, "2026-01-31", "1300.00", note="First note")
    assert [r["amount_cents"]["value"] for r in history(client, account, "2026-01-31")["rows"]] == [130_000, 100_000, 100_000]


def test_an_import_names_its_file_and_a_replacement_is_a_row_of_the_balance_it_replaced(client, account):
    add(client, account, "2026-02-28", "50.00")
    run_import(client, account, text="Date,Balance\n2026-02-28,99.00\n", policy="replace", name="savings-2026.csv")
    rows = history(client, account, "2026-02-28")["rows"]
    assert shown(rows) == [(9_900, 1, "CSV import · savings-2026.csv"), (5_000, 0, "Manual edit")]


def test_an_import_that_added_the_balance_is_its_first_row(client, account):
    run_import(client, account, name="a-file.csv")
    rows = history(client, account, "2026-01-31")["rows"]
    assert shown(rows) == [(100_000, 1, "CSV import · a-file.csv")]


def test_the_update_balances_screen_is_how_it_reads(client, account):
    response = client.post("/api/balances/update", json={"date": "2026-03-31", "amounts": {str(account): "700.00"}, "versions": {str(account): None}})
    assert response.status_code == 200, response.text
    assert shown(history(client, account, "2026-03-31")["rows"]) == [(70_000, 1, "Update balances")]


# -- a balance the log never saw created --

def test_a_balance_from_before_the_log_has_one_baseline_row_by_the_system_user(client, account):
    with with_db(client) as conn:
        add_balance(conn, account, "2026-01-31", 100_000)             # written straight to the table, so the log has nothing
        conn.commit()
    body = history(client, account, "2026-01-31")
    assert shown(body["rows"]) == [(100_000, 1, "Entered")]
    assert body["rows"][0]["_id"] == balance(client, account, "2026-01-31")["id"]      # a baseline row has the balance's own id; a log row a negative one


def test_the_baseline_amount_is_the_one_before_the_first_logged_change(client, account):
    with with_db(client) as conn:
        add_balance(conn, account, "2026-01-31", 100_000)
        conn.commit()
    edit(client, account, "2026-01-31", "1100.00")
    edit(client, account, "2026-01-31", "1250.00")
    assert shown(history(client, account, "2026-01-31")["rows"]) == [
        (125_000, 1, "Manual edit"), (110_000, 0, "Manual edit"), (100_000, 0, "Entered")]


def test_a_note_only_first_change_leaves_the_baseline_amount_the_amount_now(client, account):
    with with_db(client) as conn:
        add_balance(conn, account, "2026-01-31", 100_000)
        conn.commit()
    edit(client, account, "2026-01-31", "1000.00", note="A note")
    assert shown(history(client, account, "2026-01-31")["rows"]) == [(100_000, 1, "Manual edit · note changed"), (100_000, 0, "Entered")]


# -- what it leaves out --

def test_it_is_only_that_balances_changes(client, account):
    add(client, account, "2026-01-31", "1000.00")
    add(client, account, "2026-02-28", "2000.00")
    edit(client, account, "2026-02-28", "2100.00")
    assert history(client, account, "2026-01-31")["total"] == 1
    assert history(client, account, "2026-02-28")["total"] == 2


def test_a_deleted_balance_and_a_balance_of_a_deleted_account_have_no_history(client, account):
    add(client, account, "2026-01-31", "1000.00")
    add(client, account, "2026-02-28", "2000.00")
    gone, kept = balance(client, account, "2026-01-31"), balance(client, account, "2026-02-28")
    assert client.delete(f"/api/balances/{gone['id']}", params={"version": gone["version"]}).status_code == 200
    assert client.post(LIST, json={"params": {"balance": gone["id"]}}).status_code == 404
    with with_db(client) as conn:
        accounts.delete_account(op(conn), account)
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM balance_history").fetchone()[0] == 0
    assert client.post(LIST, json={"params": {"balance": kept["id"]}}).status_code == 404


def test_a_balance_that_does_not_exist_is_not_found(client):
    assert client.post(LIST, json={"params": {"balance": 99999}}).status_code == 404


# -- the list --

def test_it_is_a_fixed_list_with_the_agreed_columns_twelve_to_a_page(client, account):
    add(client, account, "2026-01-31", "1000.00")
    body = history(client, account, "2026-01-31")
    assert [c["label"] for c in body["columns"]] == ["When", "By", "Amount", "Current", "How", "Restorable"]
    assert body["sort"] == {"field": "changed_at", "direction": "desc"}
    assert (body["page_size"], body["customisable"], body["filters"]) == (12, False, [])


def test_more_than_twelve_changes_are_paged_newest_first(client, account):
    add(client, account, "2026-01-31", "1.00")
    for n in range(2, 16):
        edit(client, account, "2026-01-31", f"{n}.00")
    first, second = history(client, account, "2026-01-31"), history(client, account, "2026-01-31", page=2)
    assert (first["total"], first["pages"], len(first["rows"]), len(second["rows"])) == (15, 2, 12, 3)
    assert first["rows"][0]["amount_cents"]["value"] == 1500 and first["rows"][0]["is_current"] == 1
    assert second["rows"][-1]["amount_cents"]["value"] == 100


def test_a_non_balance_parameter_and_a_missing_one_are_refused(client, account):
    assert client.post(LIST, json={}).status_code in (400, 422)
    assert client.post(LIST, json={"params": {"account": account}}).status_code in (400, 422)


# -- upgrading --

def test_the_upgrade_gives_a_balance_that_the_log_never_saw_one_baseline_row_and_changes_nothing_else(tmp_path):
    """Migration 0029 tested on a copy of a database as the migration before it left it, holding balances written before the view."""
    import shutil
    from northstar import db

    folder = tmp_path / "before"
    folder.mkdir()
    for file in db.MIGRATIONS_DIR.glob("*.sql"):
        if not file.name.startswith(("0029", "0030")):
            shutil.copy(file, folder)
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path, folder)
    conn = db.connect(path)
    use_dollars(conn)
    account_id = add_account(conn, "Test upgrade", ASSET, "Savings")
    add_balance(conn, account_id, "2026-01-31", 100_000)
    add_balance(conn, account_id, "2026-02-28", 120_000)
    conn.commit()
    balances_before = [tuple(r) for r in conn.execute("SELECT * FROM balances ORDER BY id")]
    log_before = conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0]
    conn.close()

    assert db.upgrade(path) == ["0029_balance_history", "0030_restore_balance_value"]
    conn = db.connect(path)
    rows = [tuple(r) for r in conn.execute("SELECT balance_id, amount_cents, how, is_current FROM balance_history ORDER BY balance_id")]
    assert rows == [(1, 100_000, "Entered", 1), (2, 120_000, "Entered", 1)]
    assert [tuple(r) for r in conn.execute("SELECT * FROM balances ORDER BY id")] == balances_before     # the view changed no data
    assert conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0] == log_before
    conn.close()
