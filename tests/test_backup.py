"""Backup and restore. Synthetic data only.

The main test is the round trip: back up the hand-calculation household, lose the database,
restore it, and check that net worth comes out exactly as the hand calculation says.
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from northstar import backup, db, networth
from northstar.errors import ValidationError
from northstar.web.app import create_app

# The hand-calculation household and its expected month-end numbers live in the net worth tests.
from test_networth import MONTH_ENDS, TODAY, household  # noqa: F401  (a pytest fixture)

from conftest import add_account, add_balance, sign_in


def path_of(conn) -> Path:
    return Path(conn.execute("PRAGMA database_list").fetchone()["file"])


def month_rows(conn):
    return [(r["date"], r["assets"], r["liabilities"], r["net_worth"], r["partial"])
            for r in networth.net_worth_by_month(conn, TODAY)]


def tamper_free_copy_exists(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


# -- the round trip, which is the acceptance test --

def test_backup_then_restore_gives_back_the_hand_calculated_net_worth(conn, household, tmp_path):
    db_file = path_of(conn)
    backup_file = tmp_path / "backups" / "northstar.bak"
    backup_file.parent.mkdir()
    counts = backup.create_backup(db_file, backup_file)
    assert counts["accounts"] == 6 and counts["balances"] == 14

    conn.close()
    db_file.unlink()                                       # the disaster: the database is gone
    restored = backup.restore_backup(backup_file, db_file)
    assert (restored["accounts"], restored["balances"]) == (6, 14)

    again = db.connect(db_file)
    try:
        assert month_rows(again) == MONTH_ENDS             # the same numbers, to the cent
        assert db.migrate(again) == []                     # the migration record came back too
    finally:
        again.close()


def test_the_restored_database_still_enforces_every_rule(conn, household, tmp_path):
    db_file = path_of(conn)
    backup.create_backup(db_file, tmp_path / "b.bak")
    conn.close()
    db_file.unlink()
    backup.restore_backup(tmp_path / "b.bak", db_file)
    restored = db.connect(db_file)
    try:
        assert restored.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):        # a type from the other class
            add_account(restored, "Wrong", 1, "Mortgage")
        with pytest.raises(sqlite3.IntegrityError):        # a date that is not a date
            add_balance(restored, household["checking"], "01/31/2026", 1)
        with pytest.raises(sqlite3.IntegrityError):        # a second balance on one date
            add_balance(restored, household["checking"], "2026-01-31", 1)
    finally:
        restored.close()


# -- backing up while the app is using the database --

def test_backup_includes_committed_changes_and_leaves_out_uncommitted_ones(conn, household, tmp_path):
    db_file = path_of(conn)
    add_balance(conn, household["checking"], "2026-07-01", 111111)           # committed
    other = db.connect(db_file)
    other.execute("BEGIN")
    other.execute("INSERT INTO balances (account_id, as_of_date, amount_cents) VALUES (?, '2026-08-01', 222222)",
                  (household["checking"],))                                   # not committed yet
    try:
        counts = backup.create_backup(db_file, tmp_path / "live.bak")
    finally:
        other.execute("ROLLBACK")
        other.close()
    assert counts["balances"] == 15                          # 14 seeded plus the committed one only


def test_backup_does_not_change_the_original(conn, household, tmp_path):
    before = month_rows(conn)
    backup.create_backup(path_of(conn), tmp_path / "b.bak")
    assert month_rows(conn) == before and conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0] == 14


def test_backup_of_a_brand_new_database(conn, tmp_path):
    counts = backup.create_backup(path_of(conn), tmp_path / "empty.bak")
    assert (counts["accounts"], counts["balances"]) == (0, 0) and counts["migrations"] == len(list(db.MIGRATIONS_DIR.glob("*.sql")))


# -- backups are refused when they would hurt --

def test_backup_refuses_to_overwrite_an_existing_file(conn, household, tmp_path):
    target = tmp_path / "keep.bak"
    target.write_bytes(b"precious")
    with pytest.raises(ValidationError, match="already exists"):
        backup.create_backup(path_of(conn), target)
    assert target.read_bytes() == b"precious"


def test_backup_of_a_missing_database_does_not_create_one(tmp_path):
    missing = tmp_path / "nope.db"
    with pytest.raises(ValidationError, match="no database"):
        backup.create_backup(missing, tmp_path / "x.bak")
    assert not missing.exists() and not (tmp_path / "x.bak").exists()


def test_backup_into_a_missing_folder_is_refused(conn, tmp_path):
    with pytest.raises(ValidationError, match="does not exist"):
        backup.create_backup(path_of(conn), tmp_path / "no_such_folder" / "x.bak")


def test_a_failed_backup_leaves_no_files_behind(conn, household, tmp_path, monkeypatch):
    folder = tmp_path / "out"
    folder.mkdir()
    monkeypatch.setattr(backup, "check_database", lambda path: (_ for _ in ()).throw(ValidationError("boom")))
    with pytest.raises(ValidationError, match="boom"):
        backup.create_backup(path_of(conn), folder / "x.bak")
    assert tamper_free_copy_exists(folder) == []             # no x.bak and no .partial file


# -- restores are refused when they would hurt --

def make_backup(conn, tmp_path, name="b.bak") -> Path:
    backup.create_backup(path_of(conn), tmp_path / name)
    return tmp_path / name


def test_restore_refuses_a_file_that_is_not_a_database(conn, household, tmp_path):
    garbage = tmp_path / "garbage.bak"
    garbage.write_bytes(b"this is not a database at all" * 100)
    target = tmp_path / "restored.db"
    target.write_bytes(b"existing")
    with pytest.raises(ValidationError, match="not a valid Northstar database"):
        backup.restore_backup(garbage, target, replace=True)
    assert target.read_bytes() == b"existing"


def test_restore_refuses_a_truncated_backup(conn, household, tmp_path):
    good = make_backup(conn, tmp_path)
    broken = tmp_path / "truncated.bak"
    broken.write_bytes(good.read_bytes()[:3000])
    target = tmp_path / "restored.db"
    with pytest.raises(ValidationError):
        backup.restore_backup(broken, target)
    assert not target.exists()


def test_restore_refuses_a_database_from_something_else(tmp_path):
    other = tmp_path / "other.db"
    sqlite3.connect(other).execute("CREATE TABLE notes (id INTEGER)").connection.commit()
    with pytest.raises(ValidationError, match="not a valid Northstar database"):
        backup.restore_backup(other, tmp_path / "restored.db")


def test_restore_refuses_a_missing_backup(tmp_path):
    with pytest.raises(ValidationError, match="no file"):
        backup.restore_backup(tmp_path / "missing.bak", tmp_path / "restored.db")


def test_restore_refuses_to_overwrite_without_replace(conn, household, tmp_path):
    good = make_backup(conn, tmp_path)
    live = path_of(conn)
    add_account(conn, "Added after the backup", 1, "Checking")
    conn.close()
    size_before = live.stat().st_size
    with pytest.raises(ValidationError, match="--replace"):
        backup.restore_backup(good, live)
    assert live.stat().st_size == size_before
    assert tamper_free_copy_exists(tmp_path) == sorted(["b.bak", "test.db"])


def test_restore_onto_itself_is_refused(conn, household, tmp_path):
    good = make_backup(conn, tmp_path)
    with pytest.raises(ValidationError, match="same file"):
        backup.restore_backup(good, good, replace=True)


def test_replace_moves_the_old_database_aside_and_never_deletes_it(conn, household, tmp_path):
    good = make_backup(conn, tmp_path)
    live = path_of(conn)
    add_account(conn, "Added after the backup", 1, "Checking")
    conn.close()
    result = backup.restore_backup(good, live, replace=True)
    assert result["accounts"] == 6                           # back to the backed-up state
    aside = Path(result["moved_aside"][0])
    assert aside.exists() and ".before-restore-" in aside.name
    old = sqlite3.connect(aside)
    try:
        assert old.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 7   # the extra account is safe
    finally:
        old.close()


def test_leftover_journal_files_are_moved_aside_so_they_cannot_corrupt_the_restore(conn, household, tmp_path):
    good = make_backup(conn, tmp_path)
    live = path_of(conn)
    conn.close()
    stale = live.with_name(live.name + "-journal")
    stale.write_bytes(b"stale journal from an older database")
    result = backup.restore_backup(good, live, replace=True)
    assert not stale.exists()
    assert any("-journal.before-restore-" in p for p in result["moved_aside"])   # kept, not deleted
    check = db.connect(live)
    try:
        assert month_rows(check) == MONTH_ENDS
    finally:
        check.close()


def test_restore_into_a_new_folder_creates_it(conn, household, tmp_path):
    good = make_backup(conn, tmp_path)
    target = tmp_path / "fresh" / "data" / "northstar.db"
    backup.restore_backup(good, target)
    assert target.is_file()


def test_a_failed_restore_puts_everything_back(conn, household, tmp_path, monkeypatch):
    good = make_backup(conn, tmp_path)
    live = path_of(conn)
    conn.close()
    original = live.read_bytes()
    real_replace = backup.os.replace
    calls = []

    def failing_replace(src, dst):
        calls.append((Path(src).name, Path(dst).name))
        if str(src).endswith(".partial"):                    # the last step, putting the copy in place
            raise PermissionError("in use")
        return real_replace(src, dst)

    monkeypatch.setattr(backup.os, "replace", failing_replace)
    with pytest.raises(ValidationError, match="in use"):
        backup.restore_backup(good, live, replace=True)
    assert live.read_bytes() == original                     # the old database is exactly where it was
    assert not [p for p in tmp_path.iterdir() if ".partial" in p.name or ".before-restore-" in p.name]


# -- the command line --

def test_command_line_round_trip_reports_counts_only(conn, household, tmp_path, monkeypatch, capsys):
    db_file = path_of(conn)
    monkeypatch.setenv("NORTHSTAR_DB", str(db_file))
    target = tmp_path / "cli.bak"
    assert backup.main(["create", str(target)]) == 0
    out = capsys.readouterr().out
    assert "6 accounts, 14 balances, integrity ok" in out
    # Real-data hygiene: nothing about names or amounts is ever printed.
    for secret in ("Checking", "Mortgage", "House", "1,200", "120000", "400000", "40000000"):
        assert secret not in out
    conn.close()
    db_file.unlink()
    assert backup.main(["restore", str(target)]) == 0
    assert "Restored" in capsys.readouterr().out
    assert db_file.is_file()


def test_command_line_errors_exit_with_a_message_not_a_traceback(conn, household, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NORTHSTAR_DB", str(path_of(conn)))
    existing = tmp_path / "exists.bak"
    existing.write_bytes(b"x")
    assert backup.main(["create", str(existing)]) == 1
    assert "Error:" in capsys.readouterr().err and existing.read_bytes() == b"x"
    assert backup.main(["restore", str(tmp_path / "missing.bak")]) == 1
    assert "Error:" in capsys.readouterr().err


def test_command_line_restore_without_replace_leaves_the_live_database_alone(
        conn, household, tmp_path, monkeypatch, capsys):
    live = path_of(conn)
    monkeypatch.setenv("NORTHSTAR_DB", str(live))
    good = make_backup(conn, tmp_path)
    conn.close()
    assert backup.main(["restore", str(good)]) == 1
    assert "--replace" in capsys.readouterr().err


# -- data survives restarting the app --

def test_data_survives_restarting_the_app(tmp_path):
    db_file = tmp_path / "app.db"
    first = sign_in(TestClient(create_app(db_file)))
    first.post("/accounts", data={"class": "asset", "name": "Survivor", "type_id": "1", "notes": ""})
    second = TestClient(create_app(db_file))                 # a fresh app on the same file
    second.cookies.set("northstar_session", first.cookies["northstar_session"])   # sessions survive too
    assert "Survivor" in second.get("/accounts").text
