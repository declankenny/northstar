"""Audit columns, stable ids, the sys_ prefix and the system user (migrations 0004 and 0005). Synthetic data only."""

import sqlite3

import pytest

from northstar import db, sessions, users
from northstar.errors import ValidationError

from conftest import add_account, add_balance, op, with_db
from test_migration_runner import backups_of, counts, v01_database

SYSTEM_EMAIL = "system@northstar.invalid"
AUDIT = ("created_at", "created_by", "updated_at", "updated_by")


def household_tables(conn):
    return sorted(row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'sys\\_%' ESCAPE '\\' "
        "AND name NOT LIKE 'ref\\_%' ESCAPE '\\'"))


def system_id(conn):
    return conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]


# -- the schema rules --

def test_every_table_is_either_a_sys_table_or_a_household_table_with_audit_columns(conn):
    assert household_tables(conn) == ["account_classes", "account_types", "accounts", "balances", "system_properties", "users"]
    for table in household_tables(conn):
        columns = {row["name"]: row for row in conn.execute(f"PRAGMA table_info({table})")}
        assert set(AUDIT) <= set(columns), table
        assert columns["created_by"]["notnull"] and columns["updated_by"]["notnull"], table
        targets = {row["from"]: row["table"] for row in conn.execute(f"PRAGMA foreign_key_list({table})")}
        assert targets["created_by"] == targets["updated_by"] == "users", table


def test_ref_tables_carry_no_audit_columns(conn):
    names = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'ref\\_%' ESCAPE '\\'")]
    assert sorted(names) == ["ref_property_data_types", "ref_property_lookups", "ref_property_validators"]
    for name in names:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({name})")}
        assert not columns & set(AUDIT), name


def test_sys_tables_carry_no_audit_columns(conn):
    for name in ("sys_sessions", "sys_login_attempts", "sys_schema_migrations"):
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({name})")}
        assert columns and not columns & {"created_by", "updated_by"}, name


def test_the_old_session_and_login_tables_are_gone(conn):
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert not names & {"sessions", "login_attempts", "schema_migrations"}


def test_every_household_table_uses_autoincrement(conn):
    for table in household_tables(conn):
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
        assert "AUTOINCREMENT" in sql.upper(), table


def test_the_id_of_a_deleted_row_is_never_given_to_another(conn):
    account = add_account(conn, "Test account", 1, "Checking")
    add_balance(conn, account, "2026-01-31", 100)
    add_balance(conn, account, "2026-02-28", 200)
    highest = conn.execute("SELECT MAX(id) FROM balances").fetchone()[0]
    conn.execute("DELETE FROM balances WHERE id = ?", (highest,))
    add_balance(conn, account, "2026-03-31", 300)
    assert conn.execute("SELECT MAX(id) FROM balances").fetchone()[0] > highest


def test_exactly_one_system_user_exists_and_a_second_is_refused(conn):
    assert conn.execute("SELECT COUNT(*) FROM users WHERE is_system = 1").fetchone()[0] == 1
    row = conn.execute("SELECT * FROM users WHERE is_system = 1").fetchone()
    assert row["email"] == SYSTEM_EMAIL and not row["is_admin"]
    assert row["created_by"] == row["updated_by"] == row["id"]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO users (email, display_name, password_hash, is_system, created_by, updated_by) "
                     "VALUES ('other@northstar.invalid', 'S', '!', 1, 1, 1)")


def test_the_seeded_rows_are_authored_by_the_system_user(conn):
    for table in ("account_classes", "account_types"):
        assert {row[0] for row in conn.execute(f"SELECT created_by FROM {table}")} == {system_id(conn)}


def test_an_author_must_be_a_real_user(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO accounts (name, class_id, type_id, created_by, updated_by) VALUES ('X', 1, 1, 9999, 9999)")


# -- the system user cannot be used --

def test_the_system_user_is_refused_at_sign_in_like_an_unknown_email(conn, monkeypatch):
    calls = []
    real = users.verify_password
    monkeypatch.setattr(users, "verify_password", lambda password, stored: calls.append(stored) or real(password, stored))
    assert users.authenticate(conn, "nobody@example.com", "any password at all") is None
    unknown = calls[:]
    calls.clear()
    assert users.authenticate(conn, SYSTEM_EMAIL, "any password at all") is None
    assert len(calls) == len(unknown) == 1 and calls == unknown      # the same work, on the same dummy hash


def test_the_system_user_is_refused_even_if_someone_gives_it_a_working_password(conn):
    conn.execute("UPDATE users SET password_hash = ? WHERE is_system = 1", (users.hash_password("a-synthetic-password"),))
    assert users.authenticate(conn, SYSTEM_EMAIL, "a-synthetic-password") is None


def test_no_password_verifies_against_the_system_users_stored_hash(conn):
    stored = conn.execute("SELECT password_hash FROM users WHERE is_system = 1").fetchone()[0]
    assert not users.verify_password("", stored) and not users.verify_password("!", stored)


def test_the_system_user_is_not_in_the_list_and_cannot_be_looked_up(conn):
    users.create_user(op(conn), "a@example.com", "A", "synthetic-pass-123")
    assert [row["email"] for row in users.list_users(conn)] == ["a@example.com"]
    with pytest.raises(ValidationError, match="no longer exists"):
        users.get_user(conn, system_id(conn))


def test_the_system_user_cannot_be_changed_deleted_or_reset(conn):
    users.create_user(op(conn), "a@example.com", "A", "synthetic-pass-123", is_admin=True)
    admin = conn.execute("SELECT id FROM users WHERE email = 'a@example.com'").fetchone()[0]
    target = system_id(conn)
    before = tuple(conn.execute("SELECT * FROM users WHERE id = ?", (target,)).fetchone())
    for action in (
        lambda: users.update_user(op(conn), target, admin, display_name="Renamed"),
        lambda: users.delete_user(op(conn), target, admin),
        lambda: users.set_user_password(op(conn), target, "synthetic-pass-123"),
        lambda: users.set_password(op(conn), SYSTEM_EMAIL, "synthetic-pass-123"),
        lambda: users.set_theme(op(conn), target, "light"),
        lambda: users.set_display_name(op(conn), target, "Renamed"),
    ):
        with pytest.raises(ValidationError):
            action()
    assert tuple(conn.execute("SELECT * FROM users WHERE id = ?", (target,)).fetchone()) == before


@pytest.mark.parametrize("email", [SYSTEM_EMAIL, "someone@example.invalid", "x@northstar.INVALID"])
def test_an_address_ending_in_invalid_cannot_be_used_for_a_user(conn, email):
    with pytest.raises(ValidationError, match="valid email"):
        users.create_user(op(conn), email, "X", "synthetic-pass-123")


def test_the_command_line_does_not_list_or_reset_the_system_user(tmp_path, monkeypatch, capsys):
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path)
    monkeypatch.setenv("NORTHSTAR_DB", str(path))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "synthetic-pass-123")
    assert users.main(["list"]) == 0
    assert SYSTEM_EMAIL not in capsys.readouterr().out
    assert users.main(["set-password", SYSTEM_EMAIL]) == 1
    assert "no user with that email" in capsys.readouterr().err
    assert users.main(["create", SYSTEM_EMAIL, "X"]) == 1


def test_the_users_api_hides_and_refuses_the_system_user(client):
    with with_db(client) as conn:
        target = system_id(conn)
    assert SYSTEM_EMAIL not in client.get("/api/users").text
    assert client.patch(f"/api/users/{target}", json={"display_name": "Renamed"}).status_code == 404
    assert client.delete(f"/api/users/{target}").status_code == 404
    assert client.post(f"/api/users/{target}/password", json={"password": "synthetic-pass-123"}).status_code == 404


# -- who made a change --

def test_what_a_signed_in_user_does_is_authored_by_them(client):
    with with_db(client) as conn:
        me = conn.execute("SELECT id FROM users WHERE email = 'test@example.com'").fetchone()[0]
    assert client.post("/api/accounts", json={"name": "Test api", "account_class": "asset", "type_id": 1,
                                              "amount": "10.00", "date": "2026-01-31"}).status_code == 201
    assert client.post("/api/users", json={"email": "new@example.com", "display_name": "New",
                                           "password": "synthetic-pass-123", "is_admin": False}).status_code == 201
    with with_db(client) as conn:
        for table, where in (("accounts", "name = 'Test api'"), ("balances", "1 = 1"), ("users", "email = 'new@example.com'")):
            row = conn.execute(f"SELECT created_by, updated_by FROM {table} WHERE {where}").fetchone()
            assert (row[0], row[1]) == (me, me), table


def test_an_edit_by_another_user_changes_updated_by_and_not_created_by(client):
    assert client.post("/api/accounts", json={"name": "Test api", "account_class": "asset", "type_id": 1}).status_code == 201
    with with_db(client) as conn:
        first = conn.execute("SELECT id, created_by FROM accounts WHERE name = 'Test api'").fetchone()
        other = users.create_user(op(conn), "other@example.com", "Other", "synthetic-pass-123", is_admin=True)
    with with_db(client) as conn:
        client.cookies.set("northstar_session", sessions.create_session(conn, other))
    assert client.patch(f"/api/accounts/{first['id']}", json={"name": "Test renamed", "type_id": 1}).status_code == 200
    with with_db(client) as conn:
        row = conn.execute("SELECT created_by, updated_by FROM accounts WHERE id = ?", (first["id"],)).fetchone()
    assert (row["created_by"], row["updated_by"]) == (first["created_by"], other)


def test_the_command_line_creates_users_as_the_system_user(tmp_path, monkeypatch):
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path)
    monkeypatch.setenv("NORTHSTAR_DB", str(path))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "synthetic-pass-123")
    assert users.main(["create", "first@example.com", "First", "--admin"]) == 0
    conn = db.connect(path)
    row = conn.execute("SELECT created_by, updated_by FROM users WHERE email = 'first@example.com'").fetchone()
    assert (row["created_by"], row["updated_by"]) == (system_id(conn), system_id(conn))


def test_a_password_upgrade_at_sign_in_is_authored_by_the_person_signing_in(conn):
    users.create_user(op(conn), "a@example.com", "A", "synthetic-pass-123")
    person = conn.execute("SELECT id FROM users WHERE email = 'a@example.com'").fetchone()[0]
    old = _hash_with("synthetic-pass-123", 2**3)
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (old, person))
    assert users.authenticate(conn, "a@example.com", "synthetic-pass-123") is not None
    assert conn.execute("SELECT updated_by FROM users WHERE id = ?", (person,)).fetchone()[0] == person


def _hash_with(password, n):
    import base64
    import hashlib
    salt = b"0123456789abcdef"
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=8, p=1)
    b64 = lambda raw: base64.b64encode(raw).decode()
    return f"scrypt${n}$8$1${b64(salt)}${b64(digest)}"


# -- upgrading a v0.1 database --

@pytest.fixture
def upgraded(tmp_path):
    path = v01_database(tmp_path / "data" / "northstar.db")
    seed = sqlite3.connect(path)
    seed.execute("INSERT INTO users (email, display_name, password_hash, is_admin) VALUES ('old@example.com', 'Old', 'kept', 1)")
    seed.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES ('t', 1, '2999-01-01T00:00:00Z')")
    seed.execute("INSERT INTO login_attempts (email_hash, address_hash, attempted_at) VALUES ('e', NULL, '2026-01-01T00:00:00Z')")
    seed.execute("UPDATE balances SET created_at = '2026-02-01T00:00:00Z', updated_at = '2026-03-01T00:00:00Z'")
    seed.commit()
    before = {table: seed.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
              for table in ("account_classes", "account_types", "accounts", "balances", "users")}
    ids = [row[0] for row in seed.execute("SELECT id FROM account_types ORDER BY id")]
    seed.close()
    applied = db.upgrade(path)
    return path, before, ids, applied


def test_a_v0_1_database_is_backed_up_then_upgraded_with_every_row_kept(upgraded):
    path, before, ids, applied = upgraded
    assert applied[:3] == ["0003_unique_account_names", "0004_audit_columns_and_system_user", "0005_sys_table_names"]
    assert len(backups_of(path)) == 1
    conn = db.connect(path)
    after = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in before}
    assert after == {**before, "users": before["users"] + 1}                    # and the system user
    assert [row[0] for row in conn.execute("SELECT id FROM account_types ORDER BY id")] == ids
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_the_upgrade_backfills_every_row_to_the_system_user_and_keeps_its_times(upgraded):
    path, *_ = upgraded
    conn = db.connect(path)
    system = system_id(conn)
    for table in ("account_classes", "account_types", "accounts", "balances", "users"):
        assert {tuple(row) for row in conn.execute(f"SELECT created_by, updated_by FROM {table}")} == {(system, system)}, table
    balance = conn.execute("SELECT created_at, updated_at FROM balances").fetchone()
    assert (balance[0], balance[1]) == ("2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z")      # what it had, not now
    old = conn.execute("SELECT * FROM users WHERE email = 'old@example.com'").fetchone()
    assert (old["password_hash"], old["is_admin"], old["is_system"], old["updated_at"]) == ("kept", 1, 0, old["created_at"])
    assert conn.execute("SELECT created_at FROM account_classes").fetchone()[0].endswith("Z")


def test_the_upgrade_keeps_sessions_and_login_attempts_under_their_new_names(upgraded):
    path, *_ = upgraded
    conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM sys_sessions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sys_login_attempts").fetchone()[0] == 1
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"sys_sessions_user_id", "sys_login_attempts_email", "sys_login_attempts_address",
            "accounts_name_unique", "users_one_system"} <= names
    assert not names & {"sessions_user_id", "login_attempts_email", "login_attempts_address"}


def test_the_upgrade_keeps_ids_from_being_reused_afterwards(upgraded):
    path, *_ = upgraded
    conn = db.connect(path)
    highest = conn.execute("SELECT MAX(id) FROM balances").fetchone()[0]
    conn.execute("DELETE FROM balances")
    add_balance(conn, conn.execute("SELECT id FROM accounts").fetchone()[0], "2026-04-30", 1)
    assert conn.execute("SELECT MAX(id) FROM balances").fetchone()[0] > highest


def test_a_second_start_changes_nothing(upgraded):
    path, *_ = upgraded
    before = path.read_bytes()
    assert db.upgrade(path) == []
    assert path.read_bytes() == before


def test_a_new_database_starts_with_only_the_system_user(tmp_path):
    path = tmp_path / "northstar.db"
    db.upgrade(path)
    conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    assert counts(conn) == [0, 0]
    assert backups_of(path) == []
