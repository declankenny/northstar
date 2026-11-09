"""OIDC sign-in through the web app (northstar/web/oidc_routes.py): the two public routes, the cookies, what the sign-in page is
told, the check on every request that ends a session when the provider settings change, the refusal of password sign-in when it
is off, and the limits. The provider is a fake HTTP server (tests/fake_provider.py). Synthetic data only."""

import logging
import time
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from northstar import db, identities, oidc, throttle, users
from northstar.web.app import create_app
from tests.conftest import op, sign_in
from tests.fake_provider import ACCESS_TOKEN, CLIENT_ID, CLIENT_SECRET, FakeProvider

PUBLIC_URL = "http://localhost:8765"
PASSWORD = "a-long-test-password"
PROTECTED = "/api/version"


@pytest.fixture
def provider():
    fake = FakeProvider()
    yield fake
    fake.close()


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    oidc.reset_cache()
    for name in ("NORTHSTAR_OIDC_CLIENT_SECRET_FILE", "NORTHSTAR_COOKIE_SECURE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NORTHSTAR_OIDC_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("NORTHSTAR_PUBLIC_URL", PUBLIC_URL)
    yield
    oidc.reset_cache()


def set_property(web, name, value):
    with db.connect(web.app.state.db_path) as conn:
        conn.execute("UPDATE system_properties SET value = ? WHERE name = ?", (value, name))


def configure(web, provider, *, creation=True):
    for name, value in (("oidc.issuer", provider.issuer), ("oidc.client_id", CLIENT_ID), ("oidc.enabled", "true"),
                        ("oidc.user.allow_creation", "true" if creation else "false")):
        set_property(web, name, value)


@pytest.fixture
def web(tmp_path, provider):
    client = TestClient(create_app(tmp_path / "web.db"), follow_redirects=False)
    configure(client, provider)
    return client


def query(conn_or_web, sql, *args):
    with db.connect(conn_or_web.app.state.db_path) as conn:
        return conn.execute(sql, args).fetchall()


def add_user(web, email="alex@example.test", name="Alex", admin=False):
    with db.connect(web.app.state.db_path) as conn:
        return users.create_user(op(conn), email, name, PASSWORD, admin)


def start(web, next="/accounts"):
    return web.get("/api/auth/oidc/login", params={"next": next})


def sign_in_through(web, provider, claims=None, next="/accounts", **options):
    """What a browser does: start, go to the provider, come back. Returns both responses."""
    begun = start(web, next)
    assert begun.status_code == 302, begun.headers
    code, params = provider.authorize(begun.headers["location"], claims, **options)
    returned = web.get("/api/auth/oidc/callback", params={"code": code, "state": params["state"]})
    return begun, returned


def refused_code(returned):
    assert returned.status_code == 303, returned.text
    location = urllib.parse.urlsplit(returned.headers["location"])
    assert location.path == "/login", location
    return urllib.parse.parse_qs(location.query)["oidc_error"][0]


def cookie_lines(response):
    return [line.lower() for line in response.headers.get_list("set-cookie")]


# -- starting --

def test_starting_sends_the_browser_to_the_provider_with_a_binding_cookie(web, provider):
    response = start(web)
    assert response.status_code == 302
    assert response.headers["location"].startswith(provider.issuer + "/authorize?")
    assert response.headers["cache-control"] == "no-store"
    (cookie,) = cookie_lines(response)
    assert cookie.startswith("northstar_oidc=") and "httponly" in cookie and "samesite=lax" in cookie
    assert "max-age=600" in cookie and "path=/api/auth/oidc" in cookie and "secure" not in cookie


def test_the_binding_cookie_is_secure_when_the_deployment_says_so(web, monkeypatch):
    monkeypatch.setenv("NORTHSTAR_COOKIE_SECURE", "1")
    assert "secure" in cookie_lines(start(web))[0]


def test_starting_needs_no_sign_in_and_nothing_else_under_it_is_public(web):
    assert start(web).status_code == 302
    assert web.get("/api/auth/oidc/other").status_code == 401
    assert web.post("/api/auth/oidc/callback").status_code == 405
    assert web.get("/api/auth/oidc").status_code == 401


def test_the_sign_in_page_still_loads_with_an_error_code_in_its_address(anon_spa_client):
    assert anon_spa_client.get("/login", params={"oidc_error": "not_allowed"}).status_code == 200


@pytest.mark.parametrize("next", ["https://evil.example.test/x", "//evil.example.test", "/\\evil.example.test", "/\t/evil.example.test"])
def test_a_return_address_that_leaves_the_site_goes_to_the_dashboard(web, provider, next):
    _, returned = sign_in_through(web, provider, next=next)
    assert returned.headers["location"] == "/dashboard"


def test_a_safe_return_address_is_kept(web, provider):
    _, returned = sign_in_through(web, provider, next="/accounts?filter=open")
    assert returned.headers["location"] == "/accounts?filter=open"


@pytest.mark.parametrize("change, code", [
    (lambda web, provider: set_property(web, "oidc.enabled", "false"), "not_configured"),
    (lambda web, provider: set_property(web, "oidc.issuer", None), "not_configured"),
    (lambda web, provider: setattr(provider, "discovery_status", 500), "provider_unavailable"),
    (lambda web, provider: provider.close(), "provider_unavailable")])
def test_a_start_that_cannot_be_made_goes_back_to_the_sign_in_page_with_the_reason(web, provider, change, code):
    change(web, provider)
    response = start(web)
    assert refused_code(response) == code
    assert query(web, "SELECT COUNT(*) FROM sys_login_transactions")[0][0] == 0
    assert not any(line.startswith("northstar_oidc=") and "max-age=600" in line for line in cookie_lines(response))


# -- the whole sign-in --

def test_a_sign_in_sets_the_session_cookie_for_the_configured_lifetime_and_goes_where_asked(web, provider):
    begun, returned = sign_in_through(web, provider)
    assert returned.status_code == 303 and returned.headers["location"] == "/accounts"
    assert returned.headers["cache-control"] == "no-store"
    lines = cookie_lines(returned)
    session = next(line for line in lines if line.startswith("northstar_session="))
    assert "httponly" in session and "samesite=lax" in session and "max-age=43200" in session
    assert any(line.startswith("northstar_oidc=") and "max-age=0" in line for line in lines)       # the binding cookie is removed
    assert web.get(PROTECTED).status_code == 200
    row = query(web, "SELECT auth_method, config_fingerprint FROM sys_sessions")[0]
    assert row["auth_method"] == "oidc" and row["config_fingerprint"] is not None


def test_the_lifetime_follows_the_setting(web, provider):
    set_property(web, "oidc.session.lifetime_hours", "2")
    _, returned = sign_in_through(web, provider)
    assert "max-age=7200" in next(line for line in cookie_lines(returned) if line.startswith("northstar_session="))


def test_an_existing_user_is_linked_by_a_verified_email(web, provider):
    alex = add_user(web, admin=True)
    sign_in_through(web, provider)
    assert [tuple(r) for r in query(web, "SELECT user_id FROM user_identities")] == [(alex,)]
    assert query(web, "SELECT COUNT(*) FROM users WHERE is_system = 0")[0][0] == 1


def test_any_session_this_browser_had_is_ended_and_replaced(web, provider):
    add_user(web, "other@example.test", "Other")
    web.post("/api/auth/login", json={"email": "other@example.test", "password": PASSWORD})
    before = {row["token_hash"] for row in query(web, "SELECT token_hash FROM sys_sessions")}
    assert len(before) == 1
    sign_in_through(web, provider)
    after = query(web, "SELECT token_hash, auth_method FROM sys_sessions")
    assert len(after) == 1 and after[0]["token_hash"] not in before and after[0]["auth_method"] == "oidc"


def test_a_return_cannot_be_replayed(web, provider):
    begun = start(web)
    code, params = provider.authorize(begun.headers["location"])
    arguments = {"code": code, "state": params["state"]}
    assert web.get("/api/auth/oidc/callback", params=arguments).status_code == 303
    web.cookies.clear()
    web.cookies.set("northstar_oidc", "whatever")
    replay = web.get("/api/auth/oidc/callback", params=arguments)
    assert refused_code(replay) == "expired"
    assert query(web, "SELECT COUNT(*) FROM sys_sessions")[0][0] == 1


def test_a_return_without_the_binding_cookie_is_refused_and_uses_the_login_up(web, provider):
    begun = start(web)
    code, params = provider.authorize(begun.headers["location"])
    binding = web.cookies.get("northstar_oidc")
    web.cookies.clear()
    assert refused_code(web.get("/api/auth/oidc/callback", params={"code": code, "state": params["state"]})) == "expired"
    web.cookies.set("northstar_oidc", binding)
    assert refused_code(web.get("/api/auth/oidc/callback", params={"code": code, "state": params["state"]})) == "expired"
    assert query(web, "SELECT COUNT(*) FROM sys_sessions")[0][0] == 0


def test_a_return_for_a_login_begun_under_other_settings_is_refused(web, provider):
    begun = start(web)
    code, params = provider.authorize(begun.headers["location"])
    set_property(web, "oidc.client_id", "another-client")
    assert refused_code(web.get("/api/auth/oidc/callback", params={"code": code, "state": params["state"]})) in ("expired", "not_configured")
    assert query(web, "SELECT COUNT(*) FROM sys_sessions")[0][0] == 0


@pytest.mark.parametrize("state", [None, "", "not-a-state"])
def test_a_return_with_no_known_state_is_refused(web, state):
    arguments = {"code": "c"} | ({"state": state} if state is not None else {})
    assert refused_code(web.get("/api/auth/oidc/callback", params=arguments)) == "expired"


# -- what the sign-in page is told --

@pytest.mark.parametrize("claims, options, code", [
    ({"email_verified": False}, {}, "email_unverified"),
    ({"email_verified": None}, {}, "email_unverified"),
    ({"email": None}, {}, "email_unverified"),
    ({"nonce": None}, {}, "invalid_token"),
    ({}, {"nonce": "a-nonce-this-login-never-sent"}, "invalid_token"),
    ({"aud": "another-client"}, {}, "invalid_token"),
    ({"iss": "https://evil.example.test"}, {}, "invalid_token"),
    ({"exp": int(time.time()) - 3600}, {}, "invalid_token"),
    ({}, {"alg": "none"}, "invalid_token"),
    ({}, {"alg": "HS256"}, "invalid_token"),
    ({}, {"kid": "unknown-key"}, "invalid_token")])
def test_a_token_or_a_claim_that_is_not_acceptable_goes_back_with_a_fixed_code(web, provider, claims, options, code):
    _, returned = sign_in_through(web, provider, claims, **options)
    assert refused_code(returned) == code
    assert returned.headers["location"] == f"/login?oidc_error={code}"
    assert query(web, "SELECT COUNT(*) FROM sys_sessions")[0][0] == 0
    assert query(web, "SELECT COUNT(*) FROM users WHERE is_system = 0")[0][0] == 0
    assert not any(line.startswith("northstar_session=") for line in cookie_lines(returned))


def test_someone_who_may_not_come_in_is_told_so_in_one_way(web, provider):
    configure(web, provider, creation=False)
    _, returned = sign_in_through(web, provider)
    assert refused_code(returned) == "not_allowed"
    gone = add_user(web, "alex@example.test")
    boss = add_user(web, "boss@example.test", admin=True)
    with db.connect(web.app.state.db_path) as conn:
        users.delete_user(op(conn), gone, boss)
    _, again = sign_in_through(web, provider)
    assert refused_code(again) == "not_allowed"


def test_a_provider_that_fails_sends_the_person_back_with_a_fixed_code(web, provider):
    provider.token_status = 500
    _, returned = sign_in_through(web, provider)
    assert refused_code(returned) == "provider_unavailable"


@pytest.mark.parametrize("error, code", [("access_denied", "cancelled"), ("server_error", "provider_unavailable"),
                                        ("temporarily_unavailable", "provider_unavailable")])
def test_an_error_from_the_provider_ends_the_login_and_goes_back_with_a_code(web, provider, error, code):
    begun = start(web)
    _, params = provider.authorize(begun.headers["location"])
    returned = web.get("/api/auth/oidc/callback", params={"error": error, "state": params["state"],
                                                          "error_description": "words from the provider"})
    assert refused_code(returned) == code
    assert "words" not in returned.headers["location"]
    assert query(web, "SELECT COUNT(*) FROM sys_login_transactions")[0][0] == 0


# -- what is never kept or shown --

def test_no_secret_token_or_code_is_logged_shown_or_kept(web, provider, caplog):
    add_user(web, "alex@example.test", admin=True)
    with caplog.at_level(logging.DEBUG):
        begun = start(web)
        code, params = provider.authorize(begun.headers["location"])
        bad = provider.authorize(begun.headers["location"], {"aud": "another-client"})
        returned = web.get("/api/auth/oidc/callback", params={"code": code, "state": params["state"]})
        provider.token_status = 500
        failed = sign_in_through(web, provider)[1]
    id_token = provider.id_token(params, {})
    # What the application logs. The test client's own request log is not the application's.
    logged = " ".join(record.getMessage() for record in caplog.records if not record.name.startswith(("httpx", "httpcore")))
    assert "OIDC sign-in" in logged        # the failure was logged, so the check below means something
    for secret in (CLIENT_SECRET, ACCESS_TOKEN, id_token, code, params["state"], params["nonce"], bad[0]):
        assert secret not in logged, "a secret reached the log"
        for response in (returned, failed):
            assert secret not in response.text and secret not in str(response.headers.get("location"))
    with db.connect(web.app.state.db_path) as conn:
        dump = " ".join(conn.iterdump())
    assert CLIENT_SECRET not in dump and ACCESS_TOKEN not in dump and id_token not in dump


# -- every request checks the provider settings --

def sign_in_oidc(web, provider):
    add_user(web, "alex@example.test", admin=True)
    sign_in_through(web, provider)
    assert web.get(PROTECTED).status_code == 200


@pytest.mark.parametrize("name, value", [
    ("oidc.issuer", "https://other.example.test"), ("oidc.client_id", "another-client"), ("oidc.enabled", "false")])
def test_changing_the_provider_or_turning_oidc_off_ends_its_sessions_for_good(web, provider, name, value):
    sign_in_oidc(web, provider)
    original = query(web, "SELECT value FROM system_properties WHERE name = ?", name)[0][0]
    set_property(web, name, value)
    assert web.get(PROTECTED).status_code == 401
    assert query(web, "SELECT COUNT(*) FROM sys_sessions")[0][0] == 0
    set_property(web, name, original)
    assert web.get(PROTECTED).status_code == 401      # putting the settings back does not bring the session back


def test_a_changed_secret_or_lifetime_or_creation_switch_ends_nothing(web, provider, monkeypatch):
    sign_in_oidc(web, provider)
    monkeypatch.setenv("NORTHSTAR_OIDC_CLIENT_SECRET", "a-rotated-secret")
    set_property(web, "oidc.session.lifetime_hours", "1")
    set_property(web, "oidc.user.allow_creation", "false")
    set_property(web, "oidc.provider", "Pocket ID")
    assert web.get(PROTECTED).status_code == 200


def test_a_local_session_is_not_touched_by_the_provider_settings(tmp_path, provider):
    local = sign_in(TestClient(create_app(tmp_path / "local.db")))
    configure(local, provider)
    assert local.get(PROTECTED).status_code == 200
    set_property(local, "oidc.enabled", "false")
    set_property(local, "oidc.issuer", "https://other.example.test")
    assert local.get(PROTECTED).status_code == 200


# -- password sign-in switched off --

def test_password_sign_in_is_refused_at_the_endpoint_when_it_is_off_before_anything_is_checked_or_counted(web):
    add_user(web, "alex@example.test", admin=True)
    set_property(web, "system.auth.local.enabled", "false")
    response = web.post("/api/auth/login", json={"email": "alex@example.test", "password": PASSWORD})
    assert response.status_code == 403 and "turned off" in response.json()["detail"]
    assert "northstar_session" not in response.headers.get("set-cookie", "")
    assert query(web, "SELECT COUNT(*) FROM sys_login_attempts")[0][0] == 0
    assert query(web, "SELECT COUNT(*) FROM sys_sessions")[0][0] == 0
    set_property(web, "system.auth.local.enabled", "true")
    assert web.post("/api/auth/login", json={"email": "alex@example.test", "password": PASSWORD}).status_code == 200


def test_turning_password_sign_in_off_does_not_end_a_password_session(web):
    add_user(web, "alex@example.test", admin=True)
    web.post("/api/auth/login", json={"email": "alex@example.test", "password": PASSWORD})
    set_property(web, "system.auth.local.enabled", "false")
    assert web.get(PROTECTED).status_code == 200


def test_a_person_with_no_password_cannot_sign_in_with_one(web, provider):
    sign_in_through(web, provider)
    web.cookies.clear()
    response = web.post("/api/auth/login", json={"email": "alex@example.test", "password": PASSWORD})
    assert response.status_code == 400 and response.json()["detail"] == "That email and password don't match."


# -- limits --

def test_starting_sign_ins_over_and_over_is_limited(web):
    codes = [start(web).status_code for _ in range(throttle.PAIR_LIMIT)]
    assert codes == [302] * throttle.PAIR_LIMIT
    assert refused_code(start(web)) == "throttled"


def test_returns_that_are_not_a_login_in_progress_are_limited_and_a_success_would_clear_them(web, provider):
    for _ in range(throttle.PAIR_LIMIT):
        assert refused_code(web.get("/api/auth/oidc/callback", params={"code": "c", "state": "s"})) == "expired"
    assert refused_code(web.get("/api/auth/oidc/callback", params={"code": "c", "state": "s"})) == "throttled"


def forget_starts(web):
    """Starts are counted until a sign-in succeeds, which an outage never does: take them out so only returns are tested."""
    with db.connect(web.app.state.db_path) as conn:
        conn.execute("DELETE FROM sys_login_attempts WHERE email_hash = ?", (throttle.hash_value("oidc", "start"),))


def test_a_provider_outage_is_not_counted_against_the_visitor(web, provider, monkeypatch):
    monkeypatch.setattr(throttle, "PAIR_LIMIT", 3)
    provider.token_status = 500
    for _ in range(throttle.PAIR_LIMIT + 2):
        forget_starts(web)
        assert refused_code(sign_in_through(web, provider)[1]) == "provider_unavailable"
    provider.token_status = 200
    forget_starts(web)
    assert sign_in_through(web, provider)[1].headers["location"] == "/accounts"


def test_an_invalid_token_is_counted_against_the_visitor(web, provider, monkeypatch):
    monkeypatch.setattr(throttle, "PAIR_LIMIT", 3)
    for _ in range(throttle.PAIR_LIMIT):
        forget_starts(web)
        assert refused_code(sign_in_through(web, provider, alg="none")[1]) == "invalid_token"
    forget_starts(web)
    assert refused_code(sign_in_through(web, provider)[1]) == "throttled"


def test_the_return_address_kept_with_a_login_is_checked_again_when_it_comes_back(web, provider):
    begun = start(web, "/accounts")
    with db.connect(web.app.state.db_path) as conn:
        conn.execute("UPDATE sys_login_transactions SET return_path = ?", ("https://evil.example.test/x",))
    code, params = provider.authorize(begun.headers["location"])
    returned = web.get("/api/auth/oidc/callback", params={"code": code, "state": params["state"]})
    assert returned.status_code == 303 and returned.headers["location"] == "/dashboard"


def test_a_person_who_may_not_come_in_is_not_counted_either(web, provider, monkeypatch):
    configure(web, provider, creation=False)
    monkeypatch.setattr(throttle, "PAIR_LIMIT", 50)
    for _ in range(10):
        assert refused_code(sign_in_through(web, provider)[1]) == "not_allowed"


def test_a_good_sign_in_clears_the_counts(web, provider):
    for _ in range(throttle.PAIR_LIMIT - 1):
        start(web)
    sign_in_through(web, provider)
    web.cookies.clear()
    assert [start(web).status_code for _ in range(throttle.PAIR_LIMIT - 1)] == [302] * (throttle.PAIR_LIMIT - 1)


def test_oidc_and_password_sign_in_do_not_use_up_each_others_allowance(web):
    """What a visitor types as an email cannot be the key of the OIDC counts: they are counted under their own kind."""
    for key in ("start", "return", "oidc:start", "oidc:return"):
        for _ in range(throttle.PAIR_LIMIT + 1):
            web.post("/api/auth/login", json={"email": key, "password": "wrong-password-12"})
    assert start(web).status_code == 302
    assert refused_code(web.get("/api/auth/oidc/callback", params={"code": "c", "state": "s"})) == "expired"
    for _ in range(throttle.PAIR_LIMIT):
        start(web)
    add_user(web, "alex@example.test")
    assert web.post("/api/auth/login", json={"email": "alex@example.test", "password": PASSWORD}).status_code == 200
