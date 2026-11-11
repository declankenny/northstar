import sqlite3

import pytest

from northstar import db, users

from conftest import add_account, type_id, op

ASSET, LIABILITY = 1, 2


def test_foreign_keys_are_on(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_migrate_twice_applies_nothing_the_second_time(conn):
    assert db.migrate(conn) == []


def test_seed_classes_and_types(conn):
    classes = [r["name"] for r in conn.execute("SELECT name FROM account_classes ORDER BY id")]
    assert classes == ["Asset", "Liability"]
    types = {r["name"]: (r["class_id"], r["stale_after_days"]) for r in conn.execute("SELECT * FROM account_types")}
    assert len(types) == 11
    assert types["Checking"] == (ASSET, 35)
    assert types["Real estate"] == (ASSET, 365)
    assert "Vehicle" not in types
    assert types["Mortgage"] == (LIABILITY, 35)


def test_there_is_one_initial_migration_that_includes_users_and_their_theme(conn):
    assert [r["version"] for r in conn.execute("SELECT version FROM sys_schema_migrations ORDER BY version")] == [
        "0001_initial", "0002_login_attempts", "0003_unique_account_names", "0004_audit_columns_and_system_user",
        "0005_sys_table_names", "0006_user_soft_delete", "0007_account_soft_delete", "0008_change_log",
        "0009_system_properties", "0010_currencies", "0011_locales", "0012_rename_stale_days_property", "0013_exchange_rates", "0014_system_timezone", "0015_scheduler", "0016_rate_fetch", "0017_oidc_settings", "0018_oidc_identities", "0019_account_class_from_type", "0020_live_balance_values", "0021_user_list_prefs", "0022_list_filters", "0023_user_list_columns", "0024_account_summaries", "0025_accounts_list", "0026_currency_summaries", "0027_account_balances"]
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'sys_login_attempts'").fetchone()[0] == 1
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    assert {"email", "password_hash", "is_admin", "theme"} <= columns
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'sys_sessions'").fetchone()[0] == 1
    users.create_user(op(conn), "a@example.com", "Test A", "synthetic-pass-123")
    assert conn.execute("SELECT theme FROM users").fetchone()[0] == "dark"       # the default


def test_a_database_that_recorded_the_old_split_migrations_still_opens(conn):
    """The initial migration used to be three files. A database that applied all three has their names
    recorded, and the one remaining file must be treated as applied, with nothing run again."""
    conn.executemany("INSERT INTO sys_schema_migrations (version) VALUES (?)", [("0002_users",), ("0003_user_theme",)])
    assert db.migrate(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM users WHERE is_system = 0").fetchone()[0] == 0


def class_of(conn, account):
    """The class of an account, the way every read gets it: through its type."""
    return conn.execute("SELECT t.class_id FROM accounts a JOIN account_types t ON t.id = a.type_id WHERE a.id = ?",
                        (account,)).fetchone()[0]


def test_an_account_has_no_class_of_its_own_so_it_cannot_disagree_with_its_type(conn):
    assert "class_id" not in {r["name"] for r in conn.execute("PRAGMA table_info(accounts)")}
    acct = add_account(conn, "Test account", ASSET, "Checking")
    assert class_of(conn, acct) == ASSET


def test_changing_the_type_changes_the_class_with_it(conn):
    acct = add_account(conn, "Test account", ASSET, "Checking")
    conn.execute("UPDATE accounts SET type_id = ? WHERE id = ?", (type_id(conn, "Savings"), acct))
    assert class_of(conn, acct) == ASSET
    conn.execute("UPDATE accounts SET type_id = ? WHERE id = ?", (type_id(conn, "Loan"), acct))
    assert class_of(conn, acct) == LIABILITY


def test_type_in_use_cannot_be_deleted_but_unused_can(conn):
    add_account(conn, "Test account", ASSET, "Checking")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM account_types WHERE name = 'Checking'")
    conn.execute("DELETE FROM account_types WHERE name = 'Savings'")


def test_type_class_cannot_change_while_in_use(conn):
    add_account(conn, "Test account", ASSET, "Checking")
    with pytest.raises(sqlite3.IntegrityError, match="class of a type that accounts use"):
        conn.execute("UPDATE account_types SET class_id = ? WHERE name = 'Checking'", (LIABILITY,))
    # An unused type can change class.
    conn.execute("UPDATE account_types SET class_id = ? WHERE name = 'Savings'", (LIABILITY,))


@pytest.mark.parametrize("state", ["open", "closed", "deleted"])
def test_type_class_cannot_change_whatever_state_the_account_using_it_is_in(conn, state):
    """A closed account keeps its balances in net worth, and a deleted one keeps its type so that it can be restored."""
    acct = add_account(conn, "Test account", ASSET, "Savings")
    if state == "closed":
        conn.execute("UPDATE accounts SET is_open = 0 WHERE id = ?", (acct,))
    if state == "deleted":
        conn.execute("UPDATE accounts SET deleted = 1 WHERE id = ?", (acct,))
    with pytest.raises(sqlite3.IntegrityError, match="class of a type that accounts use"):
        conn.execute("UPDATE account_types SET class_id = ? WHERE name = 'Savings'", (LIABILITY,))
    assert class_of(conn, acct) == ASSET
    conn.execute("UPDATE account_types SET name = 'Savings 2' WHERE name = 'Savings'")      # the rest of a type can still change


def test_saving_a_type_without_changing_its_class_is_allowed_while_in_use(conn):
    add_account(conn, "Test account", ASSET, "Savings")
    conn.execute("UPDATE account_types SET class_id = ?, stale_after_days = 40 WHERE name = 'Savings'", (ASSET,))


def test_stale_after_days_must_be_at_least_one(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO account_types (name, class_id, stale_after_days, created_by, updated_by) VALUES ('Zero', 1, 0, (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1))")


def test_type_names_are_unique_ignoring_case(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO account_types (name, class_id, stale_after_days, created_by, updated_by) VALUES ('checking', 1, 35, (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1))")


def test_one_balance_per_account_per_date(conn):
    acct = add_account(conn, "Test account", ASSET, "Checking")
    conn.execute("INSERT INTO balances (account_id, as_of_date, amount_cents, created_by, updated_by) VALUES (?, '2026-01-31', 100000, (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1))", (acct,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO balances (account_id, as_of_date, amount_cents, created_by, updated_by) VALUES (?, '2026-01-31', 5, (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1))", (acct,))


def test_balance_dates_must_be_valid_iso_dates(conn):
    acct = add_account(conn, "Test account", ASSET, "Checking")
    for bad in ("2026-02-30", "01/31/2026", "2026-1-5"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO balances (account_id, as_of_date, amount_cents, created_by, updated_by) VALUES (?, ?, 1, (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1))", (acct, bad))


def test_balances_may_be_negative(conn):
    acct = add_account(conn, "Overdrawn", ASSET, "Checking")
    conn.execute("INSERT INTO balances (account_id, as_of_date, amount_cents, created_by, updated_by) VALUES (?, '2026-01-31', -2500, (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1))", (acct,))


def test_deleting_an_account_deletes_its_balances(conn):
    acct = add_account(conn, "Test account", ASSET, "Checking")
    conn.execute("INSERT INTO balances (account_id, as_of_date, amount_cents, created_by, updated_by) VALUES (?, '2026-01-31', 100, (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1))", (acct,))
    conn.execute("DELETE FROM accounts WHERE id = ?", (acct,))
    assert conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0] == 0


def test_is_open_defaults_to_open_and_only_allows_0_or_1(conn):
    acct = add_account(conn, "Test account", ASSET, "Checking")
    assert conn.execute("SELECT is_open FROM accounts WHERE id = ?", (acct,)).fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE accounts SET is_open = 2 WHERE id = ?", (acct,))


def test_failed_migration_rolls_back(tmp_path):
    folder = tmp_path / "migrations"
    folder.mkdir()
    (folder / "0001_bad.sql").write_text("CREATE TABLE ok (id INTEGER); INSERT INTO missing VALUES (1);")
    connection = db.connect(tmp_path / "x.db")
    with pytest.raises(sqlite3.Error):
        db.migrate(connection, folder)
    tables = {r["name"] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "ok" not in tables
    assert connection.execute("SELECT COUNT(*) FROM sys_schema_migrations").fetchone()[0] == 0
