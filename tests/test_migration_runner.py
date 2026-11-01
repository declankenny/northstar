"""The migration runner: rebuilding tables safely, one executor for upgrades and the backup check, and the move of
the ledger from schema_migrations to sys_schema_migrations. Synthetic data only."""

import shutil
import sqlite3

import pytest

from northstar import backup, db
from northstar.errors import ValidationError

REAL = sorted(file.stem for file in db.MIGRATIONS_DIR.glob("*.sql"))    # grows with every migration

LEGACY_LEDGER = (
    "CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, "
    "applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')))")

REBUILD_ACCOUNTS = """-- northstar: rebuild
CREATE TABLE accounts_new (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    class_id   INTEGER NOT NULL REFERENCES account_classes (id),
    type_id    INTEGER NOT NULL,
    is_open    INTEGER NOT NULL DEFAULT 1 CHECK (is_open IN (0, 1)),
    notes      TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    colour     TEXT,
    FOREIGN KEY (type_id, class_id) REFERENCES account_types (id, class_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);
INSERT INTO accounts_new (id, name, class_id, type_id, is_open, notes, created_at)
    SELECT id, name, class_id, type_id, is_open, notes, created_at FROM accounts;
DROP TABLE accounts;
ALTER TABLE accounts_new RENAME TO accounts;
CREATE UNIQUE INDEX accounts_name_unique ON accounts (name COLLATE NOCASE);
"""


def folder_with(tmp_path, **extra):
    """The real migrations plus extra ones, named by keyword (the keyword is the file name)."""
    folder = tmp_path / "migrations"
    shutil.copytree(db.MIGRATIONS_DIR, folder, ignore=shutil.ignore_patterns("__pycache__"))
    for name, sql in extra.items():
        (folder / f"{name}.sql").write_text(sql, encoding="utf-8")
    return folder


def fill(conn):
    """One synthetic account with one balance."""
    conn.execute("INSERT INTO accounts (name, class_id, type_id) VALUES ('Test account', 1, 1)")
    conn.execute("INSERT INTO balances (account_id, as_of_date, amount_cents) VALUES (1, '2026-01-31', 12345)")


def counts(conn):
    return [conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("accounts", "balances")]


def foreign_keys(conn):
    return conn.execute("PRAGMA foreign_keys").fetchone()[0]


def objects(conn):
    return {(row[0], row[1]) for row in conn.execute(
        "SELECT type, name FROM sqlite_master WHERE type IN ('table', 'index', 'view', 'trigger') "
        "AND name NOT LIKE 'sqlite_%'")}


def v01_database(path):
    """A database exactly as the released 0.1 code leaves it: the ledger is schema_migrations."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, "
                 "applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')))")
    for name in ("0001_initial", "0002_login_attempts"):
        sql = (db.MIGRATIONS_DIR / f"{name}.sql").read_text(encoding="utf-8")
        conn.executescript(f"BEGIN;\n{sql}\nINSERT INTO schema_migrations (version) VALUES ('{name}');\nCOMMIT;")
    fill(conn)
    conn.close()
    return path


def ledgers(path):
    conn = sqlite3.connect(path)
    try:
        return {name: [row[0] for row in conn.execute(f"SELECT version FROM {name} ORDER BY version")]
                for (name,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE name IN ('schema_migrations', 'sys_schema_migrations')")}
    finally:
        conn.close()


def backups_of(path):
    folder = path.parent / "backups"
    return sorted(folder.glob("pre-migration-*.db")) if folder.is_dir() else []


# -- rebuilding a table --

@pytest.fixture
def migrated(tmp_path):
    conn = db.connect(tmp_path / "x.db")
    db.migrate(conn)
    fill(conn)
    yield conn
    conn.close()


def test_a_rebuild_migration_keeps_every_row_and_does_not_cascade_to_the_children(tmp_path, migrated):
    """Dropping accounts with foreign keys on would delete its balances. Rebuilding is only safe with them off."""
    folder = folder_with(tmp_path, **{"0004_accounts_colour": REBUILD_ACCOUNTS})
    assert db.migrate(migrated, folder) == ["0004_accounts_colour"]
    assert counts(migrated) == [1, 1]
    assert "colour" in {row["name"] for row in migrated.execute("PRAGMA table_info(accounts)")}
    assert foreign_keys(migrated) == 1
    assert migrated.execute("SELECT COUNT(*) FROM sys_schema_migrations").fetchone()[0] == len(REAL) + 1


def test_a_migration_without_the_marker_still_runs_with_foreign_keys_on(tmp_path, migrated):
    folder = folder_with(tmp_path, **{"0004_probe": "CREATE TABLE probe (flag INTEGER);\n"
                                                     "INSERT INTO probe SELECT foreign_keys FROM pragma_foreign_keys;"})
    db.migrate(migrated, folder)
    assert migrated.execute("SELECT flag FROM probe").fetchone()[0] == 1


def test_a_rebuild_migration_runs_with_foreign_keys_off(tmp_path, migrated):
    folder = folder_with(tmp_path, **{"0004_probe": "-- northstar: rebuild\nCREATE TABLE probe (flag INTEGER);\n"
                                                     "INSERT INTO probe SELECT foreign_keys FROM pragma_foreign_keys;"})
    db.migrate(migrated, folder)
    assert migrated.execute("SELECT flag FROM probe").fetchone()[0] == 0
    assert foreign_keys(migrated) == 1


def test_a_rebuild_that_fails_while_copying_is_rolled_back_whole(tmp_path, migrated):
    broken = REBUILD_ACCOUNTS.replace("ALTER TABLE accounts_new RENAME TO accounts;",
                                      "INSERT INTO nowhere VALUES (1);")
    folder = folder_with(tmp_path, **{"0004_broken": broken})
    before = objects(migrated)
    with pytest.raises(sqlite3.Error):
        db.migrate(migrated, folder)
    assert counts(migrated) == [1, 1] and objects(migrated) == before     # accounts is back, accounts_new is gone
    assert migrated.execute("SELECT COUNT(*) FROM sys_schema_migrations").fetchone()[0] == len(REAL)
    assert foreign_keys(migrated) == 1 and not migrated.in_transaction


def test_a_rebuild_that_loses_rows_other_tables_point_at_is_refused_at_validation(tmp_path, migrated):
    lossy = REBUILD_ACCOUNTS.replace("FROM accounts;", "FROM accounts WHERE 0;")
    folder = folder_with(tmp_path, **{"0004_lossy": lossy})
    with pytest.raises(ValidationError, match="foreign key"):
        db.migrate(migrated, folder)
    assert counts(migrated) == [1, 1]
    assert "colour" not in {row["name"] for row in migrated.execute("PRAGMA table_info(accounts)")}
    assert migrated.execute("SELECT COUNT(*) FROM sys_schema_migrations").fetchone()[0] == len(REAL)
    assert foreign_keys(migrated) == 1 and not migrated.in_transaction


def test_foreign_keys_stay_off_if_they_were_off_and_on_if_they_were_on(tmp_path, migrated):
    folder = folder_with(tmp_path, **{"0004_accounts_colour": REBUILD_ACCOUNTS})
    migrated.execute("PRAGMA foreign_keys = OFF")
    db.migrate(migrated, folder)
    assert foreign_keys(migrated) == 0


def test_migrations_cannot_start_inside_a_transaction(tmp_path, migrated):
    """PRAGMA foreign_keys does nothing inside one, so a rebuild there would silently run with them on."""
    folder = folder_with(tmp_path, **{"0004_accounts_colour": REBUILD_ACCOUNTS})
    migrated.execute("BEGIN")
    with pytest.raises(ValidationError, match="transaction"):
        db.migrate(migrated, folder)
    migrated.execute("ROLLBACK")
    assert counts(migrated) == [1, 1]


INDEX_AND_VIEW = ("CREATE INDEX balances_note ON balances (note);\n"
                  "CREATE VIEW big_balances AS SELECT id FROM balances WHERE amount_cents > 100;")
REBUILD_BALANCES = """-- northstar: rebuild
DROP VIEW big_balances;
CREATE TABLE balances_new (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
    as_of_date TEXT NOT NULL CHECK (date(as_of_date) IS as_of_date),
    amount_cents INTEGER NOT NULL, note TEXT, source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    UNIQUE (account_id, as_of_date));
INSERT INTO balances_new SELECT * FROM balances;
DROP TABLE balances;
ALTER TABLE balances_new RENAME TO balances;
"""


def test_a_rebuild_that_keeps_its_indexes_and_views_is_accepted(tmp_path, migrated):
    folder = folder_with(tmp_path, **{"0004_index": INDEX_AND_VIEW,
                                      "0005_rebuild": REBUILD_BALANCES + INDEX_AND_VIEW})
    db.migrate(migrated, folder)
    assert {("index", "balances_note"), ("view", "big_balances")} <= objects(migrated)


def test_a_rebuild_that_silently_loses_an_index_or_a_view_is_refused(tmp_path, migrated):
    """Dropping a table takes its indexes with it, and a view over it stops working. Both are easy to forget."""
    folder = folder_with(tmp_path, **{"0004_index": INDEX_AND_VIEW, "0005_rebuild": REBUILD_BALANCES})
    db.migrate(migrated, folder_with(tmp_path / "first", **{"0004_index": INDEX_AND_VIEW}))
    before = objects(migrated)
    with pytest.raises(ValidationError, match="balances_note"):
        db.migrate(migrated, folder)
    assert objects(migrated) == before and counts(migrated) == [1, 1]


# -- the ledger moves from schema_migrations to sys_schema_migrations --

def test_a_new_database_gets_only_the_new_ledger(tmp_path):
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path)
    assert list(ledgers(path)) == ["sys_schema_migrations"]


def test_a_v0_1_database_is_behind_because_its_ledger_must_move(tmp_path):
    path = v01_database(tmp_path / "northstar.db")
    conn = sqlite3.connect(path)
    assert db.schema_state(conn) == "behind"
    with pytest.raises(ValidationError, match="Start Northstar"):
        db.require_current(conn, path)
    conn.close()


def test_upgrading_a_v0_1_database_backs_it_up_first_then_renames_the_ledger_keeping_its_history(tmp_path):
    path = v01_database(tmp_path / "data" / "northstar.db")
    original = sqlite3.connect(path).execute("SELECT version, applied_at FROM schema_migrations").fetchall()
    assert db.upgrade(path) == REAL[2:]                            # only the migrations after 0002 ran, and the ledger moved
    [saved] = backups_of(path)
    assert list(ledgers(saved)) == ["schema_migrations"]            # the backup is the state before the rename
    assert list(ledgers(path)) == ["sys_schema_migrations"]
    moved = sqlite3.connect(path).execute("SELECT version, applied_at FROM sys_schema_migrations").fetchall()
    assert sorted(moved)[:len(original)] == sorted(original)                # the old rows came across unchanged, then the new migration
    conn = db.connect(path)
    assert counts(conn) == [1, 1] and db.schema_state(conn) == "current"
    conn.close()
    assert db.upgrade(path) == [] and len(backups_of(path)) == 1    # and the next start does nothing


def test_if_the_backup_fails_the_ledger_is_not_renamed(tmp_path, monkeypatch):
    path = v01_database(tmp_path / "data" / "northstar.db")

    def disk_full(*args, **kwargs):
        raise ValidationError("No space left on the device.")

    monkeypatch.setattr(backup, "create_backup", disk_full)
    with pytest.raises(ValidationError, match="No space left"):
        db.upgrade(path)
    assert list(ledgers(path)) == ["schema_migrations"]


def test_a_pre_upgrade_backup_still_validates_and_restores(tmp_path):
    path = v01_database(tmp_path / "data" / "northstar.db")
    db.upgrade(path)
    [saved] = backups_of(path)
    assert backup.check_database(saved)["migrations"] == 2
    target = tmp_path / "restored" / "northstar.db"
    backup.restore_backup(saved, target)
    assert db.upgrade(target) == REAL[2:] and list(ledgers(target)) == ["sys_schema_migrations"]


def test_a_backup_validates_at_each_migration_boundary(tmp_path):
    first_only = tmp_path / "first"
    first_only.mkdir()
    shutil.copy(db.MIGRATIONS_DIR / "0001_initial.sql", first_only)
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path, first_only)
    assert backup.create_backup(path, tmp_path / "at-1.db")["migrations"] == 1
    db.upgrade(path)
    assert backup.create_backup(path, tmp_path / "at-2.db")["migrations"] == len(REAL)


def test_a_backup_missing_a_required_table_is_still_refused_under_the_new_ledger(tmp_path):
    path = tmp_path / "northstar.db"
    db.upgrade(path)
    sqlite3.connect(path).execute("DROP TABLE login_attempts").connection.commit()
    with pytest.raises(ValidationError, match="not a valid Northstar database"):
        backup.check_database(path)


def test_a_file_with_neither_ledger_is_not_a_northstar_database(tmp_path):
    path = tmp_path / "other.db"
    sqlite3.connect(path).execute("CREATE TABLE accounts (id INTEGER)").connection.commit()
    with pytest.raises(ValidationError, match="not a valid Northstar database"):
        backup.check_database(path)


def test_the_backup_check_replays_migrations_through_the_same_executor_as_upgrades(monkeypatch):
    calls = []
    real = db.migrate

    def spy(conn, migrations_dir=db.MIGRATIONS_DIR, only=None):
        calls.append(only)
        return real(conn, migrations_dir, only)

    monkeypatch.setattr(db, "migrate", spy)
    assert "login_attempts" in backup._tables_for({"0001_initial", "0002_login_attempts"})
    assert calls == [{"0001_initial", "0002_login_attempts"}]


def test_the_replay_for_the_backup_check_counts_neither_ledger_as_a_required_table():
    assert backup._tables_for({"0001_initial"}).isdisjoint({"schema_migrations", "sys_schema_migrations"})


def test_the_executor_replays_only_the_migrations_it_is_given(tmp_path):
    conn = db.connect(":memory:")
    assert db.migrate(conn, only={"0001_initial"}) == ["0001_initial"]
    names = {name for _, name in objects(conn)}
    assert "sessions" in names and "login_attempts" not in names


# -- an app rollback leaves a stray empty old ledger --

def old_code_starts(path):
    """What the released 0.1 migrate() does on every start: create schema_migrations if it is missing, read it, and
    run every file it finds unrecorded. Against a database migrated by newer code that is all of them, and they fail."""
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute(LEGACY_LEDGER.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS"))
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    try:
        for file in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
            if file.stem not in done:
                conn.executescript("BEGIN;\n" + file.read_text(encoding="utf-8") + "\nCOMMIT;")
    except sqlite3.Error:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
    finally:
        conn.close()


def test_after_an_app_rollback_the_stray_empty_ledger_is_removed_and_nothing_else_changes(tmp_path):
    path = v01_database(tmp_path / "data" / "northstar.db")
    db.upgrade(path)
    old_code_starts(path)
    assert ledgers(path)["schema_migrations"] == []               # the stray, left by the old code
    assert db.upgrade(path) == []
    assert list(ledgers(path)) == ["sys_schema_migrations"]
    assert len(backups_of(path)) == 1                             # recovery is not a migration, no new backup
    conn = db.connect(path)
    assert counts(conn) == [1, 1]
    conn.close()


def test_a_stray_ledger_alone_does_not_stop_the_command_line_tools(tmp_path):
    path = v01_database(tmp_path / "data" / "northstar.db")
    db.upgrade(path)
    old_code_starts(path)
    conn = sqlite3.connect(path)
    assert db.schema_state(conn) == "current"
    db.require_current(conn, path)
    conn.close()


def stray(path, *, version=None):
    conn = sqlite3.connect(path)
    conn.execute(LEGACY_LEDGER)
    if version:
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
    conn.commit()
    conn.close()


def test_a_database_from_a_newer_version_with_a_stray_ledger_is_refused_without_changing_anything(tmp_path):
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path)
    stray(path)
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO sys_schema_migrations (version) VALUES ('0009_from_the_future')")
    conn.commit()
    conn.close()
    before = path.read_bytes()
    with pytest.raises(ValidationError, match="newer version"):
        db.upgrade(path)
    assert path.read_bytes() == before and backups_of(path) == []


def two_ledgers(path, *, new_rows, old_rows):
    conn = sqlite3.connect(path)
    conn.execute(LEGACY_LEDGER)
    conn.execute("DELETE FROM sys_schema_migrations")
    for version in new_rows:
        conn.execute("INSERT INTO sys_schema_migrations (version) VALUES (?)", (version,))
    for version in old_rows:
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
    conn.commit()
    conn.close()


@pytest.mark.parametrize("new_rows, old_rows", [
    ([], []),                                                     # two empty ledgers
    (["0001_initial", "0002_login_attempts"], ["0001_initial"]),  # two populated ledgers
    ([], ["0001_initial", "0002_login_attempts"]),                # the history is in the old one only
])
def test_ledgers_that_cannot_be_reconciled_are_refused_and_nothing_is_deleted(tmp_path, new_rows, old_rows):
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path)
    two_ledgers(path, new_rows=new_rows, old_rows=old_rows)
    before = path.read_bytes()
    with pytest.raises(ValidationError, match="migration ledger"):
        db.upgrade(path)
    assert path.read_bytes() == before and backups_of(path) == []


@pytest.mark.parametrize("table", ["schema_migrations", "sys_schema_migrations"])
def test_a_malformed_ledger_is_refused_and_nothing_is_deleted(tmp_path, table):
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path)
    conn = sqlite3.connect(path)
    conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute(f"CREATE TABLE {table} (name TEXT, ran_at TEXT)")
    conn.commit()
    conn.close()
    before = path.read_bytes()
    with pytest.raises(ValidationError, match="migration ledger"):
        db.upgrade(path)
    assert path.read_bytes() == before


class FailsToCreateTheLedger(sqlite3.Connection):
    """A connection that fails at the last step of preparing the ledger, after the earlier steps have run."""

    def execute(self, sql, *args):
        if sql.startswith("CREATE TABLE IF NOT EXISTS sys_schema_migrations"):
            raise sqlite3.OperationalError("disk I/O error")
        return super().execute(sql, *args)


def test_a_failure_while_removing_the_stray_ledger_leaves_everything_as_it_was(tmp_path, monkeypatch):
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path)
    stray(path)
    before = path.read_bytes()

    def connect(target):
        conn = sqlite3.connect(target, isolation_level=None, factory=FailsToCreateTheLedger)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    monkeypatch.setattr(db, "connect", connect)
    with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
        db.upgrade(path)
    assert path.read_bytes() == before                            # the drop was rolled back with the rest
    assert ledgers(path)["schema_migrations"] == []


def test_a_failure_while_renaming_the_ledger_leaves_the_old_one_whole(tmp_path):
    path = v01_database(tmp_path / "data" / "northstar.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE VIEW broken AS SELECT * FROM missing_table")    # a rename re-parses every view and fails
    conn.commit()
    conn.close()
    with pytest.raises(sqlite3.Error):
        db.upgrade(path)
    assert ledgers(path) == {"schema_migrations": ["0001_initial", "0002_login_attempts"]}
    assert len(backups_of(path)) == 1                              # the backup came first and is kept
