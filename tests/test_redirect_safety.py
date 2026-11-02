"""Where a sign-in may send a person back to (`next`), and which files the page route may touch.

The scanner flagged both as taking an address from the request. The inputs below are the hostile ones: the checks
must hold for each of them, and not only because a library happens to encode what they let through."""

import os
import pathlib

import pytest
from fastapi.testclient import TestClient

from northstar import users
from northstar.web.app import create_app
from northstar.web.auth_routes import LANDING, safe_next

from conftest import sign_in, with_db, op

# -- next --

@pytest.mark.parametrize("target", ["/accounts", "/accounts/12", "/balance-update", "/accounts/12?tab=history",
                                    "/a%20b", "/%2f/still-a-path", "/@still-a-path", "/profile#top"])
def test_a_path_on_this_site_is_kept(target):
    assert safe_next(target) == target


@pytest.mark.parametrize("target", [
    "", "/", "evil.com", "http://evil.com", "https://evil.com/x", "javascript:alert(1)", "//evil.com", "///evil.com",
    "/\evil.com", "\\evil.com", "/\t/evil.com", "/\n/evil.com", "/\r\nSet-Cookie: x=1", "/\x00", "/\x7f", "/\x1b[0m",
    " /dashboard", "/dashboard ", "/da shboard", "/ /evil.com", "/ /evil.com",
])
def test_anything_else_goes_to_the_landing_page(target):
    assert safe_next(target) == LANDING


def test_the_result_always_has_no_scheme_and_no_host():
    from urllib.parse import urlsplit
    for target in ["/ok", "http://evil.com", "//evil.com", "/\t/evil.com", "/a?b=http://evil.com", "/x/../../evil"]:
        parts = urlsplit(safe_next(target))
        assert parts.scheme == "" and parts.netloc == ""


def test_a_signed_in_visitor_is_not_sent_off_site_by_the_next_parameter(client):
    for target in ("//evil.com", "/\t/evil.com", "/\n/evil.com", "http://evil.com"):
        response = TestClient(client.app, cookies=client.cookies, follow_redirects=False).get("/login", params={"next": target})
        assert response.status_code == 303 and response.headers["location"] == LANDING


def test_signing_in_does_not_send_a_visitor_off_site(anon_client):
    with with_db(anon_client) as conn:
        users.create_user(op(conn), "a@example.com", "Test A", "synthetic-pass-123")
    for target in ("//evil.com", "/\t/evil.com", "/\r\nSet-Cookie: x=1", "https://evil.com"):
        response = anon_client.post("/login", data={"email": "a@example.com", "password": "synthetic-pass-123", "next": target})
        assert response.status_code == 303 and response.headers["location"] == LANDING


# -- the page route and the file system --

@pytest.fixture
def secret_beside_the_build(tmp_path, monkeypatch):
    """A fake build, and a file just outside it that must never be served."""
    spa = tmp_path / "spa"
    (spa / "assets").mkdir(parents=True)
    (spa / "index.html").write_text("<!doctype html><title>Northstar</title>")
    (spa / "assets" / "app.js").write_text("console.log('app')")
    (tmp_path / "secret.txt").write_text("TOPSECRET")
    monkeypatch.setattr("northstar.web.app.SPA_DIR", spa)
    return sign_in(TestClient(create_app(tmp_path / "web.db"), follow_redirects=False)), spa


HOSTILE = ["/..%2fsecret.txt", "/%2e%2e/secret.txt", "/%2e%2e%2fsecret.txt", "/assets/..%2f..%2fsecret.txt",
           "/assets/%2e%2e/%2e%2e/secret.txt", "/..%5csecret.txt", "/%00", "/a%00b", "/assets/%00.js",
           "/..%252fsecret.txt", "//secret.txt", "/spa/../secret.txt", "/assets/../../secret.txt"]


@pytest.mark.parametrize("path", HOSTILE)
def test_a_path_that_climbs_out_of_the_build_serves_the_app_or_a_404_and_never_the_file(secret_beside_the_build, path):
    client, _ = secret_beside_the_build
    response = client.get(path)
    assert response.status_code in (200, 404, 303, 307, 308) and "TOPSECRET" not in response.text


def test_the_file_system_is_not_asked_about_anything_outside_the_build(secret_beside_the_build, monkeypatch):
    """Whether a file exists is also something an outsider should not be able to probe."""
    client, spa = secret_beside_the_build
    asked = []
    real_isfile, real_is_file = os.path.isfile, pathlib.Path.is_file
    monkeypatch.setattr(os.path, "isfile", lambda path: asked.append(os.path.realpath(path)) or real_isfile(path))
    monkeypatch.setattr(pathlib.Path, "is_file", lambda self, **kw: asked.append(os.path.realpath(self)) or real_is_file(self, **kw))
    for path in HOSTILE:
        client.get(path)
    root = os.path.realpath(spa)
    outside = [path for path in asked if not (path == root or path.startswith(root + os.sep))]
    assert outside == []


def test_files_inside_the_build_are_still_served(secret_beside_the_build):
    client, _ = secret_beside_the_build
    assert "console.log" in client.get("/assets/app.js").text
    assert "<title>Northstar</title>" in client.get("/index.html").text


@pytest.mark.parametrize("path", ["/%00", "/a%00b", "/assets/%00.js", "/assets/app.js%00.png"])
def test_a_path_with_a_null_byte_is_a_404_and_never_an_error(secret_beside_the_build, path):
    """No file name has one. On Linux the file system calls raise ValueError for it, which would be a 500."""
    client, _ = secret_beside_the_build
    response = client.get(path)
    assert response.status_code == 404 and "<title>" not in response.text
