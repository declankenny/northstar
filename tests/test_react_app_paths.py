import pytest
from fastapi.testclient import TestClient

from northstar import users
from northstar.web.app import create_app

from conftest import sign_in, with_db, op

PAGES = ["/dashboard", "/accounts", "/accounts/12", "/balance-update", "/types", "/users", "/profile", "/nope"]


@pytest.fixture
def built(tmp_path, monkeypatch):
    """An app with a (fake) React build: an index page and one script."""
    spa = tmp_path / "spa"
    (spa / "assets").mkdir(parents=True)
    (spa / "index.html").write_text("<!doctype html><title>Northstar</title>")
    (spa / "assets" / "app.js").write_text("console.log('app')")
    monkeypatch.setattr("northstar.web.app.SPA_DIR", spa)
    return sign_in(TestClient(create_app(tmp_path / "web.db"), follow_redirects=False))


@pytest.mark.parametrize("path", PAGES)
def test_every_page_address_serves_the_app(built, path):
    page = built.get(path)
    assert page.status_code == 200 and "<title>Northstar</title>" in page.text


def test_the_site_root_goes_to_the_dashboard(built):
    response = built.get("/")
    assert response.status_code == 303 and response.headers["location"] == "/dashboard"


def test_build_files_are_served_as_files(built):
    script = built.get("/assets/app.js")
    assert script.status_code == 200 and "console.log" in script.text and "<title>" not in script.text


def test_a_missing_build_file_is_a_404_not_the_apps_page(built):
    assert built.get("/assets/missing.js").status_code == 404


@pytest.mark.parametrize("path", ["/api/nope", "/api", "/login/extra", "/logout/extra", "/static/missing.css"])
def test_server_addresses_that_do_not_exist_are_404_not_the_apps_page(built, path):
    response = built.get(path)
    assert response.status_code == 404 and "<title>" not in response.text


def test_the_api_still_answers_json_next_to_the_page_fallback(built):
    assert built.get("/api/networth").status_code == 200
    assert built.get("/login").status_code == 303        # signed in: sign-in goes to the Dashboard


def test_nothing_outside_the_build_folder_is_served(built):
    assert "root:" not in built.get("/..%2f..%2f..%2fetc/passwd").text
    assert built.get("/%2e%2e/%2e%2e/pyproject.toml").text.startswith("<!doctype html>")


@pytest.mark.parametrize("path", PAGES + ["/assets/app.js"])
def test_signed_out_visitors_are_sent_to_sign_in_and_back(tmp_path, monkeypatch, path):
    spa = tmp_path / "spa"
    (spa / "assets").mkdir(parents=True)
    (spa / "index.html").write_text("<!doctype html><title>Northstar</title>")
    (spa / "assets" / "app.js").write_text("x")
    monkeypatch.setattr("northstar.web.app.SPA_DIR", spa)
    anon = TestClient(create_app(tmp_path / "web.db"), follow_redirects=False)
    with with_db(anon) as conn:
        users.create_user(op(conn), "a@example.com", "Test A", "synthetic-pass-123")
    response = anon.get(path)
    assert response.status_code == 303 and response.headers["location"].startswith("/login?next=")
    back = anon.post("/login", data={"email": "a@example.com", "password": "synthetic-pass-123", "next": path})
    assert back.headers["location"] == path


def test_without_a_build_there_are_no_page_addresses_and_the_api_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr("northstar.web.app.SPA_DIR", tmp_path / "missing")
    client = sign_in(TestClient(create_app(tmp_path / "web.db")))
    assert client.get("/dashboard").status_code == 404
    assert client.get("/api/networth").status_code == 200
