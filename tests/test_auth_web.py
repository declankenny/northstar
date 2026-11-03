import pytest
from northstar import users
from conftest import post_sign_in, with_db, op

PASSWORD = "synthetic-pass-123"


@pytest.fixture
def anon(anon_client):
    with with_db(anon_client) as conn:
        users.create_user(op(conn), "a@example.com", "Test A", PASSWORD)
    return anon_client


@pytest.mark.parametrize("path", ["/", "/dashboard", "/accounts"])
def test_pages_redirect_to_login_when_signed_out(anon, path):
    response = anon.get(path)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


def test_api_answers_401_when_signed_out(anon):
    assert anon.get("/api/networth").status_code == 401


def test_posts_are_refused_when_signed_out(anon):
    response = anon.post("/api/types", json={"name": "X", "class_id": 1, "stale_after_days": 35})
    assert response.status_code == 401
    with with_db(anon) as conn:
        assert conn.execute("SELECT COUNT(*) FROM account_types WHERE name = 'X'").fetchone()[0] == 0


def test_the_sign_in_page_and_the_files_it_is_made_of_are_public(anon_spa_client):
    assert anon_spa_client.get("/login").status_code == 200 and "<title>Northstar</title>" in anon_spa_client.get("/login").text
    assert anon_spa_client.get("/assets/app.js").status_code == 200
    assert anon_spa_client.get("/static/theme.js").status_code == 200


def test_signing_out_needs_a_session_like_every_other_endpoint(anon):
    assert anon.post("/api/auth/logout").status_code == 401


def test_login_sets_a_http_only_cookie_and_opens_the_app(anon):
    response = post_sign_in(anon, "A@example.com", PASSWORD)
    assert response.status_code == 200 and response.json() == {"next": "/dashboard"}
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" not in cookie
    assert anon.get("/").headers["location"] == "/dashboard"      # the site root goes to the Dashboard
    assert anon.get("/api/networth").status_code == 200


def test_login_returns_to_the_page_asked_for(anon):
    assert post_sign_in(anon, "a@example.com", PASSWORD, next="/accounts").json() == {"next": "/accounts"}


@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example/", "/\\evil.example", "accounts"])
def test_login_never_redirects_off_site(anon, target):
    assert post_sign_in(anon, "a@example.com", PASSWORD, next=target).json() == {"next": "/dashboard"}


def test_wrong_password_and_unknown_email_look_the_same(anon):
    wrong = post_sign_in(anon, "a@example.com", "wrong-password-123")
    unknown = post_sign_in(anon, "nobody@example.com", PASSWORD)
    assert wrong.status_code == unknown.status_code == 400
    assert wrong.json() == unknown.json() == {"detail": "That email and password don't match."}
    assert "set-cookie" not in wrong.headers
    assert anon.get("/api/networth").status_code == 401


def test_cookie_is_marked_secure_when_configured(anon, monkeypatch):
    monkeypatch.setenv("NORTHSTAR_COOKIE_SECURE", "1")
    response = post_sign_in(anon, "a@example.com", PASSWORD)
    assert "secure" in response.headers["set-cookie"].lower()


def test_logout_ends_the_session_on_the_server(anon):
    post_sign_in(anon, "a@example.com", PASSWORD)
    token = anon.cookies.get("northstar_session")
    response = anon.post("/api/auth/logout")
    assert response.status_code == 204 and "northstar_session" in response.headers["set-cookie"]
    anon.cookies.set("northstar_session", token)          # replaying the old cookie must not work
    assert anon.get("/api/networth").status_code == 401


def test_the_sign_in_page_while_signed_in_goes_to_the_dashboard(anon_spa_client):
    with with_db(anon_spa_client) as conn:
        users.create_user(op(conn), "a@example.com", "Test A", PASSWORD)
    post_sign_in(anon_spa_client, "a@example.com", PASSWORD)
    response = anon_spa_client.get("/login")
    assert response.status_code == 303 and response.headers["location"] == "/dashboard"


def test_a_body_that_is_not_json_is_refused_without_a_session(anon):
    response = anon.post("/api/auth/login", content="email=a%40example.com&password=x", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert response.status_code == 422 and "set-cookie" not in response.headers


def test_garbage_cookie_is_signed_out(anon):
    anon.cookies.set("northstar_session", "garbage")
    assert anon.get("/api/networth").status_code == 401


def test_a_signed_out_visit_to_the_site_root_lands_on_the_dashboard_after_login(anon):
    next_path = anon.get("/").headers["location"].split("next=")[1]
    assert next_path == "%2F"
    assert post_sign_in(anon, "a@example.com", PASSWORD, next="/").json() == {"next": "/dashboard"}
