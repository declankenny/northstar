"""Security headers on every response, and the guards that keep the content security policy true.

The policy has no 'unsafe-inline' for scripts or styles, so the pages must not contain inline scripts,
style attributes in HTML, style blocks or event handler attributes. The static tests read the HTML
entry points so a later change cannot quietly break that.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from northstar import users
from northstar.web.app import create_app

from conftest import sign_in, with_db

ROOT = Path(__file__).resolve().parents[1]
PAGES = [ROOT / "frontend" / "index.html", *sorted((ROOT / "northstar" / "web" / "templates").glob("*.html"))]

EXPECTED = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
}


def directives(policy: str) -> dict[str, list[str]]:
    parsed = {}
    for part in policy.split(";"):
        words = part.split()
        if words:
            parsed[words[0]] = words[1:]
    return parsed


@pytest.fixture
def built(tmp_path, monkeypatch):
    """A signed-in client for an app with a (fake) React build."""
    spa = tmp_path / "spa"
    (spa / "assets").mkdir(parents=True)
    (spa / "index.html").write_text("<!doctype html><title>Northstar</title>")
    (spa / "assets" / "app.js").write_text("console.log('app')")
    monkeypatch.setattr("northstar.web.app.SPA_DIR", spa)
    return sign_in(TestClient(create_app(tmp_path / "web.db"), follow_redirects=False))


def signed_out(built):
    return TestClient(built.app, follow_redirects=False)


# (description, how to ask)
RESPONSES = [
    ("the sign-in page", lambda c: signed_out(c).get("/login")),
    ("a refused sign-in", lambda c: signed_out(c).post("/login", data={"email": "x@example.com", "password": "wrong-password-123"})),
    ("the sign-in stylesheet", lambda c: signed_out(c).get("/static/login.css")),
    ("the theme script", lambda c: signed_out(c).get("/static/theme.js")),
    ("a redirect to sign-in", lambda c: signed_out(c).get("/dashboard")),
    ("the API signed out (401)", lambda c: signed_out(c).get("/api/networth")),
    ("the API signed in", lambda c: c.get("/api/networth")),
    ("an API address that does not exist (404)", lambda c: c.get("/api/nope")),
    ("a page of the app", lambda c: c.get("/dashboard")),
    ("the site root redirect", lambda c: c.get("/")),
    ("a build file", lambda c: c.get("/assets/app.js")),
    ("a missing build file (404)", lambda c: c.get("/assets/missing.js")),
]


@pytest.mark.parametrize("what, ask", RESPONSES, ids=[r[0] for r in RESPONSES])
def test_every_response_has_the_security_headers(built, what, ask):
    response = ask(built)
    for name, value in EXPECTED.items():
        assert response.headers.get(name) == value, f"{name} on {what}"
    assert "camera=()" in response.headers["permissions-policy"] and "geolocation=()" in response.headers["permissions-policy"]
    assert "content-security-policy" in response.headers, what


def test_the_content_security_policy_is_strict(built):
    policy = directives(built.get("/dashboard").headers["content-security-policy"])
    assert policy["default-src"] == ["'self'"]
    assert policy["script-src"] == ["'self'"]
    assert policy["style-src"] == ["'self'"]
    assert policy["object-src"] == ["'none'"]
    assert policy["base-uri"] == ["'self'"]
    assert policy["form-action"] == ["'self'"]
    assert policy["frame-ancestors"] == ["'none'"]
    assert policy["connect-src"] == ["'self'"]
    everything = built.get("/dashboard").headers["content-security-policy"]
    assert "unsafe-inline" not in everything and "unsafe-eval" not in everything and "*" not in everything
    assert "data:" not in everything and "http:" not in everything


def test_the_headers_are_the_same_on_every_response(built):
    seen = {built.get(path).headers["content-security-policy"] for path in ("/dashboard", "/api/networth", "/api/nope")}
    seen.add(signed_out(built).get("/login").headers["content-security-policy"])
    assert len(seen) == 1


def test_a_header_a_route_set_itself_is_not_overwritten():
    from fastapi import FastAPI, Response
    from northstar.web import security_headers

    app = FastAPI()
    security_headers.install(app)

    @app.get("/own")
    def own(response: Response):
        response.headers["Referrer-Policy"] = "no-referrer"
        return {}

    got = TestClient(app).get("/own")
    assert got.headers["referrer-policy"] == "no-referrer"          # the route's own value stays
    assert got.headers["x-content-type-options"] == "nosniff"       # the rest are filled in


def test_hsts_is_left_to_the_reverse_proxy(built):
    """The app may be served over plain HTTP in a trial, where HSTS would be wrong and could lock a browser out."""
    assert "strict-transport-security" not in built.get("/dashboard").headers


# -- what the policy needs the pages to be --

@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_no_page_has_an_inline_script(page):
    html = page.read_text(encoding="utf-8")
    for tag in re.findall(r"<script\b[^>]*>", html, flags=re.I):
        assert re.search(r"\bsrc\s*=", tag, flags=re.I), f"{page.name} has an inline script: {tag}"


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
def test_no_page_has_inline_styles_or_event_handlers(page):
    html = page.read_text(encoding="utf-8")
    assert not re.search(r"<style\b", html, flags=re.I), f"{page.name} has a style block"
    assert not re.search(r"\sstyle\s*=", html, flags=re.I), f"{page.name} has a style attribute"
    assert not re.search(r"\son[a-z]+\s*=", html, flags=re.I), f"{page.name} has an event handler attribute"
    assert "javascript:" not in html.lower()


def test_both_entry_points_load_the_one_shared_theme_script():
    for page in (ROOT / "frontend" / "index.html", ROOT / "northstar" / "web" / "templates" / "login.html"):
        assert '<script src="/static/theme.js"></script>' in page.read_text(encoding="utf-8"), page.name


def test_the_theme_script_is_public_javascript_that_applies_the_saved_theme(built):
    response = signed_out(built).get("/static/theme.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "northstar-theme" in response.text and "dataset.theme" in response.text
    assert "<script" not in response.text
