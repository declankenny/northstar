"""System properties: the tables, the setting service and its validators. Synthetic data only.
See docs/design/system-properties/design.md."""

import logging
import re
import sqlite3

import pytest

from northstar import system_properties as sp, writer
from northstar.errors import NotFoundError, ValidationError
from tests.conftest import op

SYSTEM_USER = "(SELECT id FROM users WHERE is_system = 1)"
NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+")


def add_property(conn, name, data_type="String", value=None, *, allow_null=0, read_only=0, hint="A test setting."):
    return conn.execute(
        "INSERT INTO system_properties (name, data_type_id, value, allow_null, hint, read_only, created_by, updated_by) "
        f"VALUES (?, (SELECT id FROM ref_property_data_types WHERE name = ?), ?, ?, ?, ?, {SYSTEM_USER}, {SYSTEM_USER})",
        (name, data_type, value, allow_null, hint, read_only)).lastrowid


def add_validator(conn, property_id, validator, position=1):
    conn.execute("INSERT INTO ref_property_validators (property_id, validator, position) VALUES (?, ?, ?)",
                 (property_id, validator, position))


def stored(conn, name):
    return conn.execute("SELECT value FROM system_properties WHERE name = ?", (name,)).fetchone()[0]


def changes(conn):
    return conn.execute("SELECT tablename, change, old_json, new_json FROM sys_record_changes ORDER BY id").fetchall()


def headers(conn):
    return conn.execute("SELECT kind, user_id FROM sys_operations ORDER BY id").fetchall()


# -- the schema --

def test_the_data_types_are_seeded(conn):
    assert {row[0] for row in conn.execute("SELECT name FROM ref_property_data_types")} == {"String", "Integer", "Lookup"}


def test_the_first_properties_are_seeded_by_the_system_user(conn):
    rows = {row["name"]: row for row in conn.execute(
        "SELECT p.name, t.name AS type, p.value, p.created_by FROM system_properties p "
        "JOIN ref_property_data_types t ON t.id = p.data_type_id")}
    assert {name: (row["type"], row["value"]) for name, row in rows.items()} == {
        "ui.theme.default": ("Lookup", "dark"), "balance.stale": ("Integer", "35"),
        "system.currency": ("String", "USD")}
    system_user = conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]
    assert {row["created_by"] for row in rows.values()} == {system_user}


def test_every_seeded_name_is_lowercase_dotted(conn):
    for (name,) in conn.execute("SELECT name FROM system_properties"):
        assert NAME_PATTERN.fullmatch(name), name


@pytest.mark.parametrize("name", [
    "nodot", "Upper.case", ".leading", "trailing.", "double..dot", "1starts.with_digit", "a.1segment", "has space.x",
    "has-dash.x", ""])
def test_the_database_refuses_a_badly_formed_name(conn, name):
    with pytest.raises(sqlite3.IntegrityError):
        add_property(conn, name)


def test_the_database_refuses_empty_or_oversize_text(conn):
    with pytest.raises(sqlite3.IntegrityError):
        add_property(conn, "a.empty", value="")
    with pytest.raises(sqlite3.IntegrityError):
        add_property(conn, "a.long", value="x" * 257)
    with pytest.raises(sqlite3.IntegrityError):
        add_property(conn, "a.nohint", hint="")


def test_every_property_has_a_hint(conn):
    for name, hint in conn.execute("SELECT name, hint FROM system_properties"):
        assert hint.strip() and len(hint) <= 256, name


def test_no_property_has_more_than_twenty_lookup_options(conn):
    counts = conn.execute("SELECT property_id, COUNT(*) FROM ref_property_lookups GROUP BY property_id").fetchall()
    assert counts and all(count <= 20 for _, count in counts)


def test_only_lookup_properties_have_options(conn):
    rows = conn.execute(
        "SELECT p.name FROM ref_property_lookups l JOIN system_properties p ON p.id = l.property_id "
        "JOIN ref_property_data_types t ON t.id = p.data_type_id WHERE t.name != 'Lookup'").fetchall()
    assert rows == []


def test_every_validator_named_in_the_database_exists(conn):
    names = {row[0] for row in conn.execute("SELECT validator FROM ref_property_validators")}
    assert names and names <= set(sp.VALIDATORS)


def test_a_validator_position_is_unique_within_a_property(conn):
    property_id = add_property(conn, "a.pos", "Integer", "1")
    add_validator(conn, property_id, "positive_integer", 1)
    with pytest.raises(sqlite3.IntegrityError):
        add_validator(conn, property_id, "three_capital_letters", 1)


def test_deleting_a_property_deletes_its_options_and_validators(conn):
    property_id = conn.execute("SELECT id FROM system_properties WHERE name = 'ui.theme.default'").fetchone()[0]
    conn.execute("DELETE FROM system_properties WHERE id = ?", (property_id,))
    assert conn.execute("SELECT COUNT(*) FROM ref_property_lookups WHERE property_id = ?", (property_id,)).fetchone()[0] == 0


def test_the_seeded_state_passes_the_data_type_check_and_the_validators(conn):
    """The seeded value of every property is valid as a state. Each validator is called with the seeded value as both the
    current and the proposed value, so no transition rule applies, and the read-only check is not made."""
    for row in conn.execute("SELECT id, name, value FROM system_properties WHERE value IS NOT NULL").fetchall():
        data_type = conn.execute(
            "SELECT t.name FROM system_properties p JOIN ref_property_data_types t ON t.id = p.data_type_id "
            "WHERE p.id = ?", (row["id"],)).fetchone()[0]
        prop = sp._row(conn, row["name"])
        assert sp._checked(conn, prop, row["value"]) == row["value"]
        typed = sp._typed(data_type, row["value"])
        context = sp.Context(row["name"], typed, typed, None, conn)
        for (validator,) in conn.execute(
                "SELECT validator FROM ref_property_validators WHERE property_id = ?", (row["id"],)):
            assert sp.VALIDATORS[validator](context) in (sp.ACCEPT, sp.ACCEPT_AND_LOCK)


# -- the writer refuses ref_ tables --

@pytest.mark.parametrize("table", ["ref_property_data_types", "ref_property_lookups", "ref_property_validators"])
def test_the_writer_refuses_a_reference_table(conn, table):
    with pytest.raises(ValueError, match="cannot be written this way"):
        writer.insert(op(conn), table, {"name": "x"})
    with pytest.raises(ValueError, match="cannot be written this way"):
        writer.update(op(conn), table, 1, {"name": "x"})
    with pytest.raises(ValueError, match="cannot be written this way"):
        writer.delete(op(conn), table, 1)


# -- reading --

def test_get_value_returns_the_typed_value(conn):
    assert sp.get_value(conn, "balance.stale") == 35
    assert sp.get_value(conn, "system.currency") == "USD"
    assert sp.get_value(conn, "ui.theme.default") == "dark"


def test_get_value_returns_none_for_an_unset_property(conn):
    add_property(conn, "a.unset", "Integer", None, allow_null=1)
    assert sp.get_value(conn, "a.unset") is None


def test_an_unknown_property_is_not_found(conn):
    with pytest.raises(NotFoundError):
        sp.get_value(conn, "no.such.setting")
    with pytest.raises(NotFoundError):
        sp.set_property(op(conn), "no.such.setting", "1")


def test_list_properties_gives_options_for_a_lookup_and_none_for_the_rest(conn):
    listed = {row["name"]: row for row in sp.list_properties(conn)}
    assert [o["value"] for o in listed["ui.theme.default"]["options"]] == ["light", "dark"]
    assert listed["balance.stale"]["options"] == []
    assert listed["balance.stale"]["type"] == "Integer" and listed["balance.stale"]["read_only"] is False
    assert [row["name"] for row in sp.list_properties(conn)] == sorted(listed)


# -- setting: accepted values --

def test_a_valid_integer_is_stored_in_its_canonical_form(conn):
    assert sp.set_property(op(conn), "balance.stale", " 007 ") == "7"
    assert stored(conn, "balance.stale") == "7"


def test_a_valid_lookup_option_is_stored(conn):
    assert sp.set_property(op(conn), "ui.theme.default", "light") == "light"
    assert stored(conn, "ui.theme.default") == "light"


def test_a_valid_string_is_stored_trimmed(conn):
    conn.execute("UPDATE system_properties SET value = NULL, read_only = 0 WHERE name = 'system.currency'")
    assert sp.set_property(op(conn), "system.currency", "  EUR ") == "EUR"
    assert stored(conn, "system.currency") == "EUR"


# -- setting: rejected values, through the service against the migrated database --

@pytest.mark.parametrize("name, text, message", [
    ("balance.stale", "abc", "Enter a whole number."),
    ("balance.stale", "1.5", "Enter a whole number."),
    ("balance.stale", "9" * 17, "Enter a whole number."),
    ("balance.stale", str(2**53), "Enter a whole number."),
    ("balance.stale", "0", "Enter a whole number of 1 or more."),
    ("balance.stale", "-3", "Enter a whole number of 1 or more."),
    ("ui.theme.default", "purple", "Choose one of the listed options."),
    ("ui.theme.default", "Dark", "Choose one of the listed options."),
    ("system.currency", "usd", "Choose a currency from the list."),
    ("system.currency", "x" * 257, "Use 256 characters or fewer."),
])
def test_a_bad_value_is_refused_with_its_message_and_nothing_is_written(conn, name, text, message):
    conn.execute("UPDATE system_properties SET value = NULL, read_only = 0 WHERE name = 'system.currency'")   # a fresh installation
    before = stored(conn, name)
    with pytest.raises(ValidationError, match=re.escape(message)):
        sp.set_property(op(conn), name, text)
    assert stored(conn, name) == before
    assert changes(conn) == [] and headers(conn) == []


def test_the_largest_integer_is_accepted(conn):
    assert sp.set_property(op(conn), "balance.stale", str(2**53 - 1)) == str(2**53 - 1)


@pytest.mark.parametrize("blank", ["", "   ", None, "\t\n"])
def test_a_blank_submission_is_refused_when_the_property_does_not_allow_null(conn, blank):
    with pytest.raises(ValidationError, match="This setting is required."):
        sp.set_property(op(conn), "balance.stale", blank)
    assert stored(conn, "balance.stale") == "35"


# -- unset --

def test_a_blank_submission_unsets_a_property_that_allows_null(conn):
    add_property(conn, "a.optional", "String", "x", allow_null=1)
    assert sp.set_property(op(conn), "a.optional", "   ") is None
    assert stored(conn, "a.optional") is None
    assert changes(conn)[0]["old_json"] == '{"value": "x"}' and changes(conn)[0]["new_json"] == '{"value": null}'


def test_an_unset_property_can_be_set(conn):
    add_property(conn, "a.optional", "Integer", None, allow_null=1)
    assert sp.set_property(op(conn), "a.optional", "5") == "5"


def test_a_property_that_does_not_allow_null_can_be_created_unset_and_then_cannot_be_cleared(conn):
    add_property(conn, "a.starts_empty", "String", None, allow_null=0)
    assert sp.set_property(op(conn), "a.starts_empty", "x") == "x"
    with pytest.raises(ValidationError, match="required"):
        sp.set_property(op(conn), "a.starts_empty", "")


def test_validators_run_with_the_unset_value(conn):
    """A feature can refuse to clear a setting it needs, so the validator is called with None."""
    seen = []

    def validator(ctx):
        seen.append((ctx.current, ctx.proposed))
        raise ValidationError("Keep this one.")

    add_validator(conn, add_property(conn, "a.kept", "String", "x", allow_null=1), "keep")
    sp.VALIDATORS["keep"] = validator
    try:
        with pytest.raises(ValidationError, match="Keep this one."):
            sp.set_property(op(conn), "a.kept", "")
    finally:
        del sp.VALIDATORS["keep"]
    assert seen == [("x", None)] and stored(conn, "a.kept") == "x"


# -- no-change saves --

def test_a_save_that_changes_nothing_writes_nothing_and_runs_no_validator(conn, monkeypatch):
    def refuse(ctx):
        raise AssertionError("a validator ran on a no-change save")

    monkeypatch.setitem(sp.VALIDATORS, "positive_integer", refuse)
    assert sp.set_property(op(conn), "balance.stale", " 35 ") == "35"
    assert sp.set_property(op(conn), "balance.stale", "035") == "35"
    assert changes(conn) == [] and headers(conn) == []


def test_a_value_that_has_become_invalid_is_not_flagged_by_a_no_change_save(conn):
    conn.execute("UPDATE system_properties SET value = '0' WHERE name = 'balance.stale'")     # as a tightened rule would leave it
    assert sp.set_property(op(conn), "balance.stale", "0") == "0"


def test_a_no_change_save_on_a_read_only_property_is_still_refused(conn):
    conn.execute("UPDATE system_properties SET read_only = 1 WHERE name = 'balance.stale'")
    with pytest.raises(ValidationError, match="locked"):
        sp.set_property(op(conn), "balance.stale", "35")


# -- read-only and locking --

def test_a_read_only_property_cannot_be_changed(conn):
    conn.execute("UPDATE system_properties SET read_only = 1 WHERE name = 'balance.stale'")
    with pytest.raises(ValidationError, match="This setting is locked and can't be changed."):
        sp.set_property(op(conn), "balance.stale", "31")
    assert stored(conn, "balance.stale") == "35"


def test_a_validator_can_lock_the_property_in_the_same_audited_change(conn, monkeypatch):
    monkeypatch.setitem(sp.VALIDATORS, "lock_it", lambda ctx: sp.ACCEPT_AND_LOCK)
    add_validator(conn, add_property(conn, "a.once", "String", None, allow_null=0), "lock_it")
    assert sp.set_property(op(conn), "a.once", "first") == "first"
    row = conn.execute("SELECT value, read_only FROM system_properties WHERE name = 'a.once'").fetchone()
    assert (row["value"], row["read_only"]) == ("first", 1)
    assert len(changes(conn)) == 1 and '"read_only": 1' in changes(conn)[0]["new_json"]
    with pytest.raises(ValidationError, match="locked"):
        sp.set_property(op(conn), "a.once", "second")
    assert stored(conn, "a.once") == "first"


def test_a_validator_sees_the_current_and_proposed_values_the_actor_and_the_connection(conn, monkeypatch):
    seen = []
    monkeypatch.setitem(sp.VALIDATORS, "spy", lambda ctx: seen.append(ctx) or sp.ACCEPT)
    add_validator(conn, add_property(conn, "a.spied", "Integer", "4"), "spy")
    sp.set_property(op(conn, actor_id=None), "a.spied", "9")
    (ctx,) = seen
    assert (ctx.name, ctx.current, ctx.proposed, ctx.actor_id, ctx.conn) == ("a.spied", 4, 9, None, conn)


def test_validators_run_in_position_order_and_the_first_refusal_wins(conn, monkeypatch):
    order = []

    def first(ctx):
        order.append("first")
        raise ValidationError("First refused.")

    def second(ctx):
        order.append("second")
        raise ValidationError("Second refused.")

    monkeypatch.setitem(sp.VALIDATORS, "first", first)
    monkeypatch.setitem(sp.VALIDATORS, "second", second)
    property_id = add_property(conn, "a.ordered", "String", "x")
    add_validator(conn, property_id, "second", 2)
    add_validator(conn, property_id, "first", 1)
    with pytest.raises(ValidationError, match="First refused."):
        sp.set_property(op(conn), "a.ordered", "y")
    assert order == ["first"] and stored(conn, "a.ordered") == "x"


def test_a_validator_that_returns_no_decision_is_a_programming_error(conn, monkeypatch):
    monkeypatch.setitem(sp.VALIDATORS, "forgetful", lambda ctx: None)
    add_validator(conn, add_property(conn, "a.forgetful", "String", "x"), "forgetful")
    with pytest.raises(RuntimeError, match="not a decision"):
        sp.set_property(op(conn), "a.forgetful", "y")
    assert stored(conn, "a.forgetful") == "x"


def test_an_unknown_validator_name_fails_closed_and_is_logged(conn, caplog):
    add_validator(conn, add_property(conn, "a.dangling", "String", "x"), "no_such_function")
    with caplog.at_level(logging.ERROR, logger="northstar.system_properties"):
        with pytest.raises(ValidationError, match="can't be changed right now"):
            sp.set_property(op(conn), "a.dangling", "y")
    assert stored(conn, "a.dangling") == "x"
    assert "no_such_function" in caplog.text


# -- audit --

def test_a_change_is_logged_with_who_made_it_and_the_old_and_new_value(conn):
    from northstar import users
    user = users.create_user(op(conn), "admin@example.com", "Admin", "test-password-123", is_admin=True)
    sp.set_property(op(conn, actor_id=user), "balance.stale", "45")
    assert headers(conn)[-1]["kind"] == "ui_edit" and headers(conn)[-1]["user_id"] == user
    (change,) = [c for c in changes(conn) if c["tablename"] == "system_properties"]
    assert change["change"] == "UPDATE"
    assert change["old_json"] == '{"value": "35"}' and change["new_json"] == '{"value": "45"}'
    row = conn.execute("SELECT updated_by FROM system_properties WHERE name = 'balance.stale'").fetchone()
    assert row["updated_by"] == user


def test_a_command_line_change_is_authored_by_the_system_user(conn):
    sp.set_property(op(conn, kind="cli"), "balance.stale", "45")
    system_user = conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]
    assert headers(conn)[-1]["kind"] == "cli" and headers(conn)[-1]["user_id"] == system_user


def test_a_refused_change_leaves_no_operation_behind(conn):
    with pytest.raises(ValidationError):
        sp.set_property(op(conn), "balance.stale", "0")
    assert headers(conn) == []
