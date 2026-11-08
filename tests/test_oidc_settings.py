"""The settings of OIDC sign-in (step 1 of docs/design/oidc): the Boolean data type, the seven properties, the validators that
refuse a lock-out, the secret and public address read from the environment, and the host command that turns password sign-in
back on. Synthetic data only: the secret below is made up."""

import logging

import pytest

from northstar import config, db, signin, system_properties as sp
from northstar.errors import ValidationError
from northstar.web.app import create_app
from tests.conftest import op

SECRET = "synthetic-client-secret-for-tests"
ENV = ("NORTHSTAR_OIDC_CLIENT_SECRET", "NORTHSTAR_OIDC_CLIENT_SECRET_FILE", "NORTHSTAR_PUBLIC_URL",
       "NORTHSTAR_COOKIE_SECURE")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def save(conn, name, text):
    return sp.set_property(op(conn), name, text)


def refused(conn, name, text):
    with pytest.raises(ValidationError) as err:
        save(conn, name, text)
    return str(err.value)


def stored(conn, name):
    return conn.execute("SELECT value FROM system_properties WHERE name = ?", (name,)).fetchone()[0]


def configure(conn, monkeypatch):
    """Everything OIDC needs before it can be turned on, over HTTPS behind a secure cookie."""
    save(conn, "oidc.issuer", "https://id.example.test")
    save(conn, "oidc.client_id", "northstar-test")
    monkeypatch.setenv("NORTHSTAR_OIDC_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("NORTHSTAR_PUBLIC_URL", "https://northstar.example.test")
    monkeypatch.setenv("NORTHSTAR_COOKIE_SECURE", "1")


# -- the Boolean data type --

def test_a_boolean_is_stored_as_true_or_false_and_read_as_a_bool(conn):
    assert sp.get_value(conn, "oidc.user.allow_creation") is False
    assert save(conn, "oidc.user.allow_creation", "true") == "true"
    assert sp.get_value(conn, "oidc.user.allow_creation") is True
    save(conn, "oidc.user.allow_creation", "false")
    assert sp.get_value(conn, "oidc.user.allow_creation") is False


@pytest.mark.parametrize("text", ["yes", "no", "True", "TRUE", "1", "0", "on", "y"])
def test_a_boolean_refuses_anything_but_true_or_false(conn, text):
    assert refused(conn, "oidc.user.allow_creation", text) == "Choose Yes or No."
    assert stored(conn, "oidc.user.allow_creation") == "false"


def test_a_boolean_cannot_be_unset(conn):
    assert refused(conn, "oidc.user.allow_creation", "") == "This setting is required."
    assert refused(conn, "oidc.user.allow_creation", None) == "This setting is required."


def test_the_defaults_keep_password_sign_in_on_and_everything_else_off(conn):
    assert sp.get_value(conn, "system.auth.local.enabled") is True
    assert sp.get_value(conn, "oidc.enabled") is False
    assert sp.get_value(conn, "oidc.user.allow_creation") is False
    assert sp.get_value(conn, "oidc.session.lifetime_hours") == 12
    for name in ("oidc.provider", "oidc.issuer", "oidc.client_id"):
        assert sp.get_value(conn, name) is None


def test_the_list_gives_a_boolean_as_text_with_its_type(conn):
    row = next(p for p in sp.list_properties(conn) if p["name"] == "oidc.enabled")
    assert row["type"] == "Boolean" and row["value"] == "false" and row["allow_null"] is False


# -- turning OIDC on --

def test_oidc_cannot_be_turned_on_until_it_is_fully_set_up(conn):
    message = refused(conn, "oidc.enabled", "true")
    for needed in ("oidc.issuer", "oidc.client_id", "NORTHSTAR_OIDC_CLIENT_SECRET", "NORTHSTAR_PUBLIC_URL"):
        assert needed in message
    assert stored(conn, "oidc.enabled") == "false"


def test_oidc_can_be_turned_on_when_everything_is_set(conn, monkeypatch):
    configure(conn, monkeypatch)
    assert save(conn, "oidc.enabled", "true") == "true"


def test_the_refusal_names_only_what_is_missing(conn, monkeypatch):
    configure(conn, monkeypatch)
    monkeypatch.delenv("NORTHSTAR_PUBLIC_URL")
    message = refused(conn, "oidc.enabled", "true")
    assert "NORTHSTAR_PUBLIC_URL" in message and "oidc.issuer" not in message and "client secret" not in message


def test_a_secret_in_a_file_counts(conn, monkeypatch, tmp_path):
    configure(conn, monkeypatch)
    monkeypatch.delenv("NORTHSTAR_OIDC_CLIENT_SECRET")
    file = tmp_path / "secret"
    file.write_text(SECRET + "\n", encoding="utf-8")
    monkeypatch.setenv("NORTHSTAR_OIDC_CLIENT_SECRET_FILE", str(file))
    assert save(conn, "oidc.enabled", "true") == "true"


def test_https_needs_the_secure_cookie(conn, monkeypatch):
    configure(conn, monkeypatch)
    monkeypatch.delenv("NORTHSTAR_COOKIE_SECURE")
    assert "NORTHSTAR_COOKIE_SECURE=1" in refused(conn, "oidc.enabled", "true")


def test_localhost_over_plain_http_needs_no_secure_cookie(conn, monkeypatch):
    configure(conn, monkeypatch)
    monkeypatch.setenv("NORTHSTAR_PUBLIC_URL", "http://localhost:8000")
    monkeypatch.delenv("NORTHSTAR_COOKIE_SECURE")
    assert save(conn, "oidc.enabled", "true") == "true"


def test_an_ambiguous_secret_is_refused_with_a_message_that_has_no_secret_in_it(conn, monkeypatch, tmp_path):
    configure(conn, monkeypatch)
    file = tmp_path / "secret"
    file.write_text(SECRET, encoding="utf-8")
    monkeypatch.setenv("NORTHSTAR_OIDC_CLIENT_SECRET_FILE", str(file))
    message = refused(conn, "oidc.enabled", "true")
    assert "Set only one" in message and SECRET not in message


def test_oidc_cannot_be_turned_off_while_password_sign_in_is_off(conn, monkeypatch):
    configure(conn, monkeypatch)
    save(conn, "oidc.enabled", "true")
    conn.execute("UPDATE system_properties SET value = 'false' WHERE name = 'system.auth.local.enabled'")
    assert "Turn password sign-in on first" in refused(conn, "oidc.enabled", "false")
    assert stored(conn, "oidc.enabled") == "true"


def test_oidc_can_be_turned_off_while_password_sign_in_is_on(conn, monkeypatch):
    configure(conn, monkeypatch)
    save(conn, "oidc.enabled", "true")
    assert save(conn, "oidc.enabled", "false") == "false"


# -- turning password sign-in off --

def test_password_sign_in_cannot_be_turned_off_while_oidc_is_off(conn):
    assert "until OIDC sign-in is on" in refused(conn, "system.auth.local.enabled", "false")
    assert stored(conn, "system.auth.local.enabled") == "true"


def test_password_sign_in_cannot_be_turned_off_before_an_admin_has_signed_in_through_oidc(conn, monkeypatch):
    configure(conn, monkeypatch)
    save(conn, "oidc.enabled", "true")
    assert "until an admin has signed in through OIDC" in refused(conn, "system.auth.local.enabled", "false")
    assert stored(conn, "system.auth.local.enabled") == "true"


def test_password_sign_in_can_be_turned_off_once_a_linked_admin_exists(conn, monkeypatch):
    configure(conn, monkeypatch)
    save(conn, "oidc.enabled", "true")
    seen = []
    monkeypatch.setattr(sp, "_linked_admin_exists", lambda c, issuer: seen.append(issuer) or True)
    assert save(conn, "system.auth.local.enabled", "false") == "false"
    assert seen == ["https://id.example.test"]


def test_password_sign_in_is_refused_off_when_the_secret_has_gone_missing(conn, monkeypatch):
    configure(conn, monkeypatch)
    save(conn, "oidc.enabled", "true")
    monkeypatch.setattr(sp, "_linked_admin_exists", lambda c, issuer: True)
    monkeypatch.delenv("NORTHSTAR_OIDC_CLIENT_SECRET")
    assert "fully set up" in refused(conn, "system.auth.local.enabled", "false")


def test_password_sign_in_can_always_be_turned_on(conn):
    conn.execute("UPDATE system_properties SET value = 'false' WHERE name = 'system.auth.local.enabled'")
    assert save(conn, "system.auth.local.enabled", "true") == "true"


# -- the issuer, the client ID and the session lifetime --

@pytest.mark.parametrize("text", [
    "id.example.test", "ftp://id.example.test", "http://id.example.test", "https://", "https://id.example.test?x=1",
    "https://id.example.test#frag", "https://user:pw@id.example.test", "https://id.example.test:notaport"])
def test_the_issuer_must_be_an_https_address_without_query_or_fragment(conn, text):
    assert "https://" in refused(conn, "oidc.issuer", text)
    assert stored(conn, "oidc.issuer") is None


@pytest.mark.parametrize("text", ["https://id.example.test", "https://id.example.test/realms/home", "http://localhost:1411"])
def test_the_issuer_is_kept_exactly_as_given(conn, text):
    assert save(conn, "oidc.issuer", text) == text


def test_the_issuer_and_client_id_cannot_be_cleared_while_oidc_is_on(conn, monkeypatch):
    configure(conn, monkeypatch)
    save(conn, "oidc.enabled", "true")
    assert "Turn OIDC sign-in off" in refused(conn, "oidc.issuer", "")
    assert "Turn OIDC sign-in off" in refused(conn, "oidc.client_id", "")
    save(conn, "oidc.enabled", "false")
    assert save(conn, "oidc.issuer", "") is None and save(conn, "oidc.client_id", "") is None


def test_the_issuer_cannot_change_while_password_sign_in_is_off(conn):
    conn.execute("UPDATE system_properties SET value = 'false' WHERE name = 'system.auth.local.enabled'")
    assert "Turn password sign-in on" in refused(conn, "oidc.issuer", "https://other.example.test")
    assert stored(conn, "oidc.issuer") is None


@pytest.mark.parametrize("text", ["0", "-1", "8761", "abc", ""])
def test_the_session_lifetime_is_from_one_hour_to_a_year(conn, text):
    with pytest.raises(ValidationError):
        save(conn, "oidc.session.lifetime_hours", text)
    assert stored(conn, "oidc.session.lifetime_hours") == "12"


@pytest.mark.parametrize("text", ["1", "24", "8760"])
def test_a_session_lifetime_in_range_is_saved(conn, text):
    assert save(conn, "oidc.session.lifetime_hours", text) == text


def test_changes_are_in_the_change_log_without_the_secret(conn, monkeypatch):
    configure(conn, monkeypatch)
    save(conn, "oidc.enabled", "true")
    logged = " ".join(f"{a} {b}" for a, b in conn.execute("SELECT old_json, new_json FROM sys_record_changes"))
    assert "true" in logged and SECRET not in logged


# -- the environment --

def test_no_environment_means_no_secret_and_no_public_address():
    assert config.oidc_client_secret() is None and config.public_url() is None
    config.check_environment()


def test_the_secret_is_read_from_the_environment_or_a_file(monkeypatch, tmp_path):
    monkeypatch.setenv("NORTHSTAR_OIDC_CLIENT_SECRET", f"  {SECRET}  ")
    assert config.oidc_client_secret() == SECRET
    monkeypatch.delenv("NORTHSTAR_OIDC_CLIENT_SECRET")
    file = tmp_path / "secret"
    file.write_text(f"{SECRET}\r\n", encoding="utf-8")
    monkeypatch.setenv("NORTHSTAR_OIDC_CLIENT_SECRET_FILE", str(file))
    assert config.oidc_client_secret() == SECRET


def test_empty_values_count_as_not_set(monkeypatch):
    monkeypatch.setenv("NORTHSTAR_OIDC_CLIENT_SECRET", "")
    monkeypatch.setenv("NORTHSTAR_OIDC_CLIENT_SECRET_FILE", "")
    monkeypatch.setenv("NORTHSTAR_PUBLIC_URL", "")
    assert config.oidc_client_secret() is None and config.public_url() is None


def test_both_ways_of_giving_the_secret_is_an_error_that_does_not_show_it(monkeypatch, tmp_path):
    file = tmp_path / "secret"
    file.write_text(SECRET, encoding="utf-8")
    monkeypatch.setenv("NORTHSTAR_OIDC_CLIENT_SECRET", SECRET)
    monkeypatch.setenv("NORTHSTAR_OIDC_CLIENT_SECRET_FILE", str(file))
    with pytest.raises(config.ConfigurationError) as err:
        config.oidc_client_secret()
    assert "Both" in str(err.value) and SECRET not in str(err.value)


def test_an_unreadable_or_empty_secret_file_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setenv("NORTHSTAR_OIDC_CLIENT_SECRET_FILE", str(tmp_path / "missing"))
    with pytest.raises(config.ConfigurationError, match="can't be read"):
        config.oidc_client_secret()
    empty = tmp_path / "empty"
    empty.write_text(" \n", encoding="utf-8")
    monkeypatch.setenv("NORTHSTAR_OIDC_CLIENT_SECRET_FILE", str(empty))
    with pytest.raises(config.ConfigurationError, match="is empty"):
        config.oidc_client_secret()


@pytest.mark.parametrize("given, expected", [
    ("https://northstar.example.test", "https://northstar.example.test"),
    ("https://Northstar.Example.test/", "https://northstar.example.test"),
    ("https://northstar.example.test:8443", "https://northstar.example.test:8443"),
    ("http://localhost:8000", "http://localhost:8000"),
    ("http://127.0.0.1:8000", "http://127.0.0.1:8000"),
    ("http://[::1]:8000", "http://[::1]:8000")])
def test_the_public_address_is_an_origin(monkeypatch, given, expected):
    monkeypatch.setenv("NORTHSTAR_PUBLIC_URL", given)
    assert config.public_url() == expected


@pytest.mark.parametrize("given", [
    "northstar.example.test", "http://northstar.example.test", "http://192.168.1.10:8000", "ftp://northstar.example.test",
    "https://northstar.example.test/app", "https://northstar.example.test?x=1", "https://northstar.example.test#x",
    "https://user:pw@northstar.example.test", "https://", "https://northstar.example.test:abc"])
def test_a_public_address_that_is_not_https_or_not_an_origin_is_refused(monkeypatch, given):
    monkeypatch.setenv("NORTHSTAR_PUBLIC_URL", given)
    with pytest.raises(config.ConfigurationError, match="NORTHSTAR_PUBLIC_URL"):
        config.public_url()


def test_the_app_will_not_start_on_an_ambiguous_or_malformed_setting(monkeypatch, tmp_path):
    monkeypatch.setenv("NORTHSTAR_PUBLIC_URL", "http://northstar.example.test")
    with pytest.raises(config.ConfigurationError):
        create_app(tmp_path / "web.db")
    assert not (tmp_path / "web.db").exists()       # it stopped before touching the database


def test_the_app_starts_with_nothing_set(tmp_path):
    create_app(tmp_path / "web.db")


# -- the host command that turns password sign-in back on --

def make_database(tmp_path):
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path)
    return path


def run_command(monkeypatch, path, *args):
    monkeypatch.setenv("NORTHSTAR_DB", str(path))
    return signin.main(list(args))


def test_enable_local_turns_password_sign_in_back_on_as_the_system_user(tmp_path, monkeypatch, capsys):
    path = make_database(tmp_path)
    with db.connect(path) as conn:
        conn.execute("UPDATE system_properties SET value = 'false' WHERE name = 'system.auth.local.enabled'")
        conn.execute("UPDATE system_properties SET value = 'true' WHERE name = 'oidc.enabled'")       # a provider that is down
    assert run_command(monkeypatch, path, "enable-local") == 0
    assert "now on" in capsys.readouterr().out
    with db.connect(path) as conn:
        assert sp.get_value(conn, "system.auth.local.enabled") is True
        row = conn.execute(
            "SELECT o.kind, u.is_system FROM sys_operations o JOIN users u ON u.id = o.user_id ORDER BY o.id DESC").fetchone()
        assert (row["kind"], row["is_system"]) == ("cli", 1)


def test_enable_local_when_it_is_already_on_changes_nothing(tmp_path, monkeypatch, capsys):
    path = make_database(tmp_path)
    assert run_command(monkeypatch, path, "enable-local") == 0
    assert "already on" in capsys.readouterr().out
    with db.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sys_operations").fetchone()[0] == 0


def test_enable_local_refuses_a_missing_database_without_creating_one(tmp_path, monkeypatch, capsys):
    path = tmp_path / "data" / "northstar.db"
    assert run_command(monkeypatch, path, "enable-local") == 1
    assert "There is no database" in capsys.readouterr().err and not path.exists()


def test_enable_local_refuses_a_database_the_app_has_not_brought_up_to_date(tmp_path, monkeypatch, capsys):
    path = make_database(tmp_path)
    with db.connect(path) as conn:
        conn.execute("DELETE FROM sys_schema_migrations WHERE version = '0017_oidc_settings'")
    assert run_command(monkeypatch, path, "enable-local") == 1
    assert capsys.readouterr().err.startswith("Error:")


def test_enable_local_needs_no_provider_settings(tmp_path, monkeypatch):
    """It works with no secret, no public address and no network: only the database file."""
    path = make_database(tmp_path)
    with db.connect(path) as conn:
        conn.execute("UPDATE system_properties SET value = 'false' WHERE name = 'system.auth.local.enabled'")
    assert run_command(monkeypatch, path, "enable-local") == 0


def test_the_secret_is_never_logged(conn, monkeypatch, caplog):
    configure(conn, monkeypatch)
    with caplog.at_level(logging.DEBUG):
        save(conn, "oidc.enabled", "true")
        refused(conn, "system.auth.local.enabled", "false")
        config.check_environment()
    assert SECRET not in caplog.text
