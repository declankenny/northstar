"""The sign-in page and Change password under the throttling limits. Synthetic data only, fixed clock."""

import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from northstar import throttle, users

from conftest import with_db

PASSWORD = "synthetic-pass-123"
NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
HOME, ELSEWHERE = "203.0.113.5", "198.51.100.7"


@pytest.fixture
def clock(monkeypatch):
    state = {"now": NOW}
    monkeypatch.setattr("northstar.clock.now", lambda: state["now"])
    return state


@pytest.fixture(autouse=True)
def fresh_proxy_warning():
    throttle.reset_warning_for_tests()


@pytest.fixture
def app_client(anon_client):
    with with_db(anon_client) as conn:
        users.create_user(conn, "owner@example.com", "Owner", PASSWORD, is_admin=True)
    return anon_client


def at(client, address, **headers):
    """The same app, as seen from another address (and with extra request headers)."""
    return TestClient(client.app, client=(address, 50000), headers={k.replace("_", "-"): v for k, v in headers.items()},
                      follow_redirects=False)


def fail(client, email="owner@example.com"):
    return client.post("/login", data={"email": email, "password": "wrong-password-123"})


def sign_in(client, email="owner@example.com", password=PASSWORD):
    return client.post("/login", data={"email": email, "password": password})


# -- the sign-in page --

def test_the_sixth_wrong_password_from_one_address_is_throttled(app_client, clock):
    home = at(app_client, HOME)
    assert [fail(home).status_code for _ in range(5)] == [400] * 5
    blocked = fail(home)
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "900"
    assert "Too many sign-in attempts. Try again in about 15 minutes." in blocked.text
    assert 'value="owner@example.com"' in blocked.text           # what was typed is kept


def test_the_correct_password_is_refused_while_blocked_and_sets_no_cookie(app_client, clock):
    home = at(app_client, HOME)
    for _ in range(5):
        fail(home)
    response = sign_in(home)
    assert response.status_code == 429 and "set-cookie" not in response.headers


def test_signing_in_works_again_once_the_window_has_passed(app_client, clock):
    home = at(app_client, HOME)
    for _ in range(5):
        fail(home)
    clock["now"] = NOW + timedelta(minutes=15, seconds=1)
    assert sign_in(home).status_code == 303


def test_a_successful_sign_in_resets_that_addresses_failures(app_client, clock):
    home = at(app_client, HOME)
    for _ in range(4):
        fail(home)
    assert sign_in(home).status_code == 303
    assert [fail(home).status_code for _ in range(5)] == [400] * 5
    assert fail(home).status_code == 429


def test_an_unknown_email_gets_the_same_responses_as_a_real_one(app_client, clock):
    home = at(app_client, HOME)
    real = [fail(home).status_code for _ in range(7)]
    other = at(app_client, ELSEWHERE)
    unknown = [fail(other, "nobody@example.com").status_code for _ in range(7)]
    assert real == unknown == [400] * 5 + [429] * 2


def test_an_attacker_at_another_address_does_not_stop_the_owner_signing_in(app_client, clock):
    attacker, home = at(app_client, ELSEWHERE), at(app_client, HOME)
    for _ in range(6):
        fail(attacker)
    assert fail(attacker).status_code == 429
    assert sign_in(home).status_code == 303


def test_many_addresses_together_trip_the_account_limit(app_client, clock):
    for index in range(6):
        client = at(app_client, f"198.51.100.{index + 10}")
        assert [fail(client).status_code for _ in range(5)] == [400] * 5
    assert fail(at(app_client, "198.51.100.99")).status_code == 429


def test_one_address_trying_many_emails_trips_the_address_limit(app_client, clock):
    spray = at(app_client, ELSEWHERE)
    assert [fail(spray, f"user{i}@example.com").status_code for i in range(20)] == [400] * 20
    assert fail(spray, "another@example.com").status_code == 429


# -- proxies --

def test_behind_a_proxy_that_is_not_trusted_the_address_limit_is_off_and_the_operator_is_told_once(app_client, clock, caplog):
    """The proxy's address is not in the chain it forwarded, so every visitor would look like one address."""
    behind = at(app_client, "172.18.0.2", x_forwarded_for=ELSEWHERE)
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        statuses = [fail(behind, f"user{i}@example.com").status_code for i in range(25)]
    assert statuses == [400] * 25                               # 25 emails from one address: no address limit
    warnings = [r for r in caplog.records if "FORWARDED_ALLOW_IPS" in r.getMessage()]
    assert len(warnings) == 1


def test_behind_an_untrusted_proxy_one_email_is_still_limited(app_client, clock):
    behind = at(app_client, "172.18.0.2", x_forwarded_for=ELSEWHERE)
    assert [fail(behind).status_code for _ in range(5)] == [400] * 5
    assert fail(behind).status_code == 429


def test_behind_a_trusted_proxy_the_real_address_is_used(app_client, clock, caplog):
    """Uvicorn has already put the forwarded address in place of the proxy's, so it is in the chain."""
    first = at(app_client, ELSEWHERE, x_forwarded_for=ELSEWHERE)
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        assert [fail(first, f"user{i}@example.com").status_code for i in range(20)] == [400] * 20
        assert fail(first, "another@example.com").status_code == 429
        assert sign_in(at(app_client, HOME, x_forwarded_for=HOME)).status_code == 303
    assert not [r for r in caplog.records if "FORWARDED_ALLOW_IPS" in r.getMessage()]


def test_a_spoofed_forwarded_header_cannot_dodge_the_email_limit(app_client, clock):
    """Someone connecting directly who claims to be someone else is treated as an unknown address, which
    only switches the address limit off. The email limits still apply."""
    spoofer = at(app_client, ELSEWHERE, x_forwarded_for="192.0.2.1")
    assert [fail(spoofer).status_code for _ in range(5)] == [400] * 5
    assert fail(spoofer).status_code == 429


def test_starting_the_app_says_what_the_limits_are(anon_client, caplog):
    from northstar.web.app import create_app
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        create_app(anon_client.app.state.db_path)
    message = " ".join(r.getMessage() for r in caplog.records)
    assert "Sign-in limits" in message and "5 failed attempts in 15 minutes" in message


# -- Change password --

def signed_in(client, address=HOME):
    mine = at(client, address)
    assert sign_in(mine).status_code == 303
    return mine


def change(client, current):
    return client.post("/api/me/password", json={"current_password": current, "new_password": "another-synthetic-pass-9"})


def test_guessing_the_current_password_is_throttled_like_signing_in(app_client, clock):
    mine = signed_in(app_client)
    assert [change(mine, "wrong-password-123").status_code for _ in range(5)] == [422] * 5
    blocked = change(mine, "wrong-password-123")
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "900"
    assert "Too many attempts" in blocked.json()["detail"]


def test_the_correct_current_password_is_refused_while_blocked(app_client, clock):
    mine = signed_in(app_client)
    for _ in range(5):
        change(mine, "wrong-password-123")
    assert change(mine, PASSWORD).status_code == 429
    with with_db(app_client) as conn:
        assert users.authenticate(conn, "owner@example.com", PASSWORD) is not None   # not changed


def test_a_changed_password_works_and_clears_the_failures(app_client, clock):
    mine = signed_in(app_client)
    for _ in range(3):
        change(mine, "wrong-password-123")
    assert change(mine, PASSWORD).status_code == 204
    other = at(app_client, HOME)
    assert sign_in(other, password="another-synthetic-pass-9").status_code == 303
