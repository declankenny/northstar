import pytest
from fastapi.testclient import TestClient

from northstar import users
from northstar.web.app import create_app
from conftest import with_db

PASSWORD = "synthetic-pass-123"


@pytest.fixture
def anon(anon_client):
    with with_db(anon_client) as conn:
        users.create_user(conn, "a@example.com", "Test A", PASSWORD)
    return anon_client


@pytest.mark.parametrize("path", ["/", "/accounts", "/types", "/balances/update"])
def test_pages_redirect_to_login_when_signed_out(anon, path):
    response = anon.get(path)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


def test_api_answers_401_when_signed_out(anon):
    assert anon.get("/api/networth").status_code == 401


def test_posts_are_refused_when_signed_out(anon):
    response = anon.post("/types", data={"name": "X", "class_id": "1", "stale_after_days": "35"})
    assert response.status_code == 303
    with with_db(anon) as conn:
        assert conn.execute("SELECT COUNT(*) FROM account_types WHERE name = 'X'").fetchone()[0] == 0


def test_login_page_and_stylesheet_are_public(anon):
    assert anon.get("/login").status_code == 200
    assert anon.get("/static/style.css").status_code == 200
    assert anon.get("/static/login.css").status_code == 200


def test_login_page_is_the_styled_standalone_page(anon):
    page = anon.get("/login").text
    assert "/static/login.css" in page and "northstar-theme" in page and "Sign in" in page
    assert "<nav>" not in page


def test_login_sets_a_http_only_cookie_and_opens_the_app(anon):
    response = anon.post("/login", data={"email": "A@example.com", "password": PASSWORD})
    assert response.status_code == 303 and response.headers["location"] == "/"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" not in cookie
    assert anon.get("/").status_code == 200
    assert anon.get("/api/networth").status_code == 200


def test_login_returns_to_the_page_asked_for(anon):
    response = anon.post("/login", data={"email": "a@example.com", "password": PASSWORD, "next": "/accounts"})
    assert response.headers["location"] == "/accounts"


@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example/", "/\\evil.example", "accounts"])
def test_login_never_redirects_off_site(anon, target):
    response = anon.post("/login", data={"email": "a@example.com", "password": PASSWORD, "next": target})
    assert response.headers["location"] == "/"


def test_wrong_password_and_unknown_email_look_the_same(anon):
    wrong = anon.post("/login", data={"email": "a@example.com", "password": "wrong-password-123"})
    unknown = anon.post("/login", data={"email": "nobody@example.com", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 400
    assert "match" in wrong.text and "match" in unknown.text
    assert "set-cookie" not in wrong.headers
    assert anon.get("/").status_code == 303


def test_cookie_is_marked_secure_when_configured(anon, monkeypatch):
    monkeypatch.setenv("NORTHSTAR_COOKIE_SECURE", "1")
    response = anon.post("/login", data={"email": "a@example.com", "password": PASSWORD})
    assert "secure" in response.headers["set-cookie"].lower()


def test_logout_ends_the_session_on_the_server(anon):
    anon.post("/login", data={"email": "a@example.com", "password": PASSWORD})
    token = anon.cookies.get("northstar_session")
    assert anon.post("/logout").headers["location"] == "/login"
    anon.cookies.set("northstar_session", token)          # replaying the old cookie must not work
    assert anon.get("/").status_code == 303


def test_signed_in_pages_show_the_user_and_sign_out(client):
    page = client.get("/").text
    assert "Test User" in page and 'action="/logout"' in page


def test_login_page_while_signed_in_goes_home(client):
    assert client.get("/login", follow_redirects=False).status_code == 303


def test_garbage_cookie_is_signed_out(anon):
    anon.cookies.set("northstar_session", "garbage")
    assert anon.get("/").status_code == 303


@pytest.fixture
def built_app(anon_client, tmp_path, monkeypatch):
    """A client for an app that has the React bundle built, so people land in it after signing in."""
    spa = tmp_path / "spa"
    spa.mkdir()
    (spa / "index.html").write_text("<!doctype html><title>Northstar</title>")
    monkeypatch.setattr("northstar.web.app.SPA_DIR", spa)
    client = TestClient(create_app(tmp_path / "built.db"), follow_redirects=False)
    with with_db(client) as conn:
        users.create_user(conn, "a@example.com", "Test A", PASSWORD)
    return client


def test_with_the_react_app_built_login_lands_in_it(built_app):
    response = built_app.post("/login", data={"email": "a@example.com", "password": PASSWORD})
    assert response.headers["location"] == "/app/"


def test_a_signed_out_visit_to_the_site_root_lands_in_the_react_app_after_login(built_app):
    next_path = built_app.get("/").headers["location"].split("next=")[1]
    assert next_path == "%2F"
    response = built_app.post("/login", data={"email": "a@example.com", "password": PASSWORD, "next": "/"})
    assert response.headers["location"] == "/app/"


def test_with_the_react_app_built_login_still_returns_to_a_page_asked_for(built_app):
    response = built_app.post("/login", data={"email": "a@example.com", "password": PASSWORD, "next": "/accounts"})
    assert response.headers["location"] == "/accounts"


def test_with_the_react_app_built_nothing_unsafe_redirects_off_site_either(built_app):
    response = built_app.post("/login", data={"email": "a@example.com", "password": PASSWORD, "next": "//evil.example/"})
    assert response.headers["location"] == "/app/"


def test_with_the_react_app_built_the_login_page_when_signed_in_goes_to_it(built_app):
    built_app.post("/login", data={"email": "a@example.com", "password": PASSWORD})
    assert built_app.get("/login").headers["location"] == "/app/"
