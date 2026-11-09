"""The OpenID Connect client (northstar/oidc.py) against a fake provider that is a real HTTP server: what it asks for, what it
refuses and what it never keeps. Synthetic data only."""

import base64
import hashlib
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest

from northstar import config, db, identities, oidc, sessions, users
from northstar.identities import Refused
from tests.conftest import op
from tests.fake_provider import ACCESS_TOKEN, CLIENT_ID, CLIENT_SECRET, FakeProvider, rsa_key

PUBLIC_URL = "http://localhost:8765"
REDIRECT = PUBLIC_URL + "/api/auth/oidc/callback"
NOW = datetime.now(timezone.utc).replace(microsecond=0)      # the fake provider signs with the real clock


def stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
PASSWORD = "a-long-test-password"


@pytest.fixture
def provider():
    fake = FakeProvider()
    yield fake
    fake.close()


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    # The fake provider signs with the real clock, so "now" is taken again at the start of every test.
    monkeypatch.setattr(sys.modules[__name__], "NOW", datetime.now(timezone.utc).replace(microsecond=0))
    oidc.reset_cache()
    for name in ("NORTHSTAR_OIDC_CLIENT_SECRET_FILE", "NORTHSTAR_COOKIE_SECURE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NORTHSTAR_OIDC_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("NORTHSTAR_PUBLIC_URL", PUBLIC_URL)
    yield
    oidc.reset_cache()


@pytest.fixture
def on(conn, provider):
    for name, value in (("oidc.issuer", provider.issuer), ("oidc.client_id", CLIENT_ID), ("oidc.enabled", "true"),
                        ("oidc.user.allow_creation", "true")):
        conn.execute("UPDATE system_properties SET value = ? WHERE name = ?", (value, name))
    return conn


def begin(conn, provider, claims=None, now=None, **options):
    url, binding = oidc.begin_login(conn, "/accounts", now or NOW)
    code, params = provider.authorize(url, claims, **options)
    return code, params, binding


def finish(conn, provider, claims=None, now=None, **options):
    code, params, binding = begin(conn, provider, claims, now, **options)
    return oidc.finish_login(conn, binding, params["state"], code, now or NOW)


def refused(conn, provider, claims=None, now=None, **options):
    with pytest.raises((oidc.ProviderError, oidc.LoginError, Refused)) as raised:
        finish(conn, provider, claims, now, **options)
    return raised.value


# -- the request that sends the browser to the provider --

def test_the_authorization_request_asks_for_a_code_with_pkce_and_the_openid_scopes(on, provider):
    url, binding = oidc.begin_login(on, "/accounts", NOW)
    query = {key: values[0] for key, values in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).items()}
    assert urllib.parse.urlsplit(url).path == "/authorize"
    assert query["response_type"] == "code" and query["client_id"] == CLIENT_ID and query["redirect_uri"] == REDIRECT
    assert query["scope"] == "openid profile email" and query["code_challenge_method"] == "S256"
    assert len(query["state"]) >= 32 and len(query["nonce"]) >= 32 and len(query["code_challenge"]) == 43
    assert len(binding) >= 32 and "client_secret" not in query and CLIENT_SECRET not in url


def test_the_login_in_progress_keeps_the_state_and_binding_only_as_hashes(on, provider):
    url, binding = oidc.begin_login(on, "/accounts", NOW)
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    row = on.execute("SELECT * FROM sys_login_transactions").fetchone()
    assert row["state_hash"] == hashlib.sha256(query["state"].encode()).hexdigest()
    assert row["binding_hash"] == hashlib.sha256(binding.encode()).hexdigest()
    assert row["nonce"] == query["nonce"] and row["return_path"] == "/accounts"
    assert row["config_fingerprint"] == identities.current_fingerprint(on)
    assert row["expires_at"] == stamp(NOW + timedelta(minutes=10))
    stored = " ".join(str(value) for value in tuple(row))
    assert query["state"] not in stored and binding not in stored
    challenge = base64.urlsafe_b64encode(hashlib.sha256(row["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert challenge == query["code_challenge"] and len(row["code_verifier"]) >= 43


def test_expired_transactions_are_removed_when_a_new_one_begins(on, provider):
    oidc.begin_login(on, "/a", NOW)
    oidc.begin_login(on, "/b", NOW + timedelta(hours=1))
    assert [r["return_path"] for r in on.execute("SELECT return_path FROM sys_login_transactions")] == ["/b"]


def test_too_many_logins_in_progress_are_refused(on, provider, monkeypatch):
    monkeypatch.setattr(oidc, "MAX_PENDING", 2)
    oidc.begin_login(on, "/a", NOW)
    oidc.begin_login(on, "/b", NOW)
    with pytest.raises(oidc.LoginError) as raised:
        oidc.begin_login(on, "/c", NOW)
    assert raised.value.code == "busy"


def test_nothing_begins_unless_oidc_is_on_and_fully_set(conn, provider, monkeypatch):
    with pytest.raises(Refused) as raised:
        oidc.begin_login(conn, "/a", NOW)
    assert raised.value.code == identities.NOT_CONFIGURED
    conn.execute("UPDATE system_properties SET value = ? WHERE name = 'oidc.issuer'", (provider.issuer,))
    conn.execute("UPDATE system_properties SET value = ? WHERE name = 'oidc.client_id'", (CLIENT_ID,))
    conn.execute("UPDATE system_properties SET value = 'true' WHERE name = 'oidc.enabled'")
    monkeypatch.delenv("NORTHSTAR_PUBLIC_URL")
    with pytest.raises(Refused):
        oidc.begin_login(conn, "/a", NOW)
    assert conn.execute("SELECT COUNT(*) FROM sys_login_transactions").fetchone()[0] == 0


# -- the whole sign-in --

def test_a_sign_in_creates_a_user_and_a_session_and_gives_back_the_return_path(on, provider):
    result = finish(on, provider)
    assert result.return_path == "/accounts" and result.signed_in.resolved.created
    assert sessions.user_for_token(on, result.signed_in.token, NOW)["email"] == "alex@example.test"
    assert result.signed_in.max_age == 12 * 3600


def test_the_token_request_proves_the_verifier_and_authenticates_with_the_client_secret(on, provider):
    finish(on, provider)
    token_request = next(r for r in provider.requests if r["path"] == "/token")
    assert token_request["method"] == "POST"
    form = token_request["form"]
    assert form["grant_type"] == "authorization_code" and form["redirect_uri"] == REDIRECT and len(form["code_verifier"]) >= 43
    assert "client_secret" not in form and "client_id" not in form
    expected = "Basic " + base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    assert token_request["headers"]["Authorization"] == expected
    assert token_request["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


def test_a_provider_that_wants_the_secret_in_the_body_gets_it_there(on, provider):
    provider.auth_methods = ["client_secret_post"]
    finish(on, provider)
    token_request = next(r for r in provider.requests if r["path"] == "/token")
    assert "Authorization" not in token_request["headers"]
    assert token_request["form"]["client_id"] == CLIENT_ID and token_request["form"]["client_secret"] == CLIENT_SECRET


def test_a_provider_that_lists_no_way_to_use_a_client_secret_is_refused(on, provider):
    provider.auth_methods = ["private_key_jwt", "none"]
    with pytest.raises(oidc.ProviderError) as raised:
        oidc.begin_login(on, "/a", NOW)
    assert raised.value.code == "invalid_response"


def test_no_access_token_is_kept_anywhere(on, provider):
    finish(on, provider)
    dump = " ".join(line for line in on.iterdump())
    assert ACCESS_TOKEN not in dump and CLIENT_SECRET not in dump


def test_the_login_in_progress_is_used_up_by_the_sign_in(on, provider):
    finish(on, provider)
    assert on.execute("SELECT COUNT(*) FROM sys_login_transactions").fetchone()[0] == 0


# -- one use, this browser, in time --

def test_a_return_cannot_be_used_twice(on, provider):
    code, params, binding = begin(on, provider)
    oidc.finish_login(on, binding, params["state"], code, NOW)
    with pytest.raises(oidc.LoginError) as raised:
        oidc.finish_login(on, binding, params["state"], code, NOW)
    assert raised.value.code == "expired"


def test_a_return_from_another_browser_is_refused_and_still_uses_the_login_up(on, provider):
    code, params, binding = begin(on, provider)
    with pytest.raises(oidc.LoginError) as raised:
        oidc.finish_login(on, "not-the-binding-value", params["state"], code, NOW)
    assert raised.value.code == "invalid"
    with pytest.raises(oidc.LoginError) as again:       # the right browser is too late: a failed return consumed it
        oidc.finish_login(on, binding, params["state"], code, NOW)
    assert again.value.code == "expired"
    assert not any(r["path"] == "/token" for r in provider.requests)


@pytest.mark.parametrize("state", [None, "", "wrong", "x" * 500])
def test_an_unknown_or_missing_state_is_refused(on, provider, state):
    code, _, binding = begin(on, provider)
    with pytest.raises(oidc.LoginError) as raised:
        oidc.finish_login(on, binding, state, code, NOW)
    assert raised.value.code == "expired"


@pytest.mark.parametrize("binding", [None, ""])
def test_a_missing_binding_cookie_is_refused(on, provider, binding):
    code, params, _ = begin(on, provider)
    with pytest.raises(oidc.LoginError) as raised:
        oidc.finish_login(on, binding, params["state"], code, NOW)
    assert raised.value.code == "invalid"


@pytest.mark.parametrize("code", [None, "", "c" * 3000])
def test_a_missing_code_is_refused(on, provider, code):
    _, params, binding = begin(on, provider)
    with pytest.raises(oidc.LoginError):
        oidc.finish_login(on, binding, params["state"], code, NOW)


def test_a_login_that_has_run_out_is_refused(on, provider):
    code, params, binding = begin(on, provider)
    with pytest.raises(oidc.LoginError) as raised:
        oidc.finish_login(on, binding, params["state"], code, NOW + timedelta(minutes=10, seconds=1))
    assert raised.value.code == "expired"
    code, params, binding = begin(on, provider, {"exp": int(time.time()) + 3600})
    assert oidc.finish_login(on, binding, params["state"], code, NOW + timedelta(minutes=9, seconds=59))     # just inside


@pytest.mark.parametrize("change", [
    ("oidc.issuer", "https://other.example.test"), ("oidc.client_id", "another-client"), ("oidc.enabled", "false")])
def test_a_login_begun_under_other_settings_is_refused(on, provider, change):
    code, params, binding = begin(on, provider)
    on.execute("UPDATE system_properties SET value = ? WHERE name = ?", (change[1], change[0]))
    with pytest.raises((oidc.LoginError, Refused)):
        oidc.finish_login(on, binding, params["state"], code, NOW)
    assert on.execute("SELECT COUNT(*) FROM users WHERE is_system = 0").fetchone()[0] == 0
    assert not any(r["path"] == "/token" for r in provider.requests)


def test_a_changed_secret_does_not_end_a_login_in_progress(on, provider, monkeypatch):
    code, params, binding = begin(on, provider)
    monkeypatch.setenv("NORTHSTAR_OIDC_CLIENT_SECRET", "a-different-secret")
    with pytest.raises(oidc.ProviderError):          # the provider rejects the new secret: that is the provider's answer
        oidc.finish_login(on, binding, params["state"], code, NOW)


def test_two_returns_at_once_for_one_login_let_exactly_one_in(tmp_path, provider, monkeypatch):
    path = tmp_path / "race.db"
    db.upgrade(path)
    with db.connect(path) as setup:
        for name, value in (("oidc.issuer", provider.issuer), ("oidc.client_id", CLIENT_ID), ("oidc.enabled", "true"),
                            ("oidc.user.allow_creation", "true")):
            setup.execute("UPDATE system_properties SET value = ? WHERE name = ?", (value, name))
        code, params, binding = begin(setup, provider)
    barrier, results = threading.Barrier(2), []

    def attempt():
        connection = db.connect(path)
        try:
            barrier.wait()
            results.append(oidc.finish_login(connection, binding, params["state"], code, NOW))
        except Exception as error:
            results.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(type(result).__name__ for result in results) == ["LoginError", "LoginResult"]
    assert sum(1 for r in provider.requests if r["path"] == "/token") == 1


# -- the ID token --

@pytest.mark.parametrize("claims, options", [
    ({"iss": "https://evil.example.test"}, {}),
    ({"aud": "another-client"}, {}),
    ({"aud": ["x", "y"]}, {}),
    ({"aud": [CLIENT_ID, "other"]}, {}),                                    # several audiences and no authorized party
    ({"aud": [CLIENT_ID, "other"], "azp": "other"}, {}),
    ({"azp": "other"}, {}),
    ({"exp": int(time.time()) - 3600}, {}),
    ({"exp": None}, {}),
    ({"iat": None}, {}),
    ({"iat": int(time.time()) + 3600}, {}),
    ({"nbf": int(time.time()) + 3600}, {}),
    ({"sub": None}, {}),
    ({"sub": ""}, {}),
    ({"sub": 12345}, {}),
    ({"sub": "s" * 256}, {}),
    ({"nonce": None}, {}),
    ({}, {"nonce": "a-nonce-this-login-never-sent"}),
    ({}, {"alg": "none"}),
    ({}, {"alg": "HS256"}),
    ({}, {"alg": "RS512"}),                                                  # an algorithm the provider does not list
    ({}, {"kid": "unknown-key"}),
    ({}, {"key": rsa_key("someone-elses-key")}),                             # signed by a key that is not published
    ({}, {"raw": "not.a.token"}),
    ({}, {"raw": "garbage"}),
])
def test_an_id_token_that_is_not_right_in_any_way_is_refused_and_makes_nobody(on, provider, claims, options):
    failure = refused(on, provider, claims, **options)
    assert isinstance(failure, oidc.ProviderError) and failure.code == "invalid_token"
    assert on.execute("SELECT COUNT(*) FROM users WHERE is_system = 0").fetchone()[0] == 0
    assert on.execute("SELECT COUNT(*) FROM user_identities").fetchone()[0] == 0
    assert on.execute("SELECT COUNT(*) FROM sys_sessions").fetchone()[0] == 0


@pytest.mark.parametrize("raw", ["garbage", "a.b", "a.b.c.d", "a." + "b" * oidc.MAX_TOKEN_CHARS + ".c"])
def test_a_token_of_the_wrong_shape_or_size_is_refused_before_it_is_decoded_or_the_keys_asked_for_again(on, provider, raw,
                                                                                                         monkeypatch):
    def decoder_must_not_run(*args, **kwargs):
        raise AssertionError("the token was handed to the decoder")
    monkeypatch.setattr(oidc.jwt, "decode", decoder_must_not_run)
    failure = refused(on, provider, raw=raw)
    assert isinstance(failure, oidc.ProviderError) and failure.code == "invalid_token"
    assert [r["path"] for r in provider.requests].count("/jwks") == 0


def test_a_token_for_several_audiences_is_accepted_when_the_authorized_party_is_this_client(on, provider):
    assert finish(on, provider, {"aud": [CLIENT_ID, "other"], "azp": CLIENT_ID}).signed_in.resolved.created


def test_a_token_a_minute_either_side_of_the_clock_is_accepted(on, provider):
    assert finish(on, provider, {"exp": int(time.time()) - 30, "iat": int(time.time()) + 30}).signed_in


def test_the_claims_reach_identity_resolution_as_the_token_gave_them(on, provider):
    finish(on, provider, {"sub": "the-subject", "email": "Someone@Example.Test", "name": "Some One"})
    user = on.execute("SELECT email, display_name FROM users WHERE is_system = 0").fetchone()
    assert (user["email"], user["display_name"]) == ("someone@example.test", "Some One")
    assert on.execute("SELECT subject, issuer FROM user_identities").fetchone()[:] == ("the-subject", provider.issuer)


def test_a_verified_email_that_is_not_a_boolean_is_the_identity_layers_to_refuse(on, provider):
    failure = refused(on, provider, {"email_verified": "true"})
    assert isinstance(failure, Refused) and failure.code == identities.EMAIL_UNVERIFIED


def test_a_token_that_signs_in_a_deleted_user_is_refused_by_the_identity_layer(on, provider):
    gone = users.create_user(op(on), "alex@example.test", "Alex", PASSWORD)
    boss = users.create_user(op(on), "boss@example.test", "Boss", PASSWORD, True)
    users.delete_user(op(on), gone, boss)
    assert refused(on, provider).code == identities.NOT_ALLOWED


# -- the keys --

def test_the_discovery_document_and_keys_are_fetched_once_and_kept(on, provider):
    finish(on, provider)
    finish(on, provider, {"sub": "subject-2", "email": "second@example.test"})
    paths = [r["path"] for r in provider.requests]
    assert paths.count("/.well-known/openid-configuration") == 1 and paths.count("/jwks") == 1


def test_they_are_fetched_again_after_an_hour(on, provider, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(oidc, "_monotonic", lambda: clock[0])
    finish(on, provider)
    clock[0] += oidc.METADATA_SECONDS + 1
    finish(on, provider, {"sub": "subject-2", "email": "second@example.test"})
    paths = [r["path"] for r in provider.requests]
    assert paths.count("/.well-known/openid-configuration") == 2 and paths.count("/jwks") == 2


def test_a_rotated_key_is_found_by_asking_the_provider_again_once(on, provider, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(oidc, "_monotonic", lambda: clock[0])
    finish(on, provider)
    clock[0] += oidc.KEYS_REFRESH_SECONDS + 1
    provider.kid = "rotated"
    provider.extra_keys = []
    result = finish(on, provider, {"sub": "subject-2", "email": "second@example.test"})
    assert result.signed_in.resolved.created
    assert [r["path"] for r in provider.requests].count("/jwks") == 2


def test_a_stream_of_tokens_with_unknown_keys_does_not_make_northstar_fetch_without_limit(on, provider, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(oidc, "_monotonic", lambda: clock[0])
    finish(on, provider)
    for _ in range(5):
        clock[0] += 2
        assert refused(on, provider, {}, kid="unknown-key").code == "invalid_token"
    assert [r["path"] for r in provider.requests].count("/jwks") == 1


# -- what the provider says about itself --

def test_a_discovery_document_for_another_issuer_is_refused(on, provider):
    provider.discovery_issuer = "https://someone-else.example.test"
    with pytest.raises(oidc.ProviderError) as raised:
        oidc.begin_login(on, "/a", NOW)
    assert raised.value.code == "invalid_response"


@pytest.mark.parametrize("name", ["authorization_endpoint", "token_endpoint", "jwks_uri"])
@pytest.mark.parametrize("value", ["http://provider.example.test/x", "ftp://provider.example.test/x", "/relative", None,
                                   "https://user:pw@provider.example.test/x", "https://provider.example.test/a b"])
def test_every_address_in_the_discovery_document_must_be_https(on, provider, name, value):
    provider.endpoint_overrides = {name: value}
    with pytest.raises(oidc.ProviderError) as raised:
        oidc.begin_login(on, "/a", NOW)
    assert raised.value.code == "invalid_response"


def test_a_provider_that_signs_only_with_algorithms_northstar_does_not_accept_is_refused(on, provider):
    provider.algorithms = ["HS256", "none"]
    with pytest.raises(oidc.ProviderError) as raised:
        oidc.begin_login(on, "/a", NOW)
    assert raised.value.code == "invalid_response"


def test_only_the_algorithms_both_sides_accept_are_used(on, provider):
    provider.algorithms = ["HS256", "RS256", "ES256"]
    meta = oidc.metadata(provider.issuer)
    assert meta.algorithms == ("RS256", "ES256")


def test_a_provider_that_lists_no_algorithms_is_assumed_to_use_rs256(on, provider):
    provider.algorithms = None
    assert oidc.metadata(provider.issuer).algorithms == ("RS256",)


def test_a_missing_authentication_method_list_means_the_secret_goes_in_the_header(on, provider):
    provider.auth_methods = None
    assert oidc.metadata(provider.issuer).basic_auth is True


# -- the requests themselves --

@pytest.mark.parametrize("path", ["/.well-known/openid-configuration", "/jwks"])
def test_a_redirect_is_not_followed(on, provider, path):
    provider.redirect_paths = {path: "https://elsewhere.example.test/x"}
    with pytest.raises(oidc.ProviderError) as raised:
        finish(on, provider)
    assert raised.value.code == "unreachable" and "302" in raised.value.reason
    assert not any("elsewhere" in r["headers"].get("Host", "") for r in provider.requests)


def test_a_redirect_from_the_token_endpoint_is_not_followed(on, provider):
    provider.redirect_paths = {"/token": f"{provider.issuer}/steal"}
    with pytest.raises(oidc.ProviderError):
        finish(on, provider)
    assert not any(r["path"] == "/steal" for r in provider.requests)


@pytest.mark.parametrize("path", ["/.well-known/openid-configuration", "/jwks", "/token"])
def test_an_answer_over_the_size_limit_is_refused(on, provider, path):
    provider.oversize_paths = {path}
    with pytest.raises(oidc.ProviderError) as raised:
        finish(on, provider)
    assert raised.value.code == "invalid_response" and "too large" in raised.value.reason


def test_a_slow_provider_is_given_up_on(on, provider, monkeypatch):
    monkeypatch.setattr(oidc, "TIMEOUT_SECONDS", 0.3)
    provider.delay = 1.5
    with pytest.raises(oidc.ProviderError) as raised:
        oidc.begin_login(on, "/a", NOW)
    assert raised.value.code == "unreachable"


@pytest.mark.parametrize("field, status", [("discovery_status", 500), ("discovery_status", 404), ("jwks_status", 503), ("token_status", 500)])
def test_a_provider_that_fails_is_unreachable_to_northstar(on, provider, field, status):
    setattr(provider, field, status)
    with pytest.raises(oidc.ProviderError) as raised:
        finish(on, provider)
    assert raised.value.code == "unreachable"
    assert on.execute("SELECT COUNT(*) FROM users WHERE is_system = 0").fetchone()[0] == 0


def test_a_provider_that_cannot_be_connected_to_is_unreachable(on, provider):
    provider.close()
    with pytest.raises(oidc.ProviderError) as raised:
        oidc.begin_login(on, "/a", NOW)
    assert raised.value.code == "unreachable"


def test_the_reason_for_a_failure_never_holds_what_the_provider_said(on, provider):
    provider.token_status = 500
    with pytest.raises(oidc.ProviderError) as raised:
        finish(on, provider)
    assert "server_error" not in raised.value.reason and CLIENT_SECRET not in raised.value.reason


@pytest.mark.parametrize("url, ok", [
    ("https://id.example.test/x", True), ("http://localhost:8080/x", True), ("http://127.0.0.1/x", True),
    ("http://[::1]:9/x", True), ("http://id.example.test/x", False), ("http://192.168.1.5/x", False),
    ("ftp://id.example.test/x", False), ("https://", False), ("https://u:p@id.example.test/", False),
    ("https://id.example.test/a b", False), ("https://id.example.test/\n", False), ("https://id.example.test:abc/", False),
    (None, False), (5, False), ("https://" + "a" * 2100, False)])
def test_which_addresses_the_client_will_use(url, ok):
    assert oidc._address_ok(url) is ok


def test_requests_ignore_a_proxy_from_the_environment(on, provider, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    assert oidc.metadata(provider.issuer).issuer == provider.issuer


def test_the_client_says_who_it_is_and_asks_for_json(on, provider):
    oidc.metadata(provider.issuer)
    headers = provider.requests[0]["headers"]
    assert headers["User-Agent"].startswith("Northstar/") and headers["Accept"] == "application/json"
