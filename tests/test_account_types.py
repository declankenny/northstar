import pytest

from northstar import account_types as types
from northstar.errors import ValidationError

from conftest import add_account, type_id

ASSET, LIABILITY = 1, 2


def test_add_type(conn):
    new_id = types.add_type(conn, "  529 plan ", ASSET, "90")
    row = types.get_type(conn, new_id)
    assert (row["name"], row["class_id"], row["stale_after_days"]) == ("529 plan", ASSET, 90)


@pytest.mark.parametrize("name", ["", "   ", None])
def test_add_rejects_blank_name(conn, name):
    with pytest.raises(ValidationError, match="Name is required"):
        types.add_type(conn, name, ASSET, 35)


def test_add_rejects_duplicate_name_ignoring_case(conn):
    with pytest.raises(ValidationError, match="already exists"):
        types.add_type(conn, "checking", ASSET, 35)


@pytest.mark.parametrize("days", [0, -5, "abc", "", None, "1.5"])
def test_add_rejects_bad_stale_days(conn, days):
    with pytest.raises(ValidationError, match="whole number"):
        types.add_type(conn, "Test type", ASSET, days)


@pytest.mark.parametrize("class_id", [None, 0, 99])
def test_add_rejects_unknown_class(conn, class_id):
    with pytest.raises(ValidationError, match="Asset or Liability"):
        types.add_type(conn, "Test type", class_id, 35)


def test_rename_and_change_days(conn):
    tid = type_id(conn, "Savings")
    types.update_type(conn, tid, "High-yield savings", 60)
    row = types.get_type(conn, tid)
    assert (row["name"], row["stale_after_days"]) == ("High-yield savings", 60)


def test_update_keeping_own_name_is_not_a_duplicate(conn):
    tid = type_id(conn, "Savings")
    types.update_type(conn, tid, "savings", 40)  # same name, different case


def test_update_rejects_another_types_name(conn):
    with pytest.raises(ValidationError, match="already exists"):
        types.update_type(conn, type_id(conn, "Savings"), "Checking", 35)


def test_class_can_change_while_unused(conn):
    tid = type_id(conn, "Savings")
    types.update_type(conn, tid, "Savings", 35, class_id=LIABILITY)
    assert types.get_type(conn, tid)["class_id"] == LIABILITY


def test_class_cannot_change_while_in_use(conn):
    add_account(conn, "Test account", ASSET, "Checking")
    tid = type_id(conn, "Checking")
    with pytest.raises(ValidationError, match="can't change"):
        types.update_type(conn, tid, "Checking", 35, class_id=LIABILITY)
    assert types.get_type(conn, tid)["class_id"] == ASSET


def test_update_without_class_keeps_the_class_even_in_use(conn):
    add_account(conn, "Test account", ASSET, "Checking")
    types.update_type(conn, type_id(conn, "Checking"), "Current account", 45)


def test_update_missing_type(conn):
    with pytest.raises(ValidationError, match="no longer exists"):
        types.update_type(conn, 9999, "Whatever", 35)


def test_delete_unused_type(conn):
    tid = type_id(conn, "Savings")
    types.delete_type(conn, tid)
    with pytest.raises(ValidationError):
        types.get_type(conn, tid)


def test_delete_type_in_use_is_refused_with_the_count(conn):
    add_account(conn, "Test account one", ASSET, "Checking")
    add_account(conn, "Test account two", ASSET, "Checking")
    with pytest.raises(ValidationError, match="2 accounts use this type"):
        types.delete_type(conn, type_id(conn, "Checking"))


def test_delete_missing_type(conn):
    with pytest.raises(ValidationError, match="no longer exists"):
        types.delete_type(conn, 9999)


def test_list_types_counts_accounts(conn):
    add_account(conn, "Test account", ASSET, "Checking")
    counts = {r["name"]: r["account_count"] for r in types.list_types(conn)}
    assert counts["Checking"] == 1 and counts["Savings"] == 0
