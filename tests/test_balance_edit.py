from datetime import date

import pytest

from northstar import accounts, balances
from northstar.errors import ValidationError

from conftest import add_account, add_balance

ASSET = 1
TODAY = date(2026, 10, 30)


def only_balance(conn, account_id):
    return dict(conn.execute("SELECT * FROM balances WHERE account_id = ?", (account_id,)).fetchone())


def balance_id(conn, account_id, as_of):
    return conn.execute("SELECT id FROM balances WHERE account_id = ? AND as_of_date = ?",
                        (account_id, as_of)).fetchone()["id"]


# -- notes on record_balance --

def test_new_balance_can_carry_a_note(conn):
    acct = add_account(conn, "A", ASSET, "Checking")
    balances.record_balance(conn, acct, date(2026, 10, 1), 100, "  after payday ")
    assert only_balance(conn, acct)["note"] == "after payday"


def test_leaving_the_note_out_keeps_the_existing_one(conn):
    acct = add_account(conn, "A", ASSET, "Checking")
    balances.record_balance(conn, acct, date(2026, 10, 1), 100, "keep me")
    assert balances.record_balance(conn, acct, date(2026, 10, 1), 200) == "updated"
    row = only_balance(conn, acct)
    assert (row["amount_cents"], row["note"]) == (200, "keep me")


def test_a_blank_note_clears_the_existing_one(conn):
    acct = add_account(conn, "A", ASSET, "Checking")
    balances.record_balance(conn, acct, date(2026, 10, 1), 100, "old")
    assert balances.record_balance(conn, acct, date(2026, 10, 1), 100, "   ") == "updated"
    assert only_balance(conn, acct)["note"] is None


def test_same_amount_and_note_is_unchanged_but_a_new_note_alone_is_an_update(conn):
    acct = add_account(conn, "A", ASSET, "Checking")
    balances.record_balance(conn, acct, date(2026, 10, 1), 100, "n")
    assert balances.record_balance(conn, acct, date(2026, 10, 1), 100, "n") == "unchanged"
    assert balances.record_balance(conn, acct, date(2026, 10, 1), 100, "different") == "updated"


def test_note_length_is_capped(conn):
    acct = add_account(conn, "A", ASSET, "Checking")
    balances.record_balance(conn, acct, date(2026, 10, 1), 1, "x" * 500)
    with pytest.raises(ValidationError, match="too long"):
        balances.record_balance(conn, acct, date(2026, 10, 2), 1, "x" * 501)


def test_the_update_screen_save_does_not_wipe_notes(conn):
    acct = add_account(conn, "A", ASSET, "Checking")
    balances.record_balance(conn, acct, date(2026, 10, 30), 100, "important")
    balances.save_update(conn, "2026-10-30", {acct: "5.00"}, TODAY)
    row = only_balance(conn, acct)
    assert (row["amount_cents"], row["note"]) == (500, "important")


# -- the detail page's Add a balance --

def test_add_balance_from_typed_text(conn):
    acct = add_account(conn, "A", ASSET, "Checking")
    assert balances.add_balance(conn, acct, "2026-10-30", "$1,234.56", "hello", TODAY) == "added"
    row = only_balance(conn, acct)
    assert (row["as_of_date"], row["amount_cents"], row["note"], row["source"]) == (
        "2026-10-30", 123456, "hello", "manual")


@pytest.mark.parametrize("date_text, amount, message", [
    ("2026-10-31", "1", "future"), ("nope", "1", "valid date"),
    ("2026-10-30", "1.234", "Enter an amount"), ("2026-10-30", "", "Enter an amount"),
])
def test_add_balance_rejects_bad_input_and_saves_nothing(conn, date_text, amount, message):
    acct = add_account(conn, "A", ASSET, "Checking")
    with pytest.raises(ValidationError, match=message):
        balances.add_balance(conn, acct, date_text, amount, None, TODAY)
    assert conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0] == 0


def test_add_balance_to_closed_account_is_refused(conn):
    acct = add_account(conn, "A", ASSET, "Checking")
    accounts.close_account(conn, acct)
    with pytest.raises(ValidationError, match="Reopen it before changing its balances"):
        balances.add_balance(conn, acct, "2026-10-30", "5", None, TODAY)


# -- editing --

def test_get_balance_includes_the_account(conn):
    acct = add_account(conn, "Everyday", ASSET, "Checking")
    add_balance(conn, acct, "2026-10-01", 100)
    got = balances.get_balance(conn, balance_id(conn, acct, "2026-10-01"))
    assert (got["account_name"], got["account_id"], got["is_open"], got["amount_cents"]) == ("Everyday", acct, 1, 100)
    with pytest.raises(ValidationError, match="no longer exists"):
        balances.get_balance(conn, 9999)


def test_update_balance_changes_date_amount_and_note(conn):
    acct = add_account(conn, "A", ASSET, "Checking")
    add_balance(conn, acct, "2026-10-01", 100)
    bid = balance_id(conn, acct, "2026-10-01")
    assert balances.update_balance(conn, bid, "2026-09-15", "2.50", " fixed ", TODAY) == "updated"
    row = only_balance(conn, acct)
    assert (row["as_of_date"], row["amount_cents"], row["note"]) == ("2026-09-15", 250, "fixed")


def test_update_balance_with_nothing_changed(conn):
    acct = add_account(conn, "A", ASSET, "Checking")
    add_balance(conn, acct, "2026-10-01", 100)
    bid = balance_id(conn, acct, "2026-10-01")
    conn.execute("UPDATE balances SET updated_at = '2000-01-01T00:00:00Z'")
    assert balances.update_balance(conn, bid, "2026-10-01", "1.00", "", TODAY) == "unchanged"
    assert only_balance(conn, acct)["updated_at"] == "2000-01-01T00:00:00Z"


def test_update_balance_refuses_a_date_another_balance_uses(conn):
    acct = add_account(conn, "A", ASSET, "Checking")
    add_balance(conn, acct, "2026-10-01", 100)
    add_balance(conn, acct, "2026-09-01", 200)
    bid = balance_id(conn, acct, "2026-10-01")
    with pytest.raises(ValidationError, match="already a balance on 2026-09-01"):
        balances.update_balance(conn, bid, "2026-09-01", "1", None, TODAY)
    assert balances.get_balance(conn, bid)["as_of_date"] == "2026-10-01"


def test_update_balance_may_reuse_a_date_used_on_another_account(conn):
    a = add_account(conn, "A", ASSET, "Checking")
    b = add_account(conn, "B", ASSET, "Savings")
    add_balance(conn, a, "2026-10-01", 100)
    add_balance(conn, b, "2026-09-01", 200)
    balances.update_balance(conn, balance_id(conn, a, "2026-10-01"), "2026-09-01", "1", None, TODAY)


@pytest.mark.parametrize("date_text, amount, message", [
    ("2026-10-31", "1", "future"), ("", "1", "valid date"), ("2026-10-01", "abc", "Enter an amount")])
def test_update_balance_rejects_bad_input(conn, date_text, amount, message):
    acct = add_account(conn, "A", ASSET, "Checking")
    add_balance(conn, acct, "2026-10-01", 100)
    with pytest.raises(ValidationError, match=message):
        balances.update_balance(conn, balance_id(conn, acct, "2026-10-01"), date_text, amount, None, TODAY)
    assert only_balance(conn, acct)["amount_cents"] == 100


def test_update_and_delete_missing_balance(conn):
    with pytest.raises(ValidationError, match="no longer exists"):
        balances.update_balance(conn, 9999, "2026-10-01", "1", None, TODAY)
    with pytest.raises(ValidationError, match="no longer exists"):
        balances.delete_balance(conn, 9999)


# -- deleting --

def test_delete_balance_removes_only_that_one(conn):
    acct = add_account(conn, "A", ASSET, "Checking")
    add_balance(conn, acct, "2026-10-01", 100)
    add_balance(conn, acct, "2026-09-01", 200)
    balances.delete_balance(conn, balance_id(conn, acct, "2026-10-01"))
    assert [r["as_of_date"] for r in accounts.balance_history(conn, acct)] == ["2026-09-01"]


# -- closed accounts: no changes until reopened --

def test_closed_account_balances_cannot_be_edited_or_deleted_until_reopened(conn):
    acct = add_account(conn, "A", ASSET, "Checking")
    add_balance(conn, acct, "2026-10-01", 0)
    bid = balance_id(conn, acct, "2026-10-01")
    accounts.close_account(conn, acct)
    with pytest.raises(ValidationError, match="Reopen it before changing its balances"):
        balances.update_balance(conn, bid, "2026-10-01", "5", None, TODAY)
    with pytest.raises(ValidationError, match="Reopen it before changing its balances"):
        balances.delete_balance(conn, bid)
    assert only_balance(conn, acct)["amount_cents"] == 0
    accounts.reopen_account(conn, acct)
    balances.update_balance(conn, bid, "2026-10-01", "5", None, TODAY)
    balances.delete_balance(conn, bid)
