"""Updating safely: a checked backup before a migration, a refusal to open a newer database, and a command line
that never changes the schema. Synthetic data only."""

import shutil
import sqlite3
from datetime import datetime, timezone

import pytest

from northstar import backup, clock, db, users
from northstar.errors import ValidationError
from northstar.version import VERSION
from northstar.web.app import create_app

FIRST_ONLY = ["0001_initial"]


@pytest.fixture
def older_migrations(tmp_path):
    """A migrations folder with only the first migration, standing in for an older version of the app."""
    folder = tmp_path / "older"
    folder.mkdir()
    shutil.copy(db.MIGRATIONS_DIR / "0001_initial.sql", folder)
    return folder


@pytest.fixture
def fixed_time(monkeypatch):
    moments = iter(datetime(2026, 11, 1, 10, 0, second, tzinfo=timezone.utc) for second in range(60))
    monkeypatch.setattr(clock, "now", lambda: next(moments))


def recorded(path):
    conn = sqlite3.connect(path)
    try:
        return [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
    finally:
        conn.close()


def tables(path):
    conn = sqlite3.connect(path)
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()


def backups_of(path):
    folder = path.parent / "backups"
    return sorted(folder.glob("pre-migration-*.db")) if folder.is_dir() else []


def database_at_an_older_version(tmp_path, older_migrations):
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path, older_migrations)
    assert recorded(path) == FIRST_ONLY
    return path


# -- a backup before a pending migration --

def test_a_pending_migration_is_preceded_by_a_checked_backup_of_the_old_state(tmp_path, older_migrations, fixed_time):
    path = database_at_an_older_version(tmp_path, older_migrations)
    assert db.upgrade(path) == ["0002_login_attempts"]
    [saved] = backups_of(path)
    assert saved.name == f"pre-migration-{VERSION}-20261101-100000.db"
    assert recorded(saved) == FIRST_ONLY and "login_attempts" not in tables(saved)    # the state before
    assert backup.check_database(saved)["migrations"] == 1                           # and it is a valid database
    assert recorded(path) == ["0001_initial", "0002_login_attempts"]                 # while the real one moved on


def test_no_backup_when_nothing_is_pending(tmp_path, fixed_time):
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path)
    assert db.upgrade(path) == []
    assert backups_of(path) == []


def test_no_backup_for_a_new_database_because_there_is_nothing_to_save(tmp_path, fixed_time):
    path = tmp_path / "data" / "northstar.db"
    assert db.upgrade(path) == ["0001_initial", "0002_login_attempts"]
    assert backups_of(path) == [] and not (path.parent / "backups").exists()


def test_the_backup_goes_in_a_backups_folder_beside_the_database_and_nowhere_else(tmp_path, older_migrations, fixed_time):
    path = database_at_an_older_version(tmp_path, older_migrations)
    db.upgrade(path)
    assert [p.name for p in path.parent.iterdir() if p.name != "northstar.db"] == ["backups"]


def test_if_the_backup_fails_nothing_is_migrated(tmp_path, older_migrations, monkeypatch):
    path = database_at_an_older_version(tmp_path, older_migrations)

    def disk_full(*args, **kwargs):
        raise ValidationError("No space left on the device.")

    monkeypatch.setattr(backup, "create_backup", disk_full)
    with pytest.raises(ValidationError, match="No space left"):
        db.upgrade(path)
    assert recorded(path) == FIRST_ONLY and "login_attempts" not in tables(path)


def test_a_failed_migration_is_rolled_back_and_the_backup_is_kept(tmp_path, older_migrations, fixed_time):
    path = database_at_an_older_version(tmp_path, older_migrations)
    broken = tmp_path / "broken"
    shutil.copytree(older_migrations, broken)
    (broken / "0002_bad.sql").write_text("CREATE TABLE half_done (id INTEGER); THIS IS NOT SQL;", encoding="utf-8")
    with pytest.raises(sqlite3.Error):
        db.upgrade(path, broken)
    assert recorded(path) == FIRST_ONLY and "half_done" not in tables(path)
    assert len(backups_of(path)) == 1


# -- how many backups are kept --

def make_backups(folder, count, version="0.1.0"):
    folder.mkdir(parents=True, exist_ok=True)
    made = []
    for number in range(count):
        file = folder / f"pre-migration-{version}-2026010{number + 1}-120000.db"
        file.write_bytes(b"x")
        made.append(file)
    return made


def test_only_the_newest_five_backups_are_kept_after_a_successful_upgrade(tmp_path, older_migrations, fixed_time):
    path = database_at_an_older_version(tmp_path, older_migrations)
    old = make_backups(path.parent / "backups", 6)
    db.upgrade(path)
    kept = backups_of(path)
    assert len(kept) == db.KEEP_BACKUPS == 5
    assert old[0] not in kept and old[1] not in kept            # the two oldest went
    assert any(VERSION in file.name and "20261101" in file.name for file in kept)    # the new one stayed


def test_backups_are_ordered_by_their_time_and_not_by_their_version_name(tmp_path):
    folder = tmp_path / "backups"
    folder.mkdir()
    newest = folder / "pre-migration-0.9.0-20261201-120000.db"
    oldest = folder / "pre-migration-0.10.0-20260101-120000.db"       # "0.10.0" sorts before "0.9.0" as text
    for file in (newest, oldest):
        file.write_bytes(b"x")
    db.prune_backups(folder, keep=1)
    assert newest.exists() and not oldest.exists()


def test_pruning_never_touches_files_that_are_not_pre_migration_backups(tmp_path):
    folder = tmp_path / "backups"
    make_backups(folder, 3)
    mine = [folder / "my-own-backup.db", folder / "notes.txt", folder / "pre-migration-notes.db"]
    for file in mine:
        file.write_bytes(b"x")
    db.prune_backups(folder, keep=1)
    assert all(file.exists() for file in mine)
    assert len([p for p in folder.glob("pre-migration-0.1.0-*.db")]) == 1


def test_a_failed_upgrade_prunes_nothing(tmp_path, older_migrations, monkeypatch):
    """Or a crash loop would replace the good older backups with copies of the same state."""
    path = database_at_an_older_version(tmp_path, older_migrations)
    old = make_backups(path.parent / "backups", 5)
    broken = tmp_path / "broken"
    shutil.copytree(older_migrations, broken)
    (broken / "0002_bad.sql").write_text("THIS IS NOT SQL;", encoding="utf-8")
    with pytest.raises(sqlite3.Error):
        db.upgrade(path, broken)
    assert all(file.exists() for file in old)


# -- a database from a newer version is refused --

def test_a_newer_database_is_refused_unchanged_and_without_a_backup(tmp_path):
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path)
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO schema_migrations (version) VALUES ('0003_from_the_future')")
    conn.commit()
    conn.close()
    before = path.read_bytes()
    with pytest.raises(ValidationError) as refused:
        db.upgrade(path)
    message = str(refused.value)
    assert "newer version" in message and "0003_from_the_future" in message
    assert "restore" in message and "backups" in message
    assert path.read_bytes() == before and backups_of(path) == []


def test_the_app_refuses_to_start_on_a_newer_database(tmp_path):
    path = tmp_path / "web.db"
    db.upgrade(path)
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO schema_migrations (version) VALUES ('0009_from_the_future')")
    conn.commit()
    conn.close()
    with pytest.raises(ValidationError, match="newer version"):
        create_app(path)


def test_a_database_from_before_the_squash_still_opens_and_is_backed_up(tmp_path, older_migrations, fixed_time):
    """It recorded two names this version does not have (0002_users and 0003_user_theme). Their numbers are higher than
    this version's own second migration, so they must be recognised and not mistaken for a newer database."""
    path = database_at_an_older_version(tmp_path, older_migrations)
    conn = sqlite3.connect(path)
    conn.executemany("INSERT INTO schema_migrations (version) VALUES (?)", [("0002_users",), ("0003_user_theme",)])
    conn.commit()
    conn.close()
    assert db.upgrade(path) == ["0002_login_attempts"]
    assert len(backups_of(path)) == 1
    assert db.upgrade(path) == []                                  # and it opens again afterwards


def test_a_database_that_is_behind_is_not_mistaken_for_a_newer_one(tmp_path, older_migrations):
    path = database_at_an_older_version(tmp_path, older_migrations)
    assert db.schema_state(sqlite3.connect(path)) == "behind"


# -- the state of a database --

def test_schema_states(tmp_path, older_migrations):
    empty = sqlite3.connect(tmp_path / "empty.db")
    assert db.schema_state(empty) == "empty"
    path = database_at_an_older_version(tmp_path, older_migrations)
    assert db.schema_state(sqlite3.connect(path)) == "behind"
    current = tmp_path / "current.db"
    db.upgrade(current)
    assert db.schema_state(sqlite3.connect(current)) == "current"


# -- the command line never changes the schema --

PASSWORD = "synthetic-pass-123"


@pytest.fixture
def cli(monkeypatch, tmp_path):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": PASSWORD)

    def run(path, *args):
        monkeypatch.setenv("NORTHSTAR_DB", str(path))
        return users.main(list(args))
    return run


def test_the_command_line_refuses_a_database_that_does_not_exist_and_creates_nothing(cli, tmp_path, capsys):
    target = tmp_path / "data" / "northstar.db"
    assert cli(target, "create", "a@example.com", "A", "--admin") == 1
    assert "Start Northstar" in capsys.readouterr().err
    assert not target.exists() and not target.parent.exists()


def test_the_command_line_refuses_a_database_with_pending_migrations_and_leaves_it_alone(cli, tmp_path, older_migrations, capsys):
    path = database_at_an_older_version(tmp_path, older_migrations)
    before = path.read_bytes()
    assert cli(path, "create", "a@example.com", "A", "--admin") == 1
    assert "Start Northstar" in capsys.readouterr().err
    assert path.read_bytes() == before and backups_of(path) == []


def test_the_command_line_refuses_a_newer_database(cli, tmp_path, capsys):
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path)
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO schema_migrations (version) VALUES ('0009_from_the_future')")
    conn.commit()
    conn.close()
    assert cli(path, "list") == 1
    assert "newer version" in capsys.readouterr().err


def test_the_command_line_works_on_a_current_database(cli, tmp_path, capsys):
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path)
    assert cli(path, "create", "a@example.com", "A", "--admin") == 0
    assert cli(path, "list") == 0
    assert "a@example.com" in capsys.readouterr().out
