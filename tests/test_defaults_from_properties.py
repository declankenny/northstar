"""The system properties that supply a default: the theme a new user starts with, and the stale-after days a new account
type starts with. Synthetic data only."""

import pytest

from northstar import db, system_properties as sp, users
from northstar.errors import ValidationError
from conftest import op, with_db

PASSWORD = "a-fine-password-1"
NEW = {"email": "new@example.com", "display_name": "New Person", "password": PASSWORD}


def theme_of(conn, email):
    return conn.execute("SELECT theme FROM users WHERE email = ?", (email,)).fetchone()[0]


# -- ui.theme.default: every way of adding a user --

def test_a_new_user_starts_with_the_seeded_theme(conn):
    users.create_user(op(conn), "a@example.com", "A", PASSWORD)
    assert theme_of(conn, "a@example.com") == "dark"


def test_a_new_user_starts_with_the_theme_the_property_now_says(conn):
    sp.set_property(op(conn), "ui.theme.default", "light")
    users.create_user(op(conn), "a@example.com", "A", PASSWORD)
    assert theme_of(conn, "a@example.com") == "light"


def test_changing_the_property_does_not_change_users_who_already_exist(conn):
    users.create_user(op(conn), "a@example.com", "A", PASSWORD)
    sp.set_property(op(conn), "ui.theme.default", "light")
    assert theme_of(conn, "a@example.com") == "dark"


def test_a_reactivated_user_gets_the_property_too(conn):
    admin = users.create_user(op(conn), "admin@example.com", "Admin", PASSWORD, is_admin=True)
    target = users.create_user(op(conn), "a@example.com", "A", PASSWORD)
    users.set_theme(op(conn, target), target, "dark")
    users.delete_user(op(conn, admin), target, admin)
    sp.set_property(op(conn), "ui.theme.default", "light")
    assert users.add_user(op(conn, admin), "a@example.com", "A", PASSWORD) == (target, True)
    assert theme_of(conn, "a@example.com") == "light"


def test_the_add_user_endpoint_uses_the_property(client):
    with with_db(client) as conn:
        sp.set_property(op(conn), "ui.theme.default", "light")
    assert client.post("/api/users", json=NEW).status_code == 201
    with with_db(client) as conn:
        assert theme_of(conn, "new@example.com") == "light"


def test_an_operation_with_no_user_uses_the_property(tmp_path):
    """The command line and first-run setup add users with no one signed in."""
    path = tmp_path / "cli.db"
    db.upgrade(path)
    with db.connect(path) as conn:
        sp.set_property(op(conn, kind="cli"), "ui.theme.default", "light")
        users.create_user(op(conn, kind="cli"), "cli@example.com", "Cli Person", PASSWORD)
    with db.connect(path) as conn:
        assert theme_of(conn, "cli@example.com") == "light"


def test_a_theme_the_users_table_does_not_know_is_refused_and_says_why(conn):
    """If the setting ever held a value users cannot have, adding a user says so and adds nobody."""
    conn.execute("UPDATE system_properties SET value = 'sepia' WHERE name = 'ui.theme.default'")
    before = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    with pytest.raises(ValidationError, match=r"ui\.theme\.default\) is not light or dark"):
        users.create_user(op(conn), "a@example.com", "A", PASSWORD)
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == before


# -- system.balance.stale_days: what a new account type starts at --

def test_the_types_list_says_what_a_new_type_starts_at(client):
    assert client.get("/api/types").json()["default_stale_after_days"] == 35


def test_the_start_follows_the_property(client):
    with with_db(client) as conn:
        sp.set_property(op(conn), "system.balance.stale_days", "45")
    assert client.get("/api/types").json()["default_stale_after_days"] == 45


def test_the_answer_to_adding_a_type_carries_the_start_too(client):
    answer = client.post("/api/types", json={"name": "Crypto", "class_id": 1, "stale_after_days": 10}).json()
    assert answer["default_stale_after_days"] == 35


def test_existing_types_keep_their_own_days_when_the_property_changes(client):
    with with_db(client) as conn:
        sp.set_property(op(conn), "system.balance.stale_days", "45")
    types = {t["name"]: t["stale_after_days"] for t in client.get("/api/types").json()["types"]}
    assert types["Checking"] == 35 and types["Real estate"] == 365
