import pytest
from fastapi.testclient import TestClient

from northstar import sessions, users
from northstar.web.app import create_app
from conftest import with_db, op

NEW = {"email": "new@example.com", "display_name": "New Person", "password": "a-fine-password-1"}


def add(client, **overrides):
    return client.post("/api/users", json={**NEW, **overrides})


def user_id(client, email):
    return next(u["id"] for u in client.get("/api/users").json() if u["email"] == email)


# -- who may use it --

@pytest.mark.parametrize("method, path, body", [
    ("get", "/api/users", None),
    ("post", "/api/users", NEW),
    ("patch", "/api/users/1", {"is_admin": True}),
    ("post", "/api/users/1/password", {"password": "a-fine-password-1"}),
    ("delete", "/api/users/1", None),
])
def test_members_are_refused_and_nothing_changes(member_client, method, path, body):
    response = getattr(member_client, method)(path, **({"json": body} if body else {}))
    assert response.status_code == 403
    with with_db(member_client) as conn:
        assert [u["email"] for u in users.list_users(conn)] == ["member@example.com"]


def test_signed_out_is_refused(anon_client):
    assert anon_client.get("/api/users").status_code == 401
    assert anon_client.delete("/api/users/1").status_code == 401


def test_changes_from_another_site_are_refused(client):
    response = client.post("/api/users", json=NEW, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert len(client.get("/api/users").json()) == 1


# -- list and add --

def test_list_shows_users_without_any_password_data(client):
    body = client.get("/api/users").json()
    assert [(u["email"], u["is_admin"]) for u in body] == [("test@example.com", True)]
    assert "password" not in str(body) and "hash" not in str(body)


def test_add_user_who_can_then_sign_in(client):
    created = add(client)
    assert created.status_code == 201
    assert created.json()["email"] == "new@example.com" and created.json()["is_admin"] is False
    other = TestClient(create_app(client.app.state.db_path), follow_redirects=False)
    login = other.post("/login", data={"email": "new@example.com", "password": NEW["password"]})
    assert login.status_code == 303 and other.get("/api/me").status_code == 200
    assert other.get("/api/users").status_code == 403          # not an admin


def test_add_admin(client):
    assert add(client, is_admin=True).json()["is_admin"] is True


@pytest.mark.parametrize("overrides, message", [
    ({"email": "TEST@example.com"}, "already exists"),
    ({"email": "not-an-email"}, "valid email"),
    ({"password": "short"}, "at least 12"),
    ({"display_name": "  "}, "Enter a name"),
])
def test_bad_new_users_are_refused(client, overrides, message):
    response = add(client, **overrides)
    assert response.status_code == 422 and message in response.json()["detail"]
    assert len(client.get("/api/users").json()) == 1


# -- admin flag --

def test_make_and_remove_admin(client):
    uid = add(client).json()["id"]
    assert client.patch(f"/api/users/{uid}", json={"is_admin": True}).json()["is_admin"] is True
    assert client.patch(f"/api/users/{uid}", json={"is_admin": False}).json()["is_admin"] is False


def test_the_last_admin_cannot_be_demoted(client):
    me = user_id(client, "test@example.com")
    response = client.patch(f"/api/users/{me}", json={"is_admin": False})
    assert response.status_code == 422 and "at least one admin" in response.json()["detail"]
    assert client.get("/api/me").json()["is_admin"] is True


def test_an_admin_cannot_remove_their_own_admin_even_when_another_exists(client):
    add(client, is_admin=True)
    me = user_id(client, "test@example.com")
    response = client.patch(f"/api/users/{me}", json={"is_admin": False})
    assert response.status_code == 422 and "your own admin" in response.json()["detail"]
    assert client.get("/api/me").json()["is_admin"] is True


# -- edit a user --

def test_edit_changes_email_name_and_admin_together(client):
    uid = add(client).json()["id"]
    body = client.patch(f"/api/users/{uid}", json={"email": " Renamed@Example.com ", "display_name": " Renamed ", "is_admin": True}).json()
    assert (body["email"], body["display_name"], body["is_admin"]) == ("renamed@example.com", "Renamed", True)
    assert user_id(client, "renamed@example.com") == uid


def test_a_field_left_out_stays_as_it_is(client):
    uid = add(client, is_admin=True).json()["id"]
    body = client.patch(f"/api/users/{uid}", json={"display_name": "Only the name"}).json()
    assert (body["email"], body["display_name"], body["is_admin"]) == ("new@example.com", "Only the name", True)


def test_the_user_can_sign_in_with_the_new_email_and_stays_signed_in(client):
    uid = add(client).json()["id"]
    with with_db(client) as conn:
        their_session = sessions.create_session(conn, uid)
    client.patch(f"/api/users/{uid}", json={"email": "moved@example.com"})
    with with_db(client) as conn:
        assert sessions.user_for_token(conn, their_session) is not None
        assert users.authenticate(conn, "new@example.com", NEW["password"]) is None
        assert users.authenticate(conn, "moved@example.com", NEW["password"])


@pytest.mark.parametrize("fields, message", [
    ({"email": "TEST@example.com"}, "already exists"),     # the admin's own address, ignoring case
    ({"email": "not-an-email"}, "valid email"),
    ({"display_name": "  "}, "Enter a name"),
    ({"display_name": "x" * 101}, "at most"),
])
def test_a_bad_edit_is_refused_and_changes_nothing(client, fields, message):
    uid = add(client).json()["id"]
    response = client.patch(f"/api/users/{uid}", json={"is_admin": True, **fields})
    assert response.status_code == 422 and message in response.json()["detail"]
    row = next(u for u in client.get("/api/users").json() if u["id"] == uid)
    assert (row["email"], row["display_name"], row["is_admin"]) == ("new@example.com", "New Person", False)


def test_an_admin_can_change_their_own_email_and_name(client):
    me = user_id(client, "test@example.com")
    body = client.patch(f"/api/users/{me}", json={"email": "me2@example.com", "display_name": "Me Two"}).json()
    assert (body["email"], body["display_name"], body["is_admin"]) == ("me2@example.com", "Me Two", True)
    assert client.get("/api/me").json()["email"] == "me2@example.com"       # still signed in


def test_keeping_the_same_email_is_not_a_duplicate(client):
    uid = add(client).json()["id"]
    assert client.patch(f"/api/users/{uid}", json={"email": "new@example.com", "display_name": "Same email"}).status_code == 200


def test_unknown_user_is_404(client):
    assert client.patch("/api/users/999", json={"is_admin": True}).status_code == 404
    assert client.delete("/api/users/999").status_code == 404
    assert client.post("/api/users/999/password", json={"password": "a-fine-password-1"}).status_code == 404


# -- reset password --

def test_reset_password_changes_it_and_signs_that_user_out(client):
    uid = add(client).json()["id"]
    with with_db(client) as conn:
        their_session = sessions.create_session(conn, uid)
    assert client.post(f"/api/users/{uid}/password", json={"password": "reset-password-99"}).status_code == 204
    with with_db(client) as conn:
        assert sessions.user_for_token(conn, their_session) is None
        assert users.authenticate(conn, "new@example.com", NEW["password"]) is None
        assert users.authenticate(conn, "new@example.com", "reset-password-99")
    assert client.get("/api/users").status_code == 200           # the admin stays signed in


def test_reset_password_enforces_the_minimum_length(client):
    uid = add(client).json()["id"]
    assert client.post(f"/api/users/{uid}/password", json={"password": "short"}).status_code == 422


def test_admin_cannot_reset_their_own_password_here(client):
    me = user_id(client, "test@example.com")
    response = client.post(f"/api/users/{me}/password", json={"password": "reset-password-99"})
    assert response.status_code == 422 and "Profile" in response.json()["detail"]


# -- delete --

def test_delete_user_and_their_sessions(client):
    uid = add(client).json()["id"]
    with with_db(client) as conn:
        their_session = sessions.create_session(conn, uid)
    assert client.delete(f"/api/users/{uid}").status_code == 204
    assert [u["email"] for u in client.get("/api/users").json()] == ["test@example.com"]
    with with_db(client) as conn:
        assert sessions.user_for_token(conn, their_session) is None


def test_you_cannot_delete_yourself(client):
    add(client, is_admin=True)
    me = user_id(client, "test@example.com")
    response = client.delete(f"/api/users/{me}")
    assert response.status_code == 422 and "your own account" in response.json()["detail"]
    assert len(client.get("/api/users").json()) == 2


def test_the_last_admin_cannot_be_deleted(member_client):
    # Rule check on the plain function: a member is signed in, so the only admin is not the actor.
    with with_db(member_client) as conn:
        admin = users.create_user(op(conn), "only@example.com", "Only Admin", "a-fine-password-1", is_admin=True)
        member = conn.execute("SELECT id FROM users WHERE email = 'member@example.com'").fetchone()["id"]
        with pytest.raises(users.ValidationError, match="at least one admin"):
            users.delete_user(op(conn), admin, acting_user_id=member)
