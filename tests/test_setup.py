"""First-run setup (#64): eligibility, the token and setup sessions, the one transaction that creates the administrator and
saves the initial properties, and what direct API access can and cannot do. Synthetic data only."""

import logging
import sqlite3
import threading
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from northstar import clock, db, setup, system_properties, users
from northstar.web.app import create_app

from conftest import fake_spa, op, use_dollars

PASSWORD = "synthetic-pass-123"
COOKIE = "northstar_setup"
FORM = {"email": "Owner@Example.com", "display_name": "Owner", "password": PASSWORD, "currency": "USD",
        "locale": "en-US", "timezone": "America/Chicago"}


def gate_of(client) -> setup.SetupGate:
    return client.app.state.setup


def enter_token(client) -> None:
    assert client.post("/api/setup/token", json={"token": gate_of(client).token}).status_code == 204


def rows(client, sql, *params):
    with closing(db.connect(client.app.state.db_path)) as conn:
        return conn.execute(sql, params).fetchall()


def admins(client):
    return rows(client, "SELECT id, email FROM users WHERE is_admin = 1 AND is_system = 0")


def prop(client, name):
    return rows(client, "SELECT value, read_only, created_by, updated_by FROM system_properties WHERE name = ?", name)[0]


@pytest.fixture
def fresh(tmp_path):
    """A client on a new installation: no administrator, so setup is open."""
    return TestClient(create_app(tmp_path / "setup.db"), follow_redirects=False)


@pytest.fixture
def entered(fresh):
    """The same, with a setup session already granted."""
    enter_token(fresh)
    return fresh


# -- who may set up --

def test_setup_is_open_only_while_no_administrator_row_exists(conn):
    assert setup.is_open(conn)                      # the system user does not count
    users.create_user(op(conn), "member@example.com", "Member", PASSWORD)
    assert setup.is_open(conn)                      # an ordinary user is not an administrator
    users.create_user(op(conn), "owner@example.com", "Owner", PASSWORD, is_admin=True)
    assert not setup.is_open(conn)


def test_a_deleted_administrator_keeps_setup_closed(conn):
    users.create_user(op(conn), "owner@example.com", "Owner", PASSWORD, is_admin=True)
    conn.execute("UPDATE users SET deleted = 1 WHERE email = 'owner@example.com'")
    assert not setup.is_open(conn)


def test_a_token_is_printed_once_while_setup_is_open_and_never_when_an_administrator_exists(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        app = create_app(tmp_path / "log.db")
    token = app.state.setup.token
    assert token and caplog.text.count(token) == 1 and "/setup" in caplog.text
    with closing(db.connect(tmp_path / "log.db")) as conn:
        users.create_user(op(conn), "owner@example.com", "Owner", PASSWORD, is_admin=True)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        again = create_app(tmp_path / "log.db")
    assert again.state.setup.token is None and "setup token" not in caplog.text


def test_the_page_is_served_while_setup_is_open_and_goes_to_sign_in_afterwards(tmp_path, monkeypatch):
    fake_spa(tmp_path, monkeypatch)
    client = TestClient(create_app(tmp_path / "page.db"), follow_redirects=False)
    assert client.get("/setup").status_code == 200
    enter_token(client)
    assert client.post("/api/setup", json=FORM).status_code == 200
    closed = client.get("/setup")
    assert (closed.status_code, closed.headers["location"]) == (303, "/login")


def test_setup_needs_no_sign_in_but_nothing_else_opens_up(fresh):
    assert fresh.get("/api/setup/status").json() == {"state": "token"}
    assert fresh.get("/api/me").status_code == 401
    assert fresh.get("/api/system-properties").status_code == 401


# -- the token and the setup session --

def test_a_wrong_token_is_a_generic_refusal_and_grants_nothing(fresh):
    answer = fresh.post("/api/setup/token", json={"token": "not-the-token"})
    assert answer.status_code == 400
    assert gate_of(fresh).token not in answer.text and COOKIE not in answer.headers.get("set-cookie", "")
    assert fresh.get("/api/setup/status").json() == {"state": "token"}


def test_wrong_tokens_are_throttled_and_a_throttled_attempt_is_not_even_compared(fresh):
    for _ in range(setup.WRONG_TOKEN_LIMIT):
        assert fresh.post("/api/setup/token", json={"token": "wrong"}).status_code == 400
    blocked = fresh.post("/api/setup/token", json={"token": gate_of(fresh).token})      # the right one, during the block
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
    assert fresh.get("/api/setup/status").json() == {"state": "token"}


def test_the_throttle_clears_with_time(fresh):
    moment = [1000.0]
    gate_of(fresh).now = lambda: moment[0]
    for _ in range(setup.WRONG_TOKEN_LIMIT):
        fresh.post("/api/setup/token", json={"token": "wrong"})
    assert fresh.post("/api/setup/token", json={"token": "wrong"}).status_code == 429
    moment[0] += setup.WRONG_TOKEN_WINDOW + 1
    enter_token(fresh)


def test_the_token_is_not_used_up_by_giving_it_or_by_a_refused_form(entered):
    assert entered.get("/api/setup/status").json() == {"state": "form"}
    other = TestClient(entered.app, follow_redirects=False)          # a second browser with the same token
    enter_token(other)
    refused = entered.post("/api/setup", json={**FORM, "email": "bad"})
    assert refused.status_code == 422
    assert entered.get("/api/setup/status").json() == {"state": "form"}      # the session survived the refusal
    assert other.get("/api/setup/status").json() == {"state": "form"}


def test_the_setup_session_is_not_a_signed_in_session(entered):
    assert entered.get("/api/me").status_code == 401
    assert entered.get("/api/accounts").status_code == 401


def test_the_form_data_and_the_save_need_a_setup_session(fresh):
    assert fresh.get("/api/setup/options").status_code == 401
    assert fresh.post("/api/setup", json=FORM).status_code == 401
    assert admins(fresh) == []


def test_a_setup_session_lasts_30_minutes_and_a_new_one_comes_from_the_token_again(fresh):
    moment = [5000.0]
    gate_of(fresh).now = lambda: moment[0]
    enter_token(fresh)
    moment[0] += setup.SESSION_SECONDS - 1
    assert fresh.get("/api/setup/options").status_code == 200
    moment[0] += 2
    expired = fresh.post("/api/setup", json=FORM)
    assert expired.status_code == 401 and "ended" in expired.json()["detail"]
    assert admins(fresh) == [] and fresh.get("/api/setup/status").json() == {"state": "token"}
    enter_token(fresh)
    assert fresh.post("/api/setup", json=FORM).status_code == 200


def test_a_restart_makes_a_new_token_and_ends_every_session(tmp_path):
    first = TestClient(create_app(tmp_path / "restart.db"), follow_redirects=False)
    enter_token(first)
    cookie = first.cookies.get(COOKIE)
    second = TestClient(create_app(tmp_path / "restart.db"), follow_redirects=False)      # the process restarted
    assert gate_of(second).token != gate_of(first).token
    second.cookies.set(COOKIE, cookie, path="/api/setup")
    assert second.get("/api/setup/status").json() == {"state": "token"}
    assert second.post("/api/setup", json=FORM).status_code == 401
    assert second.post("/api/setup/token", json={"token": gate_of(first).token}).status_code == 400


# -- the form --

def test_the_form_starts_from_the_stored_values_and_offers_the_full_catalogs(tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "Europe/London")           # saved into system.timezone the first time, as the app always does
    client = TestClient(create_app(tmp_path / "options.db"), follow_redirects=False)
    enter_token(client)
    options = client.get("/api/setup/options").json()
    assert options["currency"] == {"value": None, "locked": False}
    assert options["locale"] == "en-US" and options["timezone"] == "Europe/London"
    assert {"code": "USD", "name": "US Dollar", "minor_units": 2} in options["currencies"]
    german = next(entry for entry in options["locales"] if entry["tag"] == "de-DE")
    assert (german["decimal_mark"], german["group_mark"]) == (",", ".") and "date_template" in german       # enough to show an example
    assert "America/Chicago" in options["timezones"]


def test_an_unset_time_zone_starts_as_utc(entered):
    assert entered.get("/api/setup/options").json()["timezone"] == "UTC"


def test_an_existing_locked_currency_is_shown_read_only_and_preserved(entered):
    with closing(db.connect(entered.app.state.db_path)) as conn:
        use_dollars(conn)
    assert entered.get("/api/setup/options").json()["currency"] == {"value": "USD", "locked": True}
    done = entered.post("/api/setup", json={**FORM, "currency": "EUR"})            # a different one is not applied, and not an error
    assert done.status_code == 200
    assert prop(entered, "system.currency")["value"] == "USD"


# -- finishing setup --

def test_a_fresh_installation_goes_from_token_to_form_to_normal_sign_in(entered):
    done = entered.post("/api/setup", json=FORM)
    assert done.status_code == 200 and done.json() == {"email": "owner@example.com"}
    assert rows(entered, "SELECT COUNT(*) FROM sys_sessions")[0][0] == 0            # nobody is signed in by it
    assert "api/setup" in done.headers["set-cookie"].lower() and "max-age=0" in done.headers["set-cookie"].lower()
    assert entered.post("/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD}).status_code == 200
    assert entered.get("/api/me").json()["email"] == "owner@example.com"
    assert prop(entered, "system.currency")["value"] == "USD" and prop(entered, "system.currency")["read_only"] == 1


def test_the_administrator_is_an_administrator_in_the_selected_locale_made_by_the_system_user(entered):
    assert entered.post("/api/setup", json={**FORM, "locale": "de-DE"}).status_code == 200
    [admin] = rows(entered, "SELECT is_admin, locale, created_by, updated_by, "
                            "(SELECT id FROM users WHERE is_system = 1) AS system_id FROM users WHERE email = 'owner@example.com'")
    assert (admin["is_admin"], admin["locale"]) == (1, "de-DE")
    assert admin["created_by"] == admin["updated_by"] == admin["system_id"]
    assert prop(entered, "ui.locale.default")["value"] == "de-DE"                    # and the default for people added later


def test_changed_properties_are_authored_by_the_new_administrator_and_keep_their_creation(entered):
    before = prop(entered, "system.currency")
    assert entered.post("/api/setup", json=FORM).status_code == 200
    [admin] = admins(entered)
    after = prop(entered, "system.currency")
    assert after["updated_by"] == admin["id"] and after["created_by"] == before["created_by"]
    assert prop(entered, "system.timezone")["value"] == "America/Chicago" and prop(entered, "system.timezone")["updated_by"] == admin["id"]


def test_an_unchanged_property_is_not_written_so_its_author_stays(entered):
    before = rows(entered, "SELECT updated_at, updated_by FROM system_properties WHERE name = 'ui.locale.default'")[0]
    assert entered.post("/api/setup", json={**FORM, "locale": "en-US"}).status_code == 200      # the stored default already
    after = rows(entered, "SELECT updated_at, updated_by FROM system_properties WHERE name = 'ui.locale.default'")[0]
    assert tuple(after) == tuple(before)


def test_the_chosen_time_zone_takes_effect_for_today(entered):
    assert entered.post("/api/setup", json={**FORM, "timezone": "Pacific/Auckland"}).status_code == 200
    assert clock.today() == clock.now().astimezone(clock.zone_for("Pacific/Auckland")).date()


def test_every_refused_field_is_reported_together_and_nothing_is_saved(entered):
    answer = entered.post("/api/setup", json={"email": "nope", "display_name": " ", "password": "short", "currency": None,
                                             "locale": "en-US", "timezone": "America/Chicago"})
    assert answer.status_code == 422
    # The currency is refused too (none was chosen), so the person fixes everything in one go.
    assert set(answer.json()["errors"]) == {"email", "display_name", "password", "currency"}
    assert admins(entered) == []


def test_the_property_refusals_are_reported_by_field_and_roll_the_administrator_back(entered):
    answer = entered.post("/api/setup", json={**FORM, "currency": None, "timezone": "Mars/Olympus", "locale": "xx-XX"})
    assert answer.status_code == 422
    assert set(answer.json()["errors"]) == {"currency", "timezone", "locale"}
    assert admins(entered) == [] and rows(entered, "SELECT COUNT(*) FROM users WHERE is_system = 0")[0][0] == 0
    assert prop(entered, "system.currency")["value"] is None and prop(entered, "system.timezone")["value"] is None
    assert entered.get("/api/setup/status").json() == {"state": "form"}             # still usable, so the person fixes the fields
    assert entered.post("/api/setup", json=FORM).status_code == 200


def test_a_database_failure_after_the_administrator_was_made_rolls_everything_back_and_allows_a_retry(entered, monkeypatch):
    real, calls = system_properties.save_property, []

    def flaky(op, name, text):
        calls.append(name)
        if len(calls) == 2:
            raise sqlite3.OperationalError("disk I/O error")       # after the administrator and the first property
        return real(op, name, text)

    monkeypatch.setattr(system_properties, "save_property", flaky)
    broken = TestClient(entered.app, raise_server_exceptions=False, follow_redirects=False)
    broken.cookies.set(COOKIE, entered.cookies.get(COOKIE), path="/api/setup")
    assert broken.post("/api/setup", json=FORM).status_code == 500
    assert len(calls) == 2
    assert admins(entered) == [] and prop(entered, "system.currency")["value"] is None
    monkeypatch.undo()
    assert entered.post("/api/setup", json=FORM).status_code == 200


def test_an_existing_users_email_is_refused_even_for_a_deleted_user_who_is_not_reactivated(entered):
    with closing(db.connect(entered.app.state.db_path)) as conn:
        users.create_user(op(conn), "gone@example.com", "Gone", PASSWORD)
        conn.execute("UPDATE users SET deleted = 1 WHERE email = 'gone@example.com'")
    answer = entered.post("/api/setup", json={**FORM, "email": "Gone@Example.com"})
    assert answer.status_code == 422 and "email" in answer.json()["errors"]
    [row] = rows(entered, "SELECT deleted, is_admin FROM users WHERE email = 'gone@example.com'")
    assert (row["deleted"], row["is_admin"]) == (1, 0)
    assert admins(entered) == []


def test_the_password_and_the_token_never_reach_the_log(tmp_path, caplog):
    with caplog.at_level(logging.DEBUG):
        client = TestClient(create_app(tmp_path / "quiet.db"), follow_redirects=False)
        token = gate_of(client).token
        caplog.clear()                                              # the startup line that prints the token is deliberate
        enter_token(client)
        client.post("/api/setup", json={**FORM, "timezone": "Mars/Olympus"})
        client.post("/api/setup", json=FORM)
    assert PASSWORD not in caplog.text and token not in caplog.text


# -- after setup --

def test_completing_setup_ends_every_token_and_session_in_every_browser(entered):
    other = TestClient(entered.app, follow_redirects=False)
    enter_token(other)
    assert entered.post("/api/setup", json=FORM).status_code == 200
    assert gate_of(entered).token is None
    for browser in (entered, other):
        assert browser.get("/api/setup/status").json() == {"state": "complete"}
        assert browser.get("/api/setup/options").status_code == 409
    assert fresh_token_is_refused(entered)


def fresh_token_is_refused(client) -> bool:
    return client.post("/api/setup/token", json={"token": "anything"}).status_code == 409


def test_a_retry_after_a_lost_response_creates_nothing_and_says_setup_is_complete(entered):
    assert entered.post("/api/setup", json=FORM).status_code == 200
    retry = entered.post("/api/setup", json=FORM)               # the browser never saw the first answer
    assert retry.status_code == 409 and "already been completed" in retry.json()["detail"]
    assert len(admins(entered)) == 1


def test_direct_requests_cannot_get_around_the_guard_once_an_administrator_exists(fresh):
    with closing(db.connect(fresh.app.state.db_path)) as conn:
        users.create_user(op(conn), "owner@example.com", "Owner", PASSWORD, is_admin=True)
    assert fresh.get("/api/setup/status").json() == {"state": "complete"}
    token = gate_of(fresh).token                                 # a token that was generated while setup was open
    assert fresh.post("/api/setup/token", json={"token": token}).status_code == 409
    assert fresh.get("/api/setup/options").status_code == 409
    assert fresh.post("/api/setup", json={**FORM, "email": "second@example.com"}).status_code == 409
    assert [row["email"] for row in admins(fresh)] == ["owner@example.com"]


def test_only_deleted_administrators_leave_setup_closed(fresh):
    with closing(db.connect(fresh.app.state.db_path)) as conn:
        users.create_user(op(conn), "owner@example.com", "Owner", PASSWORD, is_admin=True)
        conn.execute("UPDATE users SET deleted = 1 WHERE email = 'owner@example.com'")
    assert fresh.get("/api/setup/status").json() == {"state": "complete"}
    assert fresh.post("/api/setup", json=FORM).status_code == 409


def test_two_submissions_at_once_create_exactly_one_administrator(tmp_path):
    path = tmp_path / "race.db"
    db.upgrade(path)
    with closing(db.connect(path)) as conn:
        gate = setup.SetupGate.start(conn)
    cookie = gate.grant()
    barrier, outcomes = threading.Barrier(2), []

    def submit(email):
        with closing(db.connect(path)) as conn:
            barrier.wait()
            try:
                outcomes.append(setup.complete(conn, gate, cookie, setup.Submission(
                    email, "Person", PASSWORD, "USD", "en-US", "America/Chicago")))
            except setup.SetupClosed:
                outcomes.append("closed")

    threads = [threading.Thread(target=submit, args=(email,)) for email in ("a@example.com", "b@example.com")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) in (["a@example.com", "closed"], ["b@example.com", "closed"])
    with closing(db.connect(path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1 AND is_system = 0").fetchone()[0] == 1
