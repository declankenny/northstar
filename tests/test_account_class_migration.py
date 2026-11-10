"""Migration 0019 removes accounts.class_id: an account's class is its type's class (issue 181). It is tested on a copy of a
database as the migration before it left it, holding synthetic accounts in every state."""

import shutil
import sqlite3

import pytest

from northstar import accounts, db
from conftest import op, type_id

SYSTEM = "(SELECT id FROM users WHERE is_system = 1)"
USD = "(SELECT id FROM currencies WHERE code = 'USD')"


@pytest.fixture
def before(tmp_path):
    """A database with every migration but 0019 and what came after it, and what it holds: (path, accounts as {id: (name, class, type, deleted)})."""
    folder = tmp_path / "before"
    folder.mkdir()
    for file in db.MIGRATIONS_DIR.glob("*.sql"):
        if not file.name.startswith(("0019", "0020", "0021", "0022", "0023", "0024", "0025")):
            shutil.copy(file, folder)
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path, folder)
    conn = db.connect(path)
    # Synthetic accounts of both classes: open, closed and deleted. (name, class, type, is_open, deleted)
    for name, klass, type_name, is_open, deleted in [
        ("Test checking", 1, "Checking", 1, 0), ("Test loan", 2, "Loan", 1, 0), ("Test closed savings", 1, "Savings", 0, 0),
        ("Test deleted card", 2, "Credit card", 1, 1),
    ]:
        account = conn.execute(
            f"INSERT INTO accounts (name, class_id, type_id, currency_id, is_open, deleted, created_by, updated_by) "
            f"VALUES (?, ?, ?, {USD}, ?, ?, {SYSTEM}, {SYSTEM})",
            (name, klass, type_id(conn, type_name), is_open, deleted)).lastrowid
        conn.execute(f"INSERT INTO balances (account_id, as_of_date, amount_cents, created_by, updated_by) "
                     f"VALUES (?, '2026-01-31', 12345, {SYSTEM}, {SYSTEM})", (account,))
    # A type that was added and deleted, so the counter is ahead of the highest id.
    gone = conn.execute(f"INSERT INTO account_types (name, class_id, stale_after_days, created_by, updated_by) "
                        f"VALUES ('Test gone', 1, 35, {SYSTEM}, {SYSTEM})").lastrowid
    conn.execute("DELETE FROM account_types WHERE id = ?", (gone,))
    conn.commit()
    held = {r["id"]: tuple(r)[1:] for r in conn.execute(
        "SELECT id, name, class_id, type_id, is_open, deleted FROM accounts ORDER BY id")}
    days = [tuple(r) for r in conn.execute("SELECT DISTINCT account_id, class_name FROM account_days ORDER BY account_id")]
    conn.close()
    return path, held, days, gone


def test_the_upgrade_drops_the_class_and_keeps_every_account_in_its_class(before):
    path, held, days_before, _ = before
    assert db.upgrade(path) == ["0019_account_class_from_type", "0020_live_balance_values", "0021_user_list_prefs", "0022_list_filters", "0023_user_list_columns", "0024_account_summaries", "0025_accounts_list"]
    conn = db.connect(path)
    assert "class_id" not in {r["name"] for r in conn.execute("PRAGMA table_info(accounts)")}
    after = {r["id"]: tuple(r)[1:] for r in conn.execute(
        "SELECT a.id, a.name, t.class_id, a.type_id, a.is_open, a.deleted FROM accounts a "
        "JOIN account_types t ON t.id = a.type_id ORDER BY a.id")}
    assert after == held                                       # the same accounts, each in the class it was in
    assert conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0] == 4          # no balance lost, deleted account's included
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_the_views_and_net_worth_calendar_come_back_the_same(before):
    path, _, days_before, _ = before
    db.upgrade(path)
    conn = db.connect(path)
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'")} == {
        "live_accounts", "live_balances", "account_days", "live_balance_values", "last_balances", "account_summaries"}
    assert [tuple(r) for r in conn.execute("SELECT DISTINCT account_id, class_name FROM account_days ORDER BY account_id")] == days_before
    assert conn.execute("SELECT COUNT(*) FROM live_accounts").fetchone()[0] == 3         # the deleted one is still out of sight
    assert conn.execute("SELECT COUNT(*) FROM live_balances").fetchone()[0] == 3


def test_the_index_and_the_triggers_survive_and_the_new_one_exists(before):
    path = before[0]
    db.upgrade(path)
    conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'accounts_name_unique'").fetchone()[0] == 1
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    assert {"accounts_currency_fixed", "account_types_class_fixed_while_used"} <= names
    with pytest.raises(sqlite3.IntegrityError):                                          # the unique name rule still holds
        conn.execute(f"INSERT INTO accounts (name, type_id, currency_id, created_by, updated_by) "
                     f"VALUES ('TEST CHECKING', 1, {USD}, {SYSTEM}, {SYSTEM})")


@pytest.mark.parametrize("type_name, other_class", [("Checking", 2), ("Savings", 2), ("Credit card", 1)])      # open, closed, deleted
def test_a_type_keeps_its_class_while_any_account_uses_it_whatever_its_state(before, type_name, other_class):
    path = before[0]
    db.upgrade(path)
    conn = db.connect(path)
    with pytest.raises(sqlite3.IntegrityError, match="class of a type that accounts use"):
        conn.execute("UPDATE account_types SET class_id = ? WHERE name = ?", (other_class, type_name))


def test_a_deleted_types_id_is_not_given_to_a_new_type_after_the_upgrade(before):
    path, _, _, gone = before
    db.upgrade(path)
    conn = db.connect(path)
    new = conn.execute(f"INSERT INTO account_types (name, class_id, stale_after_days, created_by, updated_by) "
                       f"VALUES ('Test new', 1, 35, {SYSTEM}, {SYSTEM})").lastrowid
    assert new == gone + 1
    account = conn.execute(f"INSERT INTO accounts (name, type_id, currency_id, created_by, updated_by) "
                           f"VALUES ('Test new account', 1, {USD}, {SYSTEM}, {SYSTEM})").lastrowid
    assert account == 5                                                                  # after the four, none reused


def test_the_application_still_adds_and_reclassifies_accounts_after_the_upgrade(before):
    path = before[0]
    db.upgrade(path)
    conn = db.connect(path)
    conn.execute("UPDATE system_properties SET value = 'USD' WHERE name = 'system.currency'")      # as an administrator would
    account = accounts.add_account(op(conn), "Test added", 1, type_id(conn, "Savings"))
    assert accounts.get_account(conn, account)["class_name"] == "Asset"
    accounts.change_class(op(conn), account, type_id(conn, "Loan"))
    assert accounts.get_account(conn, account)["class_name"] == "Liability"
