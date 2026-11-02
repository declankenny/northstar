"""Deleting a user keeps their row and hides them; adding their email again reactivates the same person.
Synthetic data only."""

import sqlite3

import pytest

from northstar import db, sessions, users
from northstar.errors import ValidationError
from northstar.writer import Operation

from conftest import add_account, op, with_db
from test_migration_runner import v01_database

PASSWORD = "synthetic-pass-123"
OTHER = "another-synthetic-pass-456"


def make(conn, email="a@example.com", name="A", admin=False, actor=None):
    return users.create_user(op(conn, actor), email, name, PASSWORD, is_admin=admin)


@pytest.fixture
def admin(conn):
    return make(conn, "admin@example.com", "Admin", admin=True)


def row(conn, user_id):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


# -- deleting --

def test_deleting_a_user_keeps_the_row_and_marks_it_deleted(conn, admin):
    target = make(conn, actor=admin)
    users.delete_user(op(conn, admin), target, admin)
    kept = row(conn, target)
    assert kept["deleted"] == 1 and kept["email"] == "a@example.com" and kept["display_name"] == "A"
    assert kept["password_hash"] == users.UNUSABLE_HASH
    assert (kept["updated_by"], kept["created_by"]) == (admin, admin)         # who deleted them is recorded


def test_deleting_a_user_ends_their_sessions_and_only_theirs(conn, admin):
    target = make(conn)
    mine, theirs = sessions.create_session(conn, admin), sessions.create_session(conn, target)
    users.delete_user(op(conn, admin), target, admin)
    assert sessions.user_for_token(conn, theirs) is None
    assert sessions.user_for_token(conn, mine)["id"] == admin


def test_a_session_of_a_deleted_user_is_refused_even_if_one_survived(conn, admin):
    target = make(conn)
    token = sessions.create_session(conn, target)
    conn.execute("UPDATE users SET deleted = 1 WHERE id = ?", (target,))      # as if the delete had missed a session
    assert sessions.user_for_token(conn, token) is None


def test_a_deleted_user_is_hidden_and_cannot_be_looked_up_or_changed(conn, admin):
    target = make(conn)
    users.delete_user(op(conn, admin), target, admin)
    assert [r["email"] for r in users.list_users(conn)] == ["admin@example.com"]
    before = tuple(row(conn, target))
    for action in (
        lambda: users.get_user(conn, target),
        lambda: users.update_user(op(conn, admin), target, admin, display_name="Renamed"),
        lambda: users.delete_user(op(conn, admin), target, admin),
        lambda: users.set_user_password(op(conn, admin), target, OTHER),
        lambda: users.set_password(op(conn), "a@example.com", OTHER),
        lambda: users.set_theme(op(conn), target, "light"),
        lambda: users.set_display_name(op(conn), target, "Renamed"),
    ):
        with pytest.raises(ValidationError, match="no longer exists|no user with that email"):
            action()
    assert tuple(row(conn, target)) == before


def test_a_deleted_user_cannot_sign_in_and_it_costs_the_same_as_an_unknown_email(conn, admin, monkeypatch):
    target = make(conn)
    users.delete_user(op(conn, admin), target, admin)
    calls = []
    real = users.verify_password
    monkeypatch.setattr(users, "verify_password", lambda password, stored: calls.append(stored) or real(password, stored))
    assert users.authenticate(conn, "nobody@example.com", PASSWORD) is None
    unknown = calls[:]
    calls.clear()
    assert users.authenticate(conn, "a@example.com", PASSWORD) is None
    assert len(calls) == 1 and calls == unknown                   # one hash of the same dummy, not an instant answer


def test_a_deleted_user_cannot_sign_in_even_with_their_old_password_restored_in_the_row(conn, admin):
    target = make(conn)
    users.delete_user(op(conn, admin), target, admin)
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (users.hash_password(PASSWORD), target))
    assert users.authenticate(conn, "a@example.com", PASSWORD) is None


def test_deleting_a_user_who_authored_data_works_and_the_data_keeps_its_author(conn, admin):
    author = make(conn, actor=admin)
    account = users_account(conn, author)
    users.delete_user(op(conn, admin), author, admin)
    assert conn.execute("SELECT created_by FROM accounts WHERE id = ?", (account,)).fetchone()[0] == author
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def users_account(conn, actor):
    from northstar import accounts
    return accounts.add_account(op(conn, actor), "Test account", 1, 1)


def test_deleting_a_user_who_created_another_user_works(conn, admin):
    first = make(conn, "first@example.com", "First", admin=True, actor=admin)
    second = make(conn, "second@example.com", "Second", actor=first)
    users.delete_user(op(conn, admin), first, admin)
    assert row(conn, second)["created_by"] == first


# -- the admin rules count live admins --

def test_the_last_live_admin_cannot_be_deleted_even_if_a_deleted_admin_remains(conn, admin):
    second = make(conn, "second@example.com", "Second", admin=True)
    users.delete_user(op(conn, admin), second, admin)
    third = make(conn, "third@example.com", "Third")
    with pytest.raises(ValidationError, match="at least one admin"):
        users.update_user(op(conn, third), admin, third, is_admin=False)          # a deleted admin does not count
    with pytest.raises(ValidationError, match="at least one admin"):
        users.delete_user(op(conn, third), admin, third)


def test_you_still_cannot_delete_yourself(conn, admin):
    make(conn, "second@example.com", "Second", admin=True)
    with pytest.raises(ValidationError, match="your own account"):
        users.delete_user(op(conn, admin), admin, admin)
    assert row(conn, admin)["deleted"] == 0


# -- reactivation --

def test_adding_a_deleted_users_email_reactivates_the_same_row(conn, admin):
    target = make(conn, actor=admin)
    created = row(conn, target)
    users.delete_user(op(conn, admin), target, admin)
    new_id, reactivated = users.add_user(op(conn, admin), "a@example.com", "A Again", OTHER)
    assert (new_id, reactivated) == (target, True)
    back = row(conn, target)
    assert back["deleted"] == 0 and back["display_name"] == "A Again"
    assert (back["id"], back["email"], back["created_at"], back["created_by"]) == (
        created["id"], created["email"], created["created_at"], created["created_by"])      # who they are, unchanged
    assert back["updated_by"] == admin and back["updated_at"] >= created["updated_at"]
    assert conn.execute("SELECT COUNT(*) FROM users WHERE email = 'a@example.com'").fetchone()[0] == 1


def test_a_new_email_is_still_just_added(conn, admin):
    new_id, reactivated = users.add_user(op(conn, admin), "b@example.com", "B", PASSWORD)
    assert reactivated is False and row(conn, new_id)["deleted"] == 0


def test_reactivation_matches_the_email_ignoring_case_and_spaces(conn, admin):
    target = make(conn, "mixed@example.com", "M")
    users.delete_user(op(conn, admin), target, admin)
    assert users.add_user(op(conn, admin), "  MIXED@Example.com ", "M", PASSWORD) == (target, True)


def test_a_formerly_admin_user_re_added_without_an_admin_request_is_a_regular_user(conn, admin):
    target = make(conn, "was-admin@example.com", "W", admin=True)
    users.delete_user(op(conn, admin), target, admin)
    users.add_user(op(conn, admin), "was-admin@example.com", "W", PASSWORD)
    assert row(conn, target)["is_admin"] == 0
    users.delete_user(op(conn, admin), target, admin)
    users.add_user(op(conn, admin), "was-admin@example.com", "W", PASSWORD, is_admin=True)
    assert row(conn, target)["is_admin"] == 1                              # and an explicit request is honoured


def test_the_theme_goes_back_to_the_default(conn, admin):
    target = make(conn)
    users.set_theme(op(conn, target), target, "light")
    users.delete_user(op(conn, admin), target, admin)
    users.add_user(op(conn, admin), "a@example.com", "A", PASSWORD)
    assert row(conn, target)["theme"] == users.DEFAULT_THEME == "dark"


def test_old_passwords_and_sessions_stay_unusable_after_reactivation(conn, admin):
    target = make(conn)
    old_token = sessions.create_session(conn, target)
    users.delete_user(op(conn, admin), target, admin)
    users.add_user(op(conn, admin), "a@example.com", "A", OTHER)
    assert sessions.user_for_token(conn, old_token) is None
    assert users.authenticate(conn, "a@example.com", PASSWORD) is None          # the old password
    assert users.authenticate(conn, "a@example.com", OTHER)["id"] == target     # only the new one


def test_a_refused_reactivation_changes_nothing(conn, admin):
    target = make(conn)
    users.delete_user(op(conn, admin), target, admin)
    before = tuple(row(conn, target))
    with pytest.raises(ValidationError, match="at least 12"):
        users.add_user(op(conn, admin), "a@example.com", "A", "short")
    assert tuple(row(conn, target)) == before


def test_a_live_users_email_cannot_be_added_again(conn, admin):
    make(conn)
    with pytest.raises(ValidationError, match="already exists"):
        users.add_user(op(conn, admin), "A@example.com", "A", PASSWORD)


def test_the_email_of_a_deleted_user_still_cannot_be_given_to_a_live_one(conn, admin):
    gone = make(conn, "gone@example.com", "Gone")
    users.delete_user(op(conn, admin), gone, admin)
    other = make(conn, "other@example.com", "Other")
    with pytest.raises(ValidationError, match="already exists"):
        users.update_user(op(conn, admin), other, admin, email="gone@example.com")


def test_the_system_user_cannot_be_reactivated_or_added(conn, admin):
    system = conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]
    conn.execute("UPDATE users SET deleted = 1 WHERE id = ?", (system,))       # even if it were somehow marked deleted
    before = tuple(row(conn, system))
    with pytest.raises(ValidationError, match="valid email"):
        users.add_user(op(conn, admin), "system@northstar.invalid", "S", PASSWORD)
    assert tuple(row(conn, system)) == before


# -- the command line --

def test_the_command_line_creates_restores_and_hides(tmp_path, monkeypatch, capsys):
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path)
    monkeypatch.setenv("NORTHSTAR_DB", str(path))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": PASSWORD)
    assert users.main(["create", "boss@example.com", "Boss", "--admin"]) == 0
    assert users.main(["create", "gone@example.com", "Gone"]) == 0
    assert "Created gone@example.com" in capsys.readouterr().out
    conn = db.connect(path)
    gone = conn.execute("SELECT id FROM users WHERE email = 'gone@example.com'").fetchone()[0]
    boss = conn.execute("SELECT id FROM users WHERE email = 'boss@example.com'").fetchone()[0]
    users.delete_user(op(conn, boss), gone, boss)
    assert users.main(["list"]) == 0
    assert "gone@example.com" not in capsys.readouterr().out
    assert users.main(["set-password", "gone@example.com"]) == 1
    assert users.main(["create", "gone@example.com", "Gone"]) == 0
    assert "Restored gone@example.com" in capsys.readouterr().out
    assert conn.execute("SELECT id, deleted FROM users WHERE email = 'gone@example.com'").fetchone()[:] == (gone, 0)


# -- the web API --

def test_the_api_deletes_hides_and_reactivates(client):
    created = client.post("/api/users", json={"email": "p@example.com", "display_name": "P",
                                              "password": PASSWORD, "is_admin": False})
    assert created.status_code == 201 and created.json()["reactivated"] is False
    person = created.json()["id"]
    assert client.delete(f"/api/users/{person}").status_code == 204
    assert "p@example.com" not in client.get("/api/users").text
    for response in (client.patch(f"/api/users/{person}", json={"display_name": "X"}),
                     client.delete(f"/api/users/{person}"),
                     client.post(f"/api/users/{person}/password", json={"password": OTHER})):
        assert response.status_code == 404
    again = client.post("/api/users", json={"email": "p@example.com", "display_name": "P2",
                                            "password": OTHER, "is_admin": True})
    assert again.status_code == 201
    assert (again.json()["id"], again.json()["reactivated"], again.json()["display_name"], again.json()["is_admin"]) == (
        person, True, "P2", True)
    assert [u["email"] for u in client.get("/api/users").json()].count("p@example.com") == 1
    assert all(not listed["reactivated"] for listed in client.get("/api/users").json())      # only an add says it


def test_a_deleted_users_browser_is_signed_out_at_once(client, anon_client):
    with with_db(client) as conn:
        person = make(conn, "p@example.com", "P")
        anon_client.cookies.set("northstar_session", sessions.create_session(conn, person))
    assert anon_client.get("/api/me").status_code == 200
    assert client.delete(f"/api/users/{person}").status_code == 204
    assert anon_client.get("/api/me").status_code == 401


# -- upgrading --

def test_the_upgrade_adds_the_flag_and_keeps_every_user(tmp_path):
    path = v01_database(tmp_path / "data" / "northstar.db")
    seed = sqlite3.connect(path)
    seed.execute("INSERT INTO users (email, display_name, password_hash, is_admin) VALUES ('old@example.com', 'Old', 'kept', 1)")
    seed.commit()
    seed.close()
    db.upgrade(path)
    conn = db.connect(path)
    assert [tuple(r) for r in conn.execute("SELECT email, deleted FROM users ORDER BY id")] == [
        ("old@example.com", 0), ("system@northstar.invalid", 0)]


def test_the_flag_only_accepts_zero_or_one(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE users SET deleted = 2")
