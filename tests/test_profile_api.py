import pytest

from northstar import sessions, users
from conftest import with_db

PASSWORD = "test-password-123"      # the password of the signed-in client fixture


def test_me_returns_the_signed_in_user_with_dark_by_default(client):
    body = client.get("/api/me").json()
    assert body["email"] == "test@example.com" and body["display_name"] == "Test User"
    assert body["is_admin"] is True and body["theme"] == "dark"
    assert "password" not in str(body)


def test_me_needs_a_login(anon_client):
    assert anon_client.get("/api/me").status_code == 401
    assert anon_client.patch("/api/me", json={"theme": "light"}).status_code == 401
    assert anon_client.post("/api/me/password", json={"current_password": "x", "new_password": "y"}).status_code == 401


def test_change_theme_and_it_sticks(client):
    assert client.patch("/api/me", json={"theme": "light"}).json()["theme"] == "light"
    assert client.get("/api/me").json()["theme"] == "light"


def test_change_display_name(client):
    body = client.patch("/api/me", json={"display_name": "  New Name  "}).json()
    assert body["display_name"] == "New Name"
    assert client.get("/api/me").json()["display_name"] == "New Name"      # and it is saved


@pytest.mark.parametrize("body", [{"display_name": "   "}, {"display_name": "x" * 101}])
def test_bad_display_name_is_refused(client, body):
    assert client.patch("/api/me", json=body).status_code == 422
    assert client.get("/api/me").json()["display_name"] == "Test User"


def test_bad_theme_is_refused(client):
    assert client.patch("/api/me", json={"theme": "purple"}).status_code == 422


def test_a_failed_change_changes_nothing(client):
    assert client.patch("/api/me", json={"theme": "light", "display_name": " "}).status_code == 422
    assert client.get("/api/me").json()["theme"] == "dark"


def test_cannot_change_email_or_admin_through_the_profile(client):
    client.patch("/api/me", json={"email": "other@example.com", "is_admin": False})
    body = client.get("/api/me").json()
    assert body["email"] == "test@example.com" and body["is_admin"] is True


def test_change_password_needs_the_current_one(client):
    response = client.post("/api/me/password", json={"current_password": "wrong-password-123", "new_password": "a-new-password-456"})
    assert response.status_code == 422 and "current password" in response.json()["detail"]
    with with_db(client) as conn:
        assert users.authenticate(conn, "test@example.com", PASSWORD)


def test_change_password_enforces_the_minimum_length(client):
    response = client.post("/api/me/password", json={"current_password": PASSWORD, "new_password": "short"})
    assert response.status_code == 422 and "at least 12" in response.json()["detail"]


def test_change_password_keeps_this_browser_and_signs_out_the_others(client):
    with with_db(client) as conn:
        other_browser = sessions.create_session(conn, users.authenticate(conn, "test@example.com", PASSWORD)["id"])
    response = client.post("/api/me/password", json={"current_password": PASSWORD, "new_password": "a-new-password-456"})
    assert response.status_code == 204
    assert client.get("/api/me").status_code == 200                       # this browser stays signed in
    with with_db(client) as conn:
        assert sessions.user_for_token(conn, other_browser) is None         # the other one is signed out
        assert users.authenticate(conn, "test@example.com", PASSWORD) is None
        assert users.authenticate(conn, "test@example.com", "a-new-password-456")


def test_profile_changes_are_refused_from_another_site(client):
    response = client.patch("/api/me", json={"theme": "light"}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert client.get("/api/me").json()["theme"] == "dark"
