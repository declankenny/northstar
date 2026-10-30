import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from northstar import sessions, users
from northstar.errors import ValidationError

PASSWORD = "synthetic-pass-123"


def make_user(conn, email="a@example.com", admin=False):
    return users.create_user(conn, email, "Test A", PASSWORD, is_admin=admin)


def test_password_round_trip_and_wrong_password():
    stored = users.hash_password(PASSWORD)
    assert stored != PASSWORD and PASSWORD not in stored
    assert users.verify_password(PASSWORD, stored)
    assert not users.verify_password("something else entirely", stored)
    assert not users.verify_password(PASSWORD, "garbage")


def test_same_password_hashes_differently():
    assert users.hash_password(PASSWORD) != users.hash_password(PASSWORD)


def test_create_user_stores_admin_flag_and_normalizes_email(conn):
    make_user(conn, "  Admin@Example.COM ", admin=True)
    make_user(conn, "b@example.com")
    rows = {r["email"]: r["is_admin"] for r in users.list_users(conn)}
    assert rows == {"admin@example.com": 1, "b@example.com": 0}


def test_duplicate_email_is_refused_ignoring_case(conn):
    make_user(conn, "a@example.com")
    with pytest.raises(ValidationError, match="already exists"):
        make_user(conn, "A@EXAMPLE.COM")


@pytest.mark.parametrize("email", ["", "no-at-sign", "a b@example.com", "@example.com", "a@"])
def test_bad_email_is_refused(conn, email):
    with pytest.raises(ValidationError, match="valid email"):
        make_user(conn, email)


def test_short_password_is_refused(conn):
    with pytest.raises(ValidationError, match="at least 12"):
        users.create_user(conn, "a@example.com", "A", "short")


def test_is_admin_must_be_zero_or_one(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO users (email, display_name, password_hash, is_admin) VALUES ('x@e.com', 'X', 'h', 2)")


def test_authenticate(conn):
    make_user(conn)
    assert users.authenticate(conn, "A@example.com", PASSWORD)["email"] == "a@example.com"
    assert users.authenticate(conn, "a@example.com", "wrong-password-123") is None
    assert users.authenticate(conn, "nobody@example.com", PASSWORD) is None


def test_set_password_changes_it_and_signs_the_user_out(conn):
    uid = make_user(conn)
    token = sessions.create_session(conn, uid)
    users.set_password(conn, "a@example.com", "another-password-456")
    assert users.authenticate(conn, "a@example.com", PASSWORD) is None
    assert users.authenticate(conn, "a@example.com", "another-password-456")
    assert sessions.user_for_token(conn, token) is None


def test_session_lifecycle(conn):
    uid = make_user(conn)
    token = sessions.create_session(conn, uid)
    assert sessions.user_for_token(conn, token)["id"] == uid
    assert sessions.user_for_token(conn, "not-a-token") is None
    assert sessions.user_for_token(conn, None) is None
    sessions.end_session(conn, token)
    assert sessions.user_for_token(conn, token) is None


def test_the_token_itself_is_not_stored(conn):
    token = sessions.create_session(conn, make_user(conn))
    assert conn.execute("SELECT COUNT(*) FROM sessions WHERE token_hash = ?", (token,)).fetchone()[0] == 0


def test_session_expires_and_expired_ones_are_purged(conn):
    uid = make_user(conn)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    token = sessions.create_session(conn, uid, now=start)
    assert sessions.user_for_token(conn, token, now=start + timedelta(days=29))
    assert sessions.user_for_token(conn, token, now=start + timedelta(days=31)) is None
    sessions.create_session(conn, uid, now=start + timedelta(days=31))
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


def test_deleting_a_user_deletes_their_sessions(conn):
    uid = make_user(conn)
    sessions.create_session(conn, uid)
    conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_command_line_creates_a_user_and_never_prints_the_password(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NORTHSTAR_DB", str(tmp_path / "cli.db"))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": PASSWORD)
    assert users.main(["create", "Admin@Example.com", "Admin Person", "--admin"]) == 0
    assert users.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "admin@example.com" in out and "admin" in out and PASSWORD not in out
    assert users.main(["create", "admin@example.com", "Again"]) == 1       # duplicate: error, not a crash


def test_command_line_refuses_mismatched_passwords(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NORTHSTAR_DB", str(tmp_path / "cli.db"))
    answers = iter([PASSWORD, "a-different-password"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert users.main(["create", "a@example.com", "A"]) == 1
    assert "did not match" in capsys.readouterr().err


def test_users_migration_applies_to_a_populated_database_without_touching_it(tmp_path):
    """The 0002 migration on top of an existing 0001 database that already holds (synthetic) data."""
    from northstar import db
    from conftest import add_account, add_balance
    old = tmp_path / "migrations"
    old.mkdir()
    (old / "0001_initial.sql").write_text((db.MIGRATIONS_DIR / "0001_initial.sql").read_text(encoding="utf-8"), encoding="utf-8")
    conn = db.connect(tmp_path / "copy.db")
    assert db.migrate(conn, old) == ["0001_initial"]
    account = add_account(conn, "Test checking", 1, "Checking")
    add_balance(conn, account, "2026-01-31", 123456)
    assert db.migrate(conn) == ["0002_users", "0003_user_theme"]
    assert conn.execute("SELECT amount_cents FROM balances").fetchone()[0] == 123456
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0     # no default user
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()
