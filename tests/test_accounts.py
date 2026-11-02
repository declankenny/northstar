import pytest

from northstar import accounts
from northstar.errors import ValidationError

from conftest import add_account, add_balance, type_id, op

ASSET, LIABILITY = 1, 2


def test_add_account(conn):
    new_id = accounts.add_account(op(conn), "  Test checking ", ASSET, type_id(conn, "Checking"), " main one ")
    row = accounts.get_account(conn, new_id)
    assert (row["name"], row["class_name"], row["type_name"], row["notes"], row["is_open"]) == (
        "Test checking", "Asset", "Checking", "main one", 1)


@pytest.mark.parametrize("name", ["", "   ", None])
def test_add_rejects_blank_name(conn, name):
    with pytest.raises(ValidationError, match="Name is required"):
        accounts.add_account(op(conn), name, ASSET, type_id(conn, "Checking"))


def test_add_rejects_type_from_the_other_class(conn):
    with pytest.raises(ValidationError, match="Choose a type"):
        accounts.add_account(op(conn), "Test", ASSET, type_id(conn, "Mortgage"))


@pytest.mark.parametrize("bad", [None, 9999])
def test_add_rejects_missing_or_unknown_type(conn, bad):
    with pytest.raises(ValidationError, match="Choose a type"):
        accounts.add_account(op(conn), "Test", ASSET, bad)


def test_blank_notes_are_stored_as_nothing(conn):
    new_id = accounts.add_account(op(conn), "Test", ASSET, type_id(conn, "Checking"), "   ")
    assert accounts.get_account(conn, new_id)["notes"] is None


def test_update_within_class(conn):
    acct = add_account(conn, "Test", ASSET, "Checking")
    accounts.update_account(op(conn), acct, "Renamed", type_id(conn, "Savings"), "note")
    row = accounts.get_account(conn, acct)
    assert (row["name"], row["type_name"], row["notes"], row["class_name"]) == ("Renamed", "Savings", "note", "Asset")


def test_update_cannot_move_to_a_type_in_the_other_class(conn):
    acct = add_account(conn, "Test", ASSET, "Checking")
    with pytest.raises(ValidationError, match="Choose a type"):
        accounts.update_account(op(conn), acct, "Test", type_id(conn, "Loan"))
    assert accounts.get_account(conn, acct)["class_name"] == "Asset"


def test_update_missing_account(conn):
    with pytest.raises(ValidationError, match="no longer exists"):
        accounts.update_account(op(conn), 9999, "x", 1)


def test_change_class_moves_class_and_type_together(conn):
    acct = add_account(conn, "Test", ASSET, "Checking")
    accounts.change_class(op(conn), acct, type_id(conn, "Loan"))
    row = accounts.get_account(conn, acct)
    assert (row["class_name"], row["type_name"]) == ("Liability", "Loan")


def test_change_class_keeps_the_balances(conn):
    acct = add_account(conn, "Test", ASSET, "Checking")
    add_balance(conn, acct, "2026-01-31", 100)
    accounts.change_class(op(conn), acct, type_id(conn, "Loan"))
    assert accounts.get_account(conn, acct)["balance_count"] == 1


def test_change_class_requires_a_type_in_the_other_class(conn):
    acct = add_account(conn, "Test", ASSET, "Checking")
    with pytest.raises(ValidationError, match="other class"):
        accounts.change_class(op(conn), acct, type_id(conn, "Savings"))
    with pytest.raises(ValidationError, match="Choose a type"):
        accounts.change_class(op(conn), acct, None)
    assert accounts.get_account(conn, acct)["class_name"] == "Asset"


def test_close_account_with_no_balances(conn):
    acct = add_account(conn, "Test", ASSET, "Checking")
    accounts.close_account(op(conn), acct)
    assert accounts.get_account(conn, acct)["is_open"] == 0


def test_close_account_whose_latest_balance_is_zero(conn):
    acct = add_account(conn, "Test", ASSET, "Checking")
    add_balance(conn, acct, "2026-01-31", 5000)
    add_balance(conn, acct, "2026-02-28", 0)
    accounts.close_account(op(conn), acct)


def test_close_uses_the_latest_by_date_not_by_entry_order(conn):
    acct = add_account(conn, "Test", ASSET, "Checking")
    add_balance(conn, acct, "2026-02-28", 0)      # entered first, dated later
    add_balance(conn, acct, "2026-01-31", 5000)   # entered second, dated earlier
    accounts.close_account(op(conn), acct)


def test_close_refused_when_latest_balance_is_not_zero(conn):
    acct = add_account(conn, "Test", ASSET, "Checking")
    add_balance(conn, acct, "2026-01-31", 0)
    add_balance(conn, acct, "2026-02-28", -1)
    with pytest.raises(ValidationError, match="final zero balance"):
        accounts.close_account(op(conn), acct)
    assert accounts.get_account(conn, acct)["is_open"] == 1


def test_close_twice_and_reopen(conn):
    acct = add_account(conn, "Test", ASSET, "Checking")
    accounts.close_account(op(conn), acct)
    with pytest.raises(ValidationError, match="already closed"):
        accounts.close_account(op(conn), acct)
    accounts.reopen_account(op(conn), acct)
    assert accounts.get_account(conn, acct)["is_open"] == 1
    with pytest.raises(ValidationError, match="already open"):
        accounts.reopen_account(op(conn), acct)


def test_delete_account_returns_balance_count_and_removes_balances(conn):
    acct = add_account(conn, "Test", ASSET, "Checking")
    add_balance(conn, acct, "2026-01-31", 100)
    add_balance(conn, acct, "2026-02-28", 200)
    assert accounts.delete_account(op(conn), acct) == 2
    assert conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0] == 0
    with pytest.raises(ValidationError):
        accounts.get_account(conn, acct)


def test_delete_missing_account(conn):
    with pytest.raises(ValidationError, match="no longer exists"):
        accounts.delete_account(op(conn), 9999)


def test_types_for_class_and_other_class(conn):
    assert {r["name"] for r in accounts.types_for_class(conn, LIABILITY)} == {
        "Credit card", "Loan", "Mortgage", "Other liability"}
    assert accounts.other_class(conn, ASSET)["name"] == "Liability"
    assert accounts.get_class_by_slug(conn, "ASSET")["id"] == ASSET
    with pytest.raises(ValidationError):
        accounts.get_class_by_slug(conn, "equity")
