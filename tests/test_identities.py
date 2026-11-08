"""Identity resolution for OIDC sign-in (step 2 of docs/design/oidc): who a validated identity is, what is written when they are let
in, and what is not written when they are refused. Also the storage under it: the identity table, the session method and the
unusable password. Synthetic data only."""

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

from northstar import db, identities, sessions, system_properties as sp, users
from northstar.identities import Claims, Refused
from tests.conftest import op

ISSUER = "https://id.example.test"
CLIENT = "northstar-test"
PASSWORD = "a-long-test-password"
NOW = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)


def set_property(conn, name, value):
    conn.execute("UPDATE system_properties SET value = ? WHERE name = ?", (value, name))


def turn_on(conn, *, creation=False, hours="12", issuer=ISSUER):
    """OIDC fully set up, as the validators would leave it, with user creation off unless asked."""
    set_property(conn, "oidc.issuer", issuer)
    set_property(conn, "oidc.client_id", CLIENT)
    set_property(conn, "oidc.enabled", "true")
    set_property(conn, "oidc.user.allow_creation", "true" if creation else "false")
    set_property(conn, "oidc.session.lifetime_hours", hours)


def claims(**changes):
    values = dict(issuer=ISSUER, subject="subject-1", email="alex@example.test", email_verified=True, name="Alex Example")
    values.update(changes)
    return Claims(**values)


def add_user(conn, email="sam@example.test", name="Sam Example", admin=False):
    return users.create_user(op(conn), email, name, PASSWORD, admin)


def counts(conn):
    return tuple(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in
                 ("users", "user_identities", "sys_sessions", "sys_operations", "sys_record_changes"))


def user_row(conn, user_id):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def refusal(conn, given):
    before = counts(conn)
    with pytest.raises(Refused) as refused:
        identities.sign_in(conn, given, NOW)
    assert counts(conn) == before, "a refusal must leave nothing behind"
    return refused.value


@pytest.fixture
def on(conn):
    turn_on(conn)
    return conn


@pytest.fixture
def creating(conn):
    turn_on(conn, creation=True)
    return conn


# -- an unknown identity --

def test_an_unknown_identity_with_no_account_is_refused_when_creation_is_off(on):
    refused = refusal(on, claims())
    assert refused.code == identities.NOT_ALLOWED


def test_creation_makes_a_regular_user_with_no_usable_password_and_binds_the_identity(creating):
    set_property(creating, "ui.locale.default", "de-DE")
    set_property(creating, "ui.theme.default", "light")
    signed_in = identities.sign_in(creating, claims(email=" Alex@Example.TEST "), NOW)
    assert signed_in.resolved.created and not signed_in.resolved.linked
    user = user_row(creating, signed_in.resolved.user_id)
    assert (user["email"], user["display_name"], user["is_admin"], user["deleted"], user["is_system"]) == (
        "alex@example.test", "Alex Example", 0, 0, 0)
    assert (user["theme"], user["locale"]) == ("light", "de-DE")
    assert user["password_hash"] == users.UNUSABLE_HASH and not users.has_usable_password(user["password_hash"])
    system_user = creating.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]
    assert user["created_by"] == system_user
    binding = creating.execute("SELECT * FROM user_identities").fetchone()
    assert (binding["user_id"], binding["issuer"], binding["subject"], binding["created_by"]) == (
        user["id"], ISSUER, "subject-1", system_user)


def test_creation_is_one_operation_of_kind_oidc_by_the_system_user(creating):
    identities.sign_in(creating, claims(), NOW)
    operation = creating.execute("SELECT * FROM sys_operations").fetchone()
    assert operation["kind"] == "oidc" and json.loads(operation["detail"]) == {"action": "create"}
    assert creating.execute("SELECT is_system FROM users WHERE id = ?", (operation["user_id"],)).fetchone()[0] == 1
    logged = creating.execute("SELECT tablename, change FROM sys_record_changes ORDER BY id").fetchall()
    assert [(row[0], row[1]) for row in logged] == [("users", "INSERT"), ("user_identities", "INSERT")]


def test_the_change_log_holds_no_password_hash_and_no_claims_beyond_the_binding(creating):
    identities.sign_in(creating, claims(), NOW)
    logged = " ".join(f"{row[0]} {row[1]}" for row in creating.execute("SELECT old_json, new_json FROM sys_record_changes"))
    assert users.UNUSABLE_HASH not in json.loads(
        creating.execute("SELECT new_json FROM sys_record_changes WHERE tablename = 'users'").fetchone()[0]).values()
    new = json.loads(creating.execute("SELECT new_json FROM sys_record_changes WHERE tablename = 'user_identities'").fetchone()[0])
    assert set(new) == {"user_id", "issuer", "subject", "created_at", "created_by"}
    assert "password_hash" not in logged


@pytest.mark.parametrize("name, expected", [
    ("  Alex Example  ", "Alex Example"), (None, "alex@example.test"), ("", "alex@example.test"), ("   ", "alex@example.test"),
    (42, "alex@example.test"), (["Alex"], "alex@example.test"), ("Line\nBreak", "alex@example.test"),
    ("x" * 101, "alex@example.test"), ("x" * 100, "x" * 100)])
def test_the_name_is_the_providers_when_usable_and_the_email_otherwise(creating, name, expected):
    signed_in = identities.sign_in(creating, claims(name=name), NOW)
    assert user_row(creating, signed_in.resolved.user_id)["display_name"] == expected


@pytest.mark.parametrize("verified", [None, False, "true", "True", 1, 0, [True], {}])
def test_an_email_that_is_not_exactly_verified_neither_links_nor_creates(creating, verified):
    add_user(creating, "alex@example.test")
    assert refusal(creating, claims(email_verified=verified)).code == identities.EMAIL_UNVERIFIED
    assert creating.execute("SELECT COUNT(*) FROM user_identities").fetchone()[0] == 0


@pytest.mark.parametrize("email", [None, 42, ["alex@example.test"]])
def test_a_missing_or_non_text_email_is_unverified(creating, email):
    assert refusal(creating, claims(email=email)).code == identities.EMAIL_UNVERIFIED


@pytest.mark.parametrize("email", ["", "not-an-address", "a@b@c", "@example.test", "alex@", "has space@example.test",
                                   "someone@system.invalid"])
def test_an_unusable_address_is_refused(creating, email):
    assert refusal(creating, claims(email=email)).code in (identities.NOT_ALLOWED,)


# -- an existing user --

def test_a_verified_email_links_an_existing_user_even_when_creation_is_off(on):
    sam = add_user(on, "alex@example.test", "Alexandra", admin=True)
    before_hash = user_row(on, sam)["password_hash"]
    users_before = on.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    signed_in = identities.sign_in(on, claims(name="Someone Else"), NOW)
    assert signed_in.resolved == identities.Resolved(sam, created=False, linked=True)
    assert on.execute("SELECT COUNT(*) FROM users").fetchone()[0] == users_before
    user = user_row(on, sam)
    assert (user["display_name"], user["is_admin"], user["password_hash"]) == ("Alexandra", 1, before_hash)
    assert on.execute("SELECT user_id, issuer, subject FROM user_identities").fetchone()[:] == (sam, ISSUER, "subject-1")
    assert users.authenticate(on, "alex@example.test", PASSWORD) is not None       # the password still works


def test_linking_is_logged_as_an_oidc_operation_that_only_inserts_the_binding(on):
    add_user(on, "alex@example.test")
    on.execute("DELETE FROM sys_record_changes")
    on.execute("DELETE FROM sys_operations")
    identities.sign_in(on, claims(), NOW)
    operation = on.execute("SELECT * FROM sys_operations").fetchone()
    assert operation["kind"] == "oidc" and json.loads(operation["detail"]) == {"action": "link"}
    assert [r[0] for r in on.execute("SELECT tablename FROM sys_record_changes")] == ["user_identities"]


def test_the_email_match_ignores_case_and_surrounding_space(on):
    sam = add_user(on, "alex@example.test")
    assert identities.sign_in(on, claims(email="  ALEX@Example.Test "), NOW).resolved.user_id == sam


def test_an_email_that_belongs_to_a_deleted_user_is_refused_and_nobody_is_reactivated(creating):
    gone = add_user(creating, "alex@example.test", "Former Member")
    users.delete_user(op(creating), gone, acting_user_id=add_user(creating, "boss@example.test", admin=True))
    refused = refusal(creating, claims())
    assert refused.code == identities.NOT_ALLOWED
    row = user_row(creating, gone)
    assert row["deleted"] == 1 and row["display_name"] == "Former Member" and row["password_hash"] == users.UNUSABLE_HASH
    assert creating.execute("SELECT COUNT(*) FROM user_identities").fetchone()[0] == 0


def test_a_second_subject_for_an_email_already_bound_at_the_issuer_is_refused_and_changes_nothing(on):
    sam = add_user(on, "alex@example.test")
    identities.sign_in(on, claims(subject="first"), NOW)
    refused = refusal(on, claims(subject="second"))
    assert refused.code == identities.NOT_ALLOWED and "another identity at this issuer" in refused.reason     # the rule, not the unique index
    assert on.execute("SELECT user_id, subject FROM user_identities").fetchall()[0][:] == (sam, "first")
    assert on.execute("SELECT COUNT(*) FROM user_identities").fetchone()[0] == 1


def test_creation_does_not_make_a_second_user_for_an_email_that_exists(creating):
    sam = add_user(creating, "alex@example.test")
    assert identities.sign_in(creating, claims(), NOW).resolved.user_id == sam
    assert creating.execute("SELECT COUNT(*) FROM users WHERE is_system = 0").fetchone()[0] == 1


# -- a known identity --

def test_a_known_identity_signs_in_whatever_the_provider_now_says_about_the_person(on):
    sam = add_user(on, "alex@example.test", "Alexandra")
    identities.sign_in(on, claims(), NOW)
    before = counts(on)
    changed = claims(email="renamed@elsewhere.test", email_verified=False, name="Renamed")
    signed_in = identities.sign_in(on, changed, NOW)
    assert signed_in.resolved == identities.Resolved(sam, created=False, linked=False)
    after = counts(on)
    assert (after[0], after[1]) == (before[0], before[1]) and after[2] == before[2] + 1     # one more session, no new user
    user = user_row(on, sam)
    assert (user["email"], user["display_name"]) == ("alex@example.test", "Alexandra")


def test_a_known_identity_signs_in_with_no_email_claim_at_all(on):
    add_user(on, "alex@example.test")
    identities.sign_in(on, claims(), NOW)
    assert identities.sign_in(on, claims(email=None, email_verified=None, name=None), NOW).resolved.linked is False


def test_a_known_identity_is_never_matched_again_by_email(on):
    alex = add_user(on, "alex@example.test")
    other = add_user(on, "other@example.test")
    identities.sign_in(on, claims(subject="alexs-subject"), NOW)
    signed_in = identities.sign_in(on, claims(subject="alexs-subject", email="other@example.test"), NOW)
    assert signed_in.resolved.user_id == alex != other


def test_a_known_identity_of_a_deleted_user_is_refused(on):
    sam = add_user(on, "alex@example.test")
    identities.sign_in(on, claims(), NOW)
    users.delete_user(op(on), sam, acting_user_id=add_user(on, "boss@example.test", admin=True))
    assert refusal(on, claims()).code == identities.NOT_ALLOWED


def test_a_binding_survives_the_deletion_so_signing_in_again_cannot_get_around_it(creating):
    sam = add_user(creating, "alex@example.test")
    identities.sign_in(creating, claims(), NOW)
    users.delete_user(op(creating), sam, acting_user_id=add_user(creating, "boss@example.test", admin=True))
    assert creating.execute("SELECT COUNT(*) FROM user_identities WHERE user_id = ?", (sam,)).fetchone()[0] == 1
    refusal(creating, claims())
    refusal(creating, claims(subject="a-new-subject"))      # the same email under a new subject is refused as well


def test_the_system_user_is_never_signed_in(on):
    system_id = on.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]
    on.execute("PRAGMA foreign_keys = ON")
    on.execute("INSERT INTO user_identities (user_id, issuer, subject, created_by, updated_by) VALUES (?, ?, 's', ?, ?)",
               (system_id, ISSUER, system_id, system_id))
    assert refusal(on, claims(subject="s")).code == identities.NOT_ALLOWED


# -- the configuration --

@pytest.mark.parametrize("undo", [
    lambda c: set_property(c, "oidc.enabled", "false"),
    lambda c: set_property(c, "oidc.issuer", None),
    lambda c: set_property(c, "oidc.client_id", None),
    lambda c: set_property(c, "oidc.issuer", "https://other.example.test")])
def test_nothing_signs_in_unless_oidc_is_on_and_the_issuer_is_the_configured_one(creating, undo):
    undo(creating)
    assert refusal(creating, claims()).code == identities.NOT_CONFIGURED


def test_the_session_is_an_oidc_session_for_the_configured_lifetime_and_fingerprint(creating):
    set_property(creating, "oidc.session.lifetime_hours", "5")
    signed_in = identities.sign_in(creating, claims(), NOW)
    row = creating.execute("SELECT * FROM sys_sessions").fetchone()
    assert (row["auth_method"], row["config_fingerprint"]) == ("oidc", identities.fingerprint(ISSUER, CLIENT))
    assert row["expires_at"] == (NOW + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert sessions.user_for_token(creating, signed_in.token, NOW)["id"] == signed_in.resolved.user_id


def test_the_fingerprint_follows_the_issuer_and_the_client_id_and_nothing_else():
    base = identities.fingerprint(ISSUER, CLIENT)
    assert base == identities.fingerprint(ISSUER, CLIENT) and len(base) == 64
    assert base != identities.fingerprint("https://other.example.test", CLIENT) != identities.fingerprint(ISSUER, "other")
    assert identities.fingerprint("a\nb", "c") != identities.fingerprint("a", "b\nc")      # no ambiguity at the join


def test_the_current_fingerprint_is_none_unless_oidc_is_on(conn):
    assert identities.current_fingerprint(conn) is None
    turn_on(conn)
    assert identities.current_fingerprint(conn) == identities.fingerprint(ISSUER, CLIENT)
    set_property(conn, "oidc.enabled", "false")
    assert identities.current_fingerprint(conn) is None


# -- atomicity --

def test_a_failure_after_the_user_is_made_leaves_no_user_no_binding_and_no_session(creating, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("the session could not be made")
    monkeypatch.setattr(sessions, "create_session", fail)
    before = counts(creating)
    with pytest.raises(RuntimeError):
        identities.sign_in(creating, claims(), NOW)
    assert counts(creating) == before


def test_two_first_sign_ins_at_once_make_one_user_one_binding_and_two_sessions(tmp_path):
    path = tmp_path / "race.db"
    db.upgrade(path)
    with db.connect(path) as setup:
        turn_on(setup, creation=True)
    barrier, results = threading.Barrier(2), []

    def attempt():
        connection = db.connect(path)
        try:
            barrier.wait()
            results.append(identities.sign_in(connection, claims(), NOW))
        except Exception as error:      # a failure is recorded, so the test can say what it was
            results.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert all(isinstance(result, identities.SignedIn) for result in results), results
    assert results[0].resolved.user_id == results[1].resolved.user_id
    assert sorted(result.resolved.created for result in results) == [False, True]
    with db.connect(path) as check:
        assert check.execute("SELECT COUNT(*) FROM users WHERE is_system = 0").fetchone()[0] == 1
        assert check.execute("SELECT COUNT(*) FROM user_identities").fetchone()[0] == 1
        assert check.execute("SELECT COUNT(*) FROM sys_sessions").fetchone()[0] == 2


def test_two_different_subjects_with_one_email_at_once_do_not_merge_into_one_account(tmp_path):
    path = tmp_path / "race.db"
    db.upgrade(path)
    with db.connect(path) as setup:
        turn_on(setup, creation=True)
    barrier, results = threading.Barrier(2), []

    def attempt(subject):
        connection = db.connect(path)
        try:
            barrier.wait()
            results.append(identities.sign_in(connection, claims(subject=subject), NOW))
        except Refused as refused:
            results.append(refused)
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt, args=(subject,)) for subject in ("one", "two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(type(result).__name__ for result in results) == ["Refused", "SignedIn"]
    with db.connect(path) as check:
        assert check.execute("SELECT COUNT(*) FROM users WHERE is_system = 0").fetchone()[0] == 1
        assert check.execute("SELECT COUNT(*) FROM user_identities").fetchone()[0] == 1


# -- the messages --

def test_the_refusals_say_what_the_sign_in_page_shows():
    assert Refused(identities.NOT_ALLOWED, "x").message("Pocket ID") == \
        "This account can't sign in to Northstar. Ask a Northstar admin for access."
    assert Refused(identities.EMAIL_UNVERIFIED, "x").message("Pocket ID") == \
        "Pocket ID hasn't confirmed your email address. Verify it there, then try again."
    assert Refused(identities.EMAIL_UNVERIFIED, "x").message().startswith("Your identity provider hasn't confirmed")
    assert "isn't available" in Refused(identities.NOT_CONFIGURED, "x").message("Pocket ID")


def test_a_refusal_reason_never_holds_a_claim(creating):
    refused = refusal(creating, claims(email="secret.person@example.test", email_verified=False, subject="private-subject"))
    assert "secret.person" not in refused.reason and "private-subject" not in refused.reason
    assert "secret.person" not in str(refused)


# -- the identity table --

def test_the_database_keeps_one_binding_per_identity_and_one_per_user_and_issuer(conn):
    sam, kim = add_user(conn, "sam@example.test"), add_user(conn, "kim@example.test")
    system_id = conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]

    def bind(user_id, issuer, subject):
        conn.execute("INSERT INTO user_identities (user_id, issuer, subject, created_by, updated_by) VALUES (?, ?, ?, ?, ?)",
                     (user_id, issuer, subject, system_id, system_id))

    bind(sam, ISSUER, "s1")
    with pytest.raises(sqlite3.IntegrityError):
        bind(kim, ISSUER, "s1")           # the identity is already someone's
    with pytest.raises(sqlite3.IntegrityError):
        bind(sam, ISSUER, "s2")           # the user already has a binding at this issuer
    bind(sam, "https://other.example.test", "s1")      # another issuer is another namespace


@pytest.mark.parametrize("issuer, subject", [("", "s"), ("x" * 257, "s"), (ISSUER, ""), (ISSUER, "s" * 256)])
def test_the_database_refuses_an_empty_or_oversize_issuer_or_subject(conn, issuer, subject):
    sam = add_user(conn)
    system_id = conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO user_identities (user_id, issuer, subject, created_by, updated_by) VALUES (?, ?, ?, ?, ?)",
                     (sam, issuer, subject, system_id, system_id))


def test_a_binding_can_be_neither_deleted_nor_moved(on):
    add_user(on, "alex@example.test")
    identities.sign_in(on, claims(), NOW)
    other = add_user(on, "other@example.test")
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        on.execute("DELETE FROM user_identities")
    for column, value in (("user_id", other), ("issuer", "https://x.example.test"), ("subject", "else")):
        with pytest.raises(sqlite3.IntegrityError, match="cannot be changed"):
            on.execute(f"UPDATE user_identities SET {column} = ?", (value,))


def test_every_column_of_the_new_table_says_whether_it_is_logged(conn):
    registry = dict(conn.execute("SELECT fieldname, is_logged FROM sys_audited_fields WHERE tablename = 'user_identities'").fetchall())
    columns = [row[0] for row in conn.execute("SELECT name FROM pragma_table_info('user_identities')")]
    assert set(registry) == set(columns)
    assert {name for name, logged in registry.items() if logged} == {"user_id", "issuer", "subject", "created_at", "created_by"}


# -- sessions --

def test_a_local_session_is_unchanged_thirty_days_with_no_fingerprint(conn):
    sam = add_user(conn)
    token = sessions.create_session(conn, sam, NOW)
    row = conn.execute("SELECT * FROM sys_sessions").fetchone()
    assert (row["auth_method"], row["config_fingerprint"], row["expires_at"]) == (
        "local", None, (NOW + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    found = sessions.user_for_token(conn, token, NOW)
    assert (found["auth_method"], found["config_fingerprint"]) == ("local", None)


def test_a_session_inserted_with_no_method_is_local(conn):
    sam = add_user(conn)
    conn.execute("INSERT INTO sys_sessions (token_hash, user_id, expires_at) VALUES ('h', ?, '2999-01-01T00:00:00Z')", (sam,))
    assert conn.execute("SELECT auth_method, config_fingerprint FROM sys_sessions").fetchone()[:] == ("local", None)


@pytest.mark.parametrize("arguments", [
    {"method": "oidc"}, {"method": "oidc", "fingerprint": "a" * 64}, {"method": "oidc", "lifetime": timedelta(hours=1)},
    {"fingerprint": "a" * 64}, {"method": "other"}])
def test_a_session_must_say_what_its_method_needs(conn, arguments):
    sam = add_user(conn)
    with pytest.raises(ValueError):
        sessions.create_session(conn, sam, NOW, **arguments)
    assert conn.execute("SELECT COUNT(*) FROM sys_sessions").fetchone()[0] == 0


def test_the_database_pairs_the_method_with_the_fingerprint(conn):
    sam = add_user(conn)
    columns = "(token_hash, user_id, expires_at, auth_method, config_fingerprint)"
    with pytest.raises(sqlite3.IntegrityError, match="fingerprint"):
        conn.execute(f"INSERT INTO sys_sessions {columns} VALUES ('a', ?, '2999-01-01T00:00:00Z', 'oidc', NULL)", (sam,))
    with pytest.raises(sqlite3.IntegrityError, match="fingerprint"):
        conn.execute(f"INSERT INTO sys_sessions {columns} VALUES ('b', ?, '2999-01-01T00:00:00Z', 'local', ?)", (sam, "a" * 64))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f"INSERT INTO sys_sessions {columns} VALUES ('c', ?, '2999-01-01T00:00:00Z', 'oidc', 'short')", (sam,))


def test_an_oidc_session_expires_and_is_not_extended_by_use(creating):
    signed_in = identities.sign_in(creating, claims(), NOW)
    just_before, just_after = NOW + timedelta(hours=12) - timedelta(seconds=1), NOW + timedelta(hours=12)
    assert sessions.user_for_token(creating, signed_in.token, just_before) is not None
    assert sessions.user_for_token(creating, signed_in.token, just_before) is not None      # used again: no extension
    assert sessions.user_for_token(creating, signed_in.token, just_after) is None


# -- no password --

def test_a_stored_hash_is_usable_only_if_it_is_a_real_scrypt_hash(conn):
    assert users.has_usable_password(users.hash_password(PASSWORD))
    for stored in (users.UNUSABLE_HASH, "", "garbage", "scrypt$1$2$3", "scrypt$x$y$z$!!$!!"):
        assert not users.has_usable_password(stored)


def test_a_user_with_no_password_cannot_sign_in_with_one_and_takes_as_long_as_an_unknown_email(creating, monkeypatch):
    identities.sign_in(creating, claims(), NOW)
    checked = []
    real = users.verify_password
    monkeypatch.setattr(users, "verify_password", lambda password, stored: checked.append(stored) or real(password, stored))
    assert users.authenticate(creating, "alex@example.test", "anything-at-all-12") is None
    assert users.authenticate(creating, "nobody@example.test", "anything-at-all-12") is None
    assert len(checked) == 2 and checked[0] == checked[1] == users._dummy_hash()     # both spent a real hash on the dummy


def test_an_admin_can_give_a_user_with_no_password_one(creating):
    signed_in = identities.sign_in(creating, claims(), NOW)
    users.set_user_password(op(creating), signed_in.resolved.user_id, PASSWORD)
    assert users.authenticate(creating, "alex@example.test", PASSWORD) is not None


# -- the guard on switching password sign-in off, now with real identities --

def test_the_linked_admin_check_finds_an_active_admin_bound_to_the_issuer(on):
    admin = add_user(on, "admin@example.test", "Admin", admin=True)
    boss = add_user(on, "boss@example.test", "Boss", admin=True)       # a second admin, so the first can be deleted
    add_user(on, "member@example.test", "Member")
    assert sp._linked_admin_exists(on, ISSUER) is False
    identities.sign_in(on, claims(subject="m", email="member@example.test"), NOW)
    assert sp._linked_admin_exists(on, ISSUER) is False               # bound, but not an admin
    identities.sign_in(on, claims(subject="a", email="admin@example.test"), NOW)
    assert sp._linked_admin_exists(on, ISSUER) is True
    assert sp._linked_admin_exists(on, "https://other.example.test") is False
    users.delete_user(op(on), admin, acting_user_id=boss)
    assert sp._linked_admin_exists(on, ISSUER) is False               # a deleted admin does not count


def test_password_sign_in_can_be_turned_off_once_an_admin_has_signed_in_through_oidc(on, monkeypatch):
    monkeypatch.setenv("NORTHSTAR_OIDC_CLIENT_SECRET", "synthetic-secret")
    monkeypatch.setenv("NORTHSTAR_PUBLIC_URL", "https://northstar.example.test")
    monkeypatch.setenv("NORTHSTAR_COOKIE_SECURE", "1")
    add_user(on, "admin@example.test", "Admin", admin=True)
    from northstar.errors import ValidationError
    with pytest.raises(ValidationError, match="signed in through OIDC"):
        sp.set_property(op(on), "system.auth.local.enabled", "false")
    identities.sign_in(on, claims(email="admin@example.test"), NOW)
    assert sp.set_property(op(on), "system.auth.local.enabled", "false") == "false"
