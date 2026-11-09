"""What the screens of OIDC sign-in are told (step 4): the public endpoint that says which ways of signing in are on, the Sign-in
column of the Users list, and whether a person has a password. The provider is the fake server in tests/fake_provider.py.
Synthetic data only."""

import pytest
from fastapi.testclient import TestClient

from northstar import db, oidc
from northstar.web.app import create_app
from tests.fake_provider import CLIENT_ID, CLIENT_SECRET, FakeProvider

PUBLIC_URL = "http://localhost:8765"


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


def set_property(client, name, value):
    with db.connect(client.app.state.db_path) as conn:
        conn.execute("UPDATE system_properties SET value = ? WHERE name = ?", (value, name))


def configure(client, provider, label="Pocket ID"):
    for name, value in (("oidc.issuer", provider.issuer), ("oidc.client_id", CLIENT_ID), ("oidc.enabled", "true"),
                        ("oidc.user.allow_creation", "true"), ("oidc.provider", label)):
        set_property(client, name, value)


def sign_in_through(client, provider, claims=None):
    begun = client.get("/api/auth/oidc/login", params={"next": "/accounts"})
    code, params = provider.authorize(begun.headers["location"], claims)
    returned = client.get("/api/auth/oidc/callback", params={"code": code, "state": params["state"]})
    assert returned.status_code == 303 and returned.headers["location"] == "/accounts", returned.headers
    return returned


def other_browser(client):
    return TestClient(create_app(client.app.state.db_path), follow_redirects=False)


# -- which ways of signing in are on --

def test_the_methods_are_public_and_say_only_what_the_page_needs(anon_client):
    response = anon_client.get("/api/auth/methods")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json() == {"local": True, "oidc": False, "provider": None}


def test_a_fresh_installation_offers_the_password_alone(anon_client):
    assert anon_client.get("/api/auth/methods").json()["oidc"] is False


def test_oidc_is_offered_with_the_name_of_the_provider_once_it_is_on(client, provider):
    configure(client, provider)
    body = other_browser(client).get("/api/auth/methods").json()
    assert body == {"local": True, "oidc": True, "provider": "Pocket ID"}


def test_a_provider_with_no_name_is_offered_without_one(client, provider):
    configure(client, provider, label=None)
    assert other_browser(client).get("/api/auth/methods").json() == {"local": True, "oidc": True, "provider": None}


def test_oidc_that_is_not_set_up_is_not_offered_even_with_a_name(client, provider):
    configure(client, provider)
    set_property(client, "oidc.enabled", "false")
    body = other_browser(client).get("/api/auth/methods").json()
    assert body == {"local": True, "oidc": False, "provider": None}


def test_oidc_without_its_public_address_is_not_offered(client, provider, monkeypatch):
    configure(client, provider)
    monkeypatch.delenv("NORTHSTAR_PUBLIC_URL")
    assert other_browser(client).get("/api/auth/methods").json()["oidc"] is False


def test_password_sign_in_turned_off_is_reported(client, provider):
    configure(client, provider)
    set_property(client, "system.auth.local.enabled", "false")
    body = other_browser(client).get("/api/auth/methods").json()
    assert body == {"local": False, "oidc": True, "provider": "Pocket ID"}


def test_the_methods_carry_no_secret_issuer_or_client(client, provider):
    configure(client, provider)
    text = other_browser(client).get("/api/auth/methods").text
    for private in (CLIENT_SECRET, CLIENT_ID, provider.issuer):
        assert private not in text


# -- the Users list --

def sign_ins(client):
    return {user["email"]: user["sign_in"] for user in client.get("/api/users").json()}


def test_users_show_how_each_can_sign_in(client, provider):
    configure(client, provider)
    client.post("/api/users", json={"email": "robin@example.test", "display_name": "Robin", "password": "a-long-test-password",
                                    "is_admin": False})
    sign_in_through(other_browser(client), provider, {"sub": "sam", "email": "sam@example.test", "name": "Sam"})
    assert sign_ins(client) == {"robin@example.test": "local", "sam@example.test": "oidc", "test@example.com": "local"}


def test_a_user_with_a_password_who_signs_in_through_the_provider_is_both(client, provider):
    configure(client, provider)
    sign_in_through(other_browser(client), provider, {"sub": "admin-subject", "email": "test@example.com"})
    assert sign_ins(client) == {"test@example.com": "both"}


def test_a_password_set_for_someone_who_had_none_makes_them_both(client, provider):
    configure(client, provider)
    sign_in_through(other_browser(client), provider, {"sub": "sam", "email": "sam@example.test", "name": "Sam"})
    sam = next(user["id"] for user in client.get("/api/users").json() if user["email"] == "sam@example.test")
    assert client.post(f"/api/users/{sam}/password", json={"password": "a-long-test-password"}).status_code in (200, 204)
    assert sign_ins(client)["sam@example.test"] == "both"


def test_the_list_does_not_carry_identity_or_password_data(client, provider):
    configure(client, provider)
    sign_in_through(other_browser(client), provider, {"sub": "secret-subject-value", "email": "sam@example.test"})
    text = client.get("/api/users").text
    assert "secret-subject-value" not in text and provider.issuer not in text and "scrypt" not in text and "hash" not in text


# -- whether a person has a password --

def test_a_person_with_a_password_is_told_so(client):
    assert client.get("/api/me").json()["has_password"] is True


def test_a_person_who_signs_in_only_through_the_provider_has_no_password(client, provider):
    configure(client, provider)
    sam = other_browser(client)
    sign_in_through(sam, provider, {"sub": "sam", "email": "sam@example.test", "name": "Sam"})
    assert sam.get("/api/me").json()["has_password"] is False


def test_changing_the_password_of_someone_who_has_none_is_refused(client, provider):
    configure(client, provider)
    sam = other_browser(client)
    sign_in_through(sam, provider, {"sub": "sam", "email": "sam@example.test", "name": "Sam"})
    response = sam.post("/api/me/password", json={"current_password": "anything-at-all-123", "new_password": "a-long-new-password"})
    assert response.status_code in (400, 422)
    assert sam.get("/api/me").json()["has_password"] is False
