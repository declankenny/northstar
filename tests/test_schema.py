import sqlite3

import pytest

from northstar import db, users

from conftest import add_account, type_id

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
        "0001_initial", "0002_login_attempts", "0003_unique_account_names"]
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'login_attempts'").fetchone()[0] == 1
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    assert {"email", "password_hash", "is_admin", "theme"} <= columns
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'sessions'").fetchone()[0] == 1
    users.create_user(conn, "a@example.com", "Test A", "synthetic-pass-123")
    assert conn.execute("SELECT theme FROM users").fetchone()[0] == "dark"       # the default


def test_a_database_that_recorded_the_old_split_migrations_still_opens(conn):
    """The initial migration used to be three files. A database that applied all three has their names
    recorded, and the one remaining file must be treated as applied, with nothing run again."""
    conn.executemany("INSERT INTO sys_schema_migrations (version) VALUES (?)", [("0002_users",), ("0003_user_theme",)])
    assert db.migrate(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_account_with_type_from_the_other_class_is_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError):
        add_account(conn, "Test mortgage", ASSET, "Mortgage")


def test_changing_class_and_type_together_works(conn):
    acct = add_account(conn, "Test account", ASSET, "Checking")
    conn.execute(
        "UPDATE accounts SET class_id = ?, type_id = ? WHERE id = ?",
        (LIABILITY, type_id(conn, "Loan"), acct),
    )


def test_changing_class_alone_is_rejected(conn):
    acct = add_account(conn, "Test account", ASSET, "Checking")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE accounts SET class_id = ? WHERE id = ?", (LIABILITY, acct))


def test_changing_type_within_class_works_and_across_class_is_rejected(conn):
    acct = add_account(conn, "Test account", ASSET, "Checking")
    conn.execute("UPDATE accounts SET type_id = ? WHERE id = ?", (type_id(conn, "Savings"), acct))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE accounts SET type_id = ? WHERE id = ?", (type_id(conn, "Loan"), acct))


def test_type_in_use_cannot_be_deleted_but_unused_can(conn):
    add_account(conn, "Test account", ASSET, "Checking")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM account_types WHERE name = 'Checking'")
    conn.execute("DELETE FROM account_types WHERE name = 'Savings'")


def test_type_class_cannot_change_while_in_use(conn):
    add_account(conn, "Test account", ASSET, "Checking")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE account_types SET class_id = ? WHERE name = 'Checking'", (LIABILITY,))
    # An unused type can change class.
    conn.execute("UPDATE account_types SET class_id = ? WHERE name = 'Savings'", (LIABILITY,))


def test_stale_after_days_must_be_at_least_one(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO account_types (name, class_id, stale_after_days) VALUES ('Zero', 1, 0)")


def test_type_names_are_unique_ignoring_case(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO account_types (name, class_id, stale_after_days) VALUES ('checking', 1, 35)")


def test_one_balance_per_account_per_date(conn):
    acct = add_account(conn, "Test account", ASSET, "Checking")
    conn.execute("INSERT INTO balances (account_id, as_of_date, amount_cents) VALUES (?, '2026-01-31', 100000)", (acct,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO balances (account_id, as_of_date, amount_cents) VALUES (?, '2026-01-31', 5)", (acct,))


def test_balance_dates_must_be_valid_iso_dates(conn):
    acct = add_account(conn, "Test account", ASSET, "Checking")
    for bad in ("2026-02-30", "01/31/2026", "2026-1-5"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO balances (account_id, as_of_date, amount_cents) VALUES (?, ?, 1)", (acct, bad))


def test_balances_may_be_negative(conn):
    acct = add_account(conn, "Overdrawn", ASSET, "Checking")
    conn.execute("INSERT INTO balances (account_id, as_of_date, amount_cents) VALUES (?, '2026-01-31', -2500)", (acct,))


def test_deleting_an_account_deletes_its_balances(conn):
    acct = add_account(conn, "Test account", ASSET, "Checking")
    conn.execute("INSERT INTO balances (account_id, as_of_date, amount_cents) VALUES (?, '2026-01-31', 100)", (acct,))
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
