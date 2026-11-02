"""Deleting an account hides it and its balances everywhere and keeps them in the database (migration 0007).
Synthetic data only."""

import re
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from northstar import account_types, accounts, balances, db, networth, writer
from northstar.errors import NotFoundError, ValidationError

from conftest import add_account, add_balance, op, type_id, with_db
from test_migration_runner import REBUILD_ACCOUNTS, counts, folder_with, v01_database
from test_writer import strings_in

ASSET, LIABILITY = 1, 2
TODAY = date(2026, 10, 30)


@pytest.fixture
def household(conn):
    """A checking account (assets) and a mortgage (liabilities), each with balances, and the net worth to expect."""
    checking = add_account(conn, "Test checking", ASSET, "Checking")
    add_balance(conn, checking, "2026-01-31", 100000)
    add_balance(conn, checking, "2026-06-30", 150000)
    mortgage = add_account(conn, "Test mortgage", LIABILITY, "Mortgage")
    add_balance(conn, mortgage, "2026-03-31", 40000)
    return {"checking": checking, "mortgage": mortgage}


def now(conn, account_id=None):
    return networth.net_worth_on(conn, TODAY, account_id)


# -- what deleting does --

def test_deleting_marks_the_account_and_keeps_every_row(conn, household):
    assert accounts.delete_account(op(conn), household["checking"]) == 2
    assert conn.execute("SELECT deleted FROM accounts WHERE id = ?", (household["checking"],)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM balances WHERE account_id = ?", (household["checking"],)).fetchone()[0] == 2


def test_a_deleted_account_is_gone_from_every_account_read(conn, household):
    accounts.delete_account(op(conn), household["checking"])
    for read in (
        lambda: accounts.get_account(conn, household["checking"]),
        lambda: accounts.account_summary(conn, household["checking"], TODAY),
        lambda: accounts.account_page(conn, household["checking"], TODAY),
        lambda: accounts.delete_account(op(conn), household["checking"]),
        lambda: accounts.close_account(op(conn), household["checking"]),
        lambda: accounts.update_account(op(conn), household["checking"], "Renamed", type_id(conn, "Checking")),
    ):
        with pytest.raises(NotFoundError):
            read()
    assert [row["name"] for row in accounts.account_rows(conn, TODAY)] == ["Test mortgage"]
    assert accounts.account_rows(conn, TODAY, closed=True) == []
    assert [row["name"] for row in balances.update_rows(conn, TODAY, TODAY)] == ["Test mortgage"]


def test_a_deleted_closed_account_leaves_the_closed_list(conn):
    old = add_account(conn, "Test old card", LIABILITY, "Credit card")
    accounts.close_account(op(conn), old)
    assert [row["name"] for row in accounts.account_rows(conn, TODAY, closed=True)] == ["Test old card"]
    accounts.delete_account(op(conn), old)
    assert accounts.account_rows(conn, TODAY, closed=True) == []


def test_a_deleted_accounts_balances_cannot_be_read_or_changed(conn, household):
    balance_id = conn.execute("SELECT id FROM balances WHERE account_id = ? LIMIT 1", (household["checking"],)).fetchone()[0]
    accounts.delete_account(op(conn), household["checking"])
    for action in (
        lambda: balances.get_balance(conn, balance_id),
        lambda: balances.record_balance(op(conn), household["checking"], TODAY, 1),
        lambda: balances.add_balance(op(conn), household["checking"], "2026-10-01", "1.00", None, TODAY),
        lambda: balances.update_balance(op(conn), balance_id, "2026-10-01", "1.00", None, TODAY),
        lambda: balances.delete_balance(op(conn), balance_id),
    ):
        with pytest.raises(NotFoundError):
            action()
    assert conn.execute("SELECT COUNT(*) FROM balances WHERE account_id = ?", (household["checking"],)).fetchone()[0] == 2


def test_net_worth_changes_as_if_the_account_had_never_existed(conn, household):
    assert now(conn) == {"date": "2026-10-30", "assets": 150000, "liabilities": 40000, "net_worth": 110000}
    accounts.delete_account(op(conn), household["checking"])
    assert now(conn) == {"date": "2026-10-30", "assets": 0, "liabilities": 40000, "net_worth": -40000}
    assert networth.net_worth_on(conn, date(2026, 2, 28))["net_worth"] == 0              # and in the past
    with pytest.raises(NotFoundError):
        networth.net_worth_series(conn, TODAY, account_id=household["checking"])        # and its own series is gone


def test_the_net_worth_series_does_not_start_at_a_deleted_accounts_first_balance(conn, household):
    accounts.delete_account(op(conn), household["checking"])          # its balances start in January
    result = networth.net_worth_series(conn, TODAY, None, None, "month")
    assert result["start"] == "2026-03-31"                              # the mortgage's first balance
    assert result["series"][0]["net_worth"] == -40000


def test_deleting_the_only_account_leaves_no_series_at_all(conn, household):
    accounts.delete_account(op(conn), household["checking"])
    accounts.delete_account(op(conn), household["mortgage"])
    assert networth.net_worth_series(conn, TODAY, None, None, "month")["series"] == []


def test_deleting_one_account_leaves_the_others_untouched(conn, household):
    before = accounts.get_account(conn, household["mortgage"])
    accounts.delete_account(op(conn), household["checking"])
    assert dict(accounts.get_account(conn, household["mortgage"])) == dict(before)
    assert now(conn, household["mortgage"])["liabilities"] == 40000


def test_the_count_returned_is_of_the_balances_that_were_visible(conn):
    account = add_account(conn, "Test empty", ASSET, "Checking")
    assert accounts.delete_account(op(conn), account) == 0


# -- the name --

def test_a_deleted_account_frees_its_name(conn, household):
    accounts.delete_account(op(conn), household["checking"])
    new = accounts.add_account(op(conn), "test CHECKING", ASSET, type_id(conn, "Checking"))
    assert new != household["checking"] and accounts.get_account(conn, new)["name"] == "test CHECKING"


def test_a_closed_account_still_holds_its_name(conn):
    old = add_account(conn, "Test old card", LIABILITY, "Credit card")
    accounts.close_account(op(conn), old)
    with pytest.raises(ValidationError, match="closed account"):
        accounts.add_account(op(conn), "Test old card", LIABILITY, type_id(conn, "Credit card"))


def test_the_name_rule_is_partial_in_the_database_too(conn, household):
    [sql] = [row[0] for row in conn.execute("SELECT sql FROM sqlite_master WHERE name = 'accounts_name_unique'")]
    assert "WHERE deleted = 0" in sql and "NOCASE" in sql
    accounts.delete_account(op(conn), household["checking"])
    system = "(SELECT id FROM users WHERE is_system = 1)"
    insert = f"INSERT INTO accounts (name, class_id, type_id, created_by, updated_by) VALUES (?, 1, 1, {system}, {system})"
    conn.execute(insert, ("TEST CHECKING",))                                   # the name is free
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("test checking",))                                # but still unique among live accounts


# -- the views --

def test_the_views_show_only_live_accounts_and_their_balances(conn, household):
    accounts.delete_account(op(conn), household["checking"])
    assert [row[0] for row in conn.execute("SELECT id FROM live_accounts")] == [household["mortgage"]]
    assert [row[0] for row in conn.execute("SELECT DISTINCT account_id FROM live_balances")] == [household["mortgage"]]
    assert {row["name"] for row in conn.execute("PRAGMA table_info(live_balances)")} >= {"id", "account_id", "amount_cents"}


def test_the_flag_only_accepts_zero_or_one(conn, household):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE accounts SET deleted = 2")


# -- accounts and users are never removed --

@pytest.mark.parametrize("table", ["accounts", "users"])
def test_the_writer_refuses_to_remove_a_row_that_is_only_ever_marked_deleted(conn, household, table):
    with pytest.raises(ValueError, match="marked deleted"):
        writer.delete(op(conn), table, 1)
    assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] >= 1


# -- a type is held by deleted accounts too --

def test_a_type_used_only_by_a_deleted_account_cannot_be_deleted_or_change_class(conn):
    account = add_account(conn, "Test account", ASSET, "Savings")
    accounts.delete_account(op(conn), account)
    savings = type_id(conn, "Savings")
    with pytest.raises(ValidationError, match="1 deleted account uses this type. Restoring deleted accounts isn't possible yet"):
        account_types.delete_type(op(conn), savings)
    with pytest.raises(ValidationError, match="class can't change"):
        account_types.update_type(op(conn), savings, "Savings", 35, LIABILITY)
    assert conn.execute("SELECT COUNT(*) FROM account_types WHERE id = ?", (savings,)).fetchone()[0] == 1


def test_the_message_counts_live_and_deleted_accounts_together(conn):
    for name in ("Test one", "Test two", "Test three"):
        add_account(conn, name, ASSET, "Savings")
    accounts.delete_account(op(conn), conn.execute("SELECT id FROM accounts WHERE name = 'Test three'").fetchone()[0])
    with pytest.raises(ValidationError, match="3 accounts use this type, 1 of them deleted. Restoring"):
        account_types.delete_type(op(conn), type_id(conn, "Savings"))


def test_a_type_with_only_live_accounts_keeps_its_old_message(conn):
    add_account(conn, "Test one", ASSET, "Savings")
    with pytest.raises(ValidationError, match="1 account uses this type. Change their type first."):
        account_types.delete_type(op(conn), type_id(conn, "Savings"))


def test_the_types_list_counts_live_and_deleted_accounts_separately(conn):
    for name in ("Test one", "Test two"):
        add_account(conn, name, ASSET, "Savings")
    accounts.delete_account(op(conn), conn.execute("SELECT id FROM accounts WHERE name = 'Test two'").fetchone()[0])
    row = next(r for r in account_types.list_types(conn) if r["name"] == "Savings")
    assert (row["account_count"], row["deleted_account_count"]) == (1, 1)


def test_the_types_api_reports_the_deleted_count(client):
    with with_db(client) as conn:
        account = add_account(conn, "Test one", ASSET, "Savings")
        accounts.delete_account(op(conn), account)
    listed = next(t for t in client.get("/api/types").json()["types"] if t["name"] == "Savings")
    assert (listed["account_count"], listed["deleted_account_count"]) == (0, 1)
    assert client.delete(f"/api/types/{listed['id']}").status_code == 422


def test_a_type_with_no_accounts_at_all_can_still_be_deleted(conn):
    account_types.delete_type(op(conn), type_id(conn, "Savings"))


# -- nothing reads the tables around the views --

SOURCE = Path(__file__).resolve().parent.parent / "northstar"
READS = re.compile(r"\b(FROM|JOIN)\s+(accounts|balances)\b", re.I)
# Files that may read the tables directly, and why: the backup tool counts every row, the account types module has to
# see deleted accounts because they still hold their type, and the imports register has to name the account of an import
# even when it has been deleted. None may read balances except the backup tool.
EXEMPT = {"backup.py": {"accounts", "balances"}, "account_types.py": {"accounts"}, "import_register.py": {"accounts"}}


def direct_reads(source: str) -> set[str]:
    return {match.group(2).lower() for text in strings_in(source) for match in READS.finditer(text)}


def test_the_scan_notices_a_direct_read_and_ignores_the_views():
    assert direct_reads('conn.execute("SELECT * FROM accounts a JOIN balances b")') == {"accounts", "balances"}
    assert direct_reads('sql = "select 1 from Balances"') == {"balances"}
    assert not direct_reads('conn.execute("SELECT * FROM live_accounts a JOIN live_balances b")')
    assert not direct_reads('def f():\n    """Reads FROM accounts."""\n    return 1')


def test_every_read_of_accounts_and_balances_goes_through_the_live_views():
    found = {}
    for file in sorted(SOURCE.rglob("*.py")):
        extra = direct_reads(file.read_text(encoding="utf-8")) - EXEMPT.get(file.name, set())
        if extra and file.name != "writer.py":
            found[str(file.relative_to(SOURCE))] = sorted(extra)
    assert not found, f"These read accounts or balances directly and would show deleted accounts: {found}"


# -- upgrading, and rebuilding later --

def test_the_upgrade_keeps_every_account_live_and_every_balance_in_view(tmp_path):
    path = v01_database(tmp_path / "data" / "northstar.db")
    db.upgrade(path)
    conn = db.connect(path)
    assert counts(conn) == [1, 1]
    assert conn.execute("SELECT COUNT(*) FROM live_accounts").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM live_balances").fetchone()[0] == 1
    assert conn.execute("SELECT deleted FROM accounts").fetchone()[0] == 0


def test_rebuilding_accounts_without_dropping_the_views_first_fails_as_the_migration_warns(tmp_path, conn):
    """The comment in migration 0007 says a rebuild must drop the views. This is that claim, tested."""
    without_the_drop = REBUILD_ACCOUNTS.replace("DROP VIEW live_accounts;\nDROP VIEW live_balances;\n", "")
    assert without_the_drop != REBUILD_ACCOUNTS
    folder = folder_with(tmp_path, **{"0100_rebuild": without_the_drop})
    with pytest.raises(sqlite3.Error):
        db.migrate(conn, folder)
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'accounts_new'").fetchone()[0] == 0   # rolled back
