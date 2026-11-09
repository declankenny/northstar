"""Northstar's side of the list framework: its tables, and the conversion of an amount into the system currency. The lists named
here exist only in these tests. Synthetic data only; the figures are worked out by hand."""

from datetime import date

import pytest

from conftest import add_balance, op, type_id
from northstar import accounts, currencies, rates, users
from northstar.errors import ValidationError
from northstar.lists.kinds import normalise
from northstar.lists.listdef import ListDef, check
from northstar.lists.query import ListContext, run
from northstar.lists.registry import Catalog, RegistryError
from northstar.lists.request import parse_request
from northstar.listdefs import catalog as northstar_catalog
from northstar.listdefs import conversion
from northstar.listdefs.tables import NOT_LISTABLE, TABLES

TODAY = date(2026, 6, 3)
CONTEXT = ListContext(today=TODAY)
ASSET, LIABILITY = 1, 2

BALANCES = ListDef("balances_for_tests", "balances",
                   ("as_of_date", "account", "account.type", "amount_cents", "account.currency", "reporting_value", "note"),
                   ("as_of_date", "desc"), source="live_balances")
ACCOUNTS = ListDef("accounts_for_tests", "accounts", ("name", "type", "type.class", "currency", "is_open"),
                   ("name", "asc"), source="live_accounts")
USERS = ListDef("users_for_tests", "users", ("display_name", "email", "is_admin"), ("display_name", "asc"),
                scope="b.is_system = 0 AND b.deleted = 0")


def cid(conn, code):
    return conn.execute("SELECT id FROM currencies WHERE code = ?", (code,)).fetchone()[0]


def switch_on(conn, code):
    currencies.update_currency(op(conn), code, True, "2020-01-01", TODAY)


def rate(conn, code, day, text):
    rates.add_rate(op(conn), code, day, text, TODAY)


def account(conn, name, code="USD", kind="Savings"):
    klass = conn.execute("SELECT class_id FROM account_types WHERE name = ?", (kind,)).fetchone()[0]
    return accounts.add_account(op(conn), name, klass, type_id(conn, kind), None, cid(conn, code))


@pytest.fixture
def household(conn):
    """Dollars (the system currency), euros with rates from 1 March and 1 May, and yen with one rate; one deleted account."""
    for code in ("EUR", "JPY"):
        switch_on(conn, code)
    rate(conn, "EUR", "2026-03-01", "1.08")
    rate(conn, "EUR", "2026-05-01", "1.10")
    rate(conn, "JPY", "2026-01-01", "0.0067")
    ids = {"usd": account(conn, "Test dollars"), "eur": account(conn, "Test euros", "EUR"),
           "jpy": account(conn, "Test yen", "JPY", "Checking"), "card": account(conn, "Test card", "USD", "Credit card"),
           "gone": account(conn, "Test deleted")}
    for account_id, day, cents in [
        ("usd", "2026-01-31", 100_000), ("usd", "2026-05-31", 123_456),
        ("eur", "2026-02-15", 50_000),          # before the first euro rate: cannot be converted
        ("eur", "2026-03-01", 10_000),          # on the day of a rate: that rate (1.08)
        ("eur", "2026-04-15", 123_456),         # between the two rates: the earlier one (1.08)
        ("eur", "2026-05-10", 123_456),         # after the second: 1.10
        ("eur", "2026-05-11", 5), ("eur", "2026-05-12", -5),       # half a cent away from zero, both ways
        ("jpy", "2026-01-31", 5_000), ("jpy", "2026-02-28", 10),
        ("card", "2026-05-31", 20_000), ("gone", "2026-05-31", 999_999),
    ]:
        add_balance(conn, ids[account_id], day, cents)
    conn.execute("UPDATE balances SET note = 'Test note' WHERE as_of_date = '2026-05-31' AND account_id = ?", (ids["usd"],))
    accounts.delete_account(op(conn), ids["gone"])
    conn.commit()
    return ids


def view(conn, data=None, definition=BALANCES, context=CONTEXT):
    cat = northstar_catalog(conn)
    return run(conn, cat, definition, parse_request(cat, definition, data), context)


def everything(conn, data=None, definition=BALANCES):
    rows, page = [], 1
    while True:
        result = view(conn, {**(data or {}), "page": page, "page_size": 100}, definition)
        rows += result.rows
        if page >= result.pages:
            return rows
        page += 1


# -- the tables --

def test_every_household_table_has_an_entry_or_says_why_it_is_not_listable(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}
    household_tables = {t for t in tables if not t.startswith(("sys_", "ref_"))}
    assert household_tables == set(TABLES) | set(NOT_LISTABLE), "a table was added or removed: decide whether it is a list"
    assert not set(TABLES) & set(NOT_LISTABLE)
    assert all(reason.strip() for reason in NOT_LISTABLE.values())


def test_the_registry_agrees_with_the_migrated_database_and_the_test_lists_are_valid(conn):
    cat = northstar_catalog(conn)
    for definition in (BALANCES, ACCOUNTS, USERS):
        check(cat, definition)
    assert set(cat.relations("balances")) == {"account", "created_by", "updated_by"}
    assert set(cat.relations("accounts")) == {"type", "currency", "created_by", "updated_by"}
    assert "class" not in cat.relations("accounts")                      # an account has no class of its own (#181)
    assert set(cat.relations("account_types")) == {"class", "created_by", "updated_by"}


def test_a_registry_that_forgets_a_table_a_foreign_key_points_at_is_refused(conn):
    without_users = {name: table for name, table in TABLES.items() if name != "users"}
    with pytest.raises(RegistryError, match="has no entry"):
        Catalog(conn, without_users)


@pytest.mark.parametrize("table, key", [
    ("balances", "version"), ("balances", "deleted"), ("accounts", "deleted"), ("users", "password_hash"), ("users", "is_system"),
    ("balances", "created_by.password_hash"), ("balances", "created_by.email"), ("balances", "account.created_by.email"),
    ("accounts", "id"), ("balances", "account_id"), ("balances", "account.currency_id"),
])
def test_what_is_denied_or_not_offered_is_not_a_column_by_any_path(conn, table, key):
    with pytest.raises(ValidationError, match="not a column|only shows its name"):      # a person's other columns are not offered either
        northstar_catalog(conn).resolve(table, key)


def test_a_person_can_be_shown_by_name_but_not_entered_and_a_table_never_leads_back_to_itself(conn):
    cat = northstar_catalog(conn)
    assert cat.resolve("balances", "created_by").column == "display_name"
    with pytest.raises(ValidationError, match="only shows its name"):
        cat.resolve("balances", "created_by.email")
    with pytest.raises(ValidationError, match="comes back to a table"):
        cat.resolve("users", "created_by")                                # who created a user, in the list of users


def test_every_offered_column_can_be_asked_for_from_the_table_that_has_it(conn, household):
    cat = northstar_catalog(conn)
    for name, table in TABLES.items():
        for field in table.fields:
            assert cat.resolve(name, field)


# -- Balances, as a list over live_balances --

def test_every_balance_of_a_live_account_appears_once_and_a_deleted_accounts_does_not(conn, household):
    rows = everything(conn)
    expected = conn.execute("SELECT COUNT(*) FROM live_balances").fetchone()[0]
    assert len(rows) == expected == 11 and view(conn).total == 11
    assert len({r["_id"] for r in rows}) == 11
    assert "Test deleted" not in {r["account"] for r in rows}


def test_a_value_shows_its_amount_its_scale_and_its_unit(conn, household):
    rows = {(r["account"], r["as_of_date"]): r for r in everything(conn)}
    assert rows[("Test dollars", "2026-05-31")]["amount_cents"] == {"value": 123_456, "scale": 2, "unit": "USD"}
    assert rows[("Test yen", "2026-01-31")]["amount_cents"] == {"value": 5_000, "scale": 0, "unit": "JPY"}
    assert rows[("Test dollars", "2026-05-31")]["account.currency"] == "USD"
    assert rows[("Test card", "2026-05-31")]["account.type"] == "Credit card"


def reporting(rows, account_name, day):
    return next(r for r in rows if (r["account"], r["as_of_date"]) == (account_name, day))["reporting_value"]


def test_a_balance_is_converted_with_the_latest_rate_on_or_before_its_own_date(conn, household):
    rows = everything(conn)
    answers = {
        ("Test dollars", "2026-01-31"): (100_000, "USD"),         # the system currency: no rate needed
        ("Test euros", "2026-03-01"): (10_800, "USD"),            # 100.00 EUR x 1.08, on the day of the rate
        ("Test euros", "2026-04-15"): (133_332, "USD"),           # 1,234.56 x 1.08 = 1,333.3248, between the rates
        ("Test euros", "2026-05-10"): (135_802, "USD"),           # 1,234.56 x 1.10 = 1,358.016 -> the later rate
        ("Test euros", "2026-05-11"): (6, "USD"),                 # 0.05 x 1.10 = 0.055: half a cent rounds away from zero
        ("Test euros", "2026-05-12"): (-6, "USD"),                # and so does -0.055
        ("Test yen", "2026-01-31"): (3_350, "USD"),               # 5,000 JPY x 0.0067 = 33.50
        ("Test yen", "2026-02-28"): (7, "USD"),                   # 10 JPY x 0.0067 = 0.067 -> 7 cents
    }
    for (name, day), (cents, unit) in answers.items():
        assert reporting(rows, name, day) == {"value": cents, "scale": 2, "unit": unit, "note": None}, (name, day)


def test_a_balance_with_no_rate_on_or_before_its_date_has_no_value_and_says_which_currency(conn, household):
    shown = reporting(everything(conn), "Test euros", "2026-02-15")
    assert shown == {"value": None, "scale": 2, "unit": "USD", "note": "No EUR rate"}


def test_the_conversion_is_the_one_in_networth(conn, household):
    from northstar import networth
    row = next(r for r in everything(conn) if (r["account"], r["as_of_date"]) == ("Test euros", "2026-05-10"))
    assert row["reporting_value"]["value"] == networth.convert(123_456, 2, "1.10", 2)


def test_sorting_filtering_and_grouping_by_reporting_value_use_the_converted_figures(conn, household):
    rows = everything(conn, {"columns": ["account", "reporting_value"], "sort": {"field": "reporting_value", "direction": "desc"}})
    values = [r["reporting_value"]["value"] if r["reporting_value"] else None for r in rows]
    present = [v for v in values if v is not None]
    assert present == sorted(present, reverse=True) and values[len(present):] == [None]            # the unconvertible one is last
    value = lambda r: r["reporting_value"]["value"] if r["reporting_value"] else None
    big = everything(conn, {"columns": ["account"], "filters": [{"field": "reporting_value", "operator": "at_least", "value": "1000"}]})
    assert {r["_id"] for r in big} == {r["_id"] for r in rows if value(r) is not None and value(r) >= 100_000} and big
    none = everything(conn, {"columns": ["account"], "filters": [{"field": "reporting_value", "operator": "is_empty"}]})
    assert len(none) == 1
    shown = everything(conn, {"columns": ["account", "reporting_value"], "filters": [{"field": "reporting_value", "operator": "between", "value": ["0", "50"]}]})
    hidden = everything(conn, {"columns": ["account"], "filters": [{"field": "reporting_value", "operator": "between", "value": ["0", "50"]}]})
    in_range = {r["_id"] for r in rows if value(r) is not None and 0 <= value(r) <= 5_000}         # 0 to 50.00, both ends included
    assert {r["_id"] for r in shown} == {r["_id"] for r in hidden} == in_range and len(in_range) == 3   # 0.06, 0.07 and 33.50
    with pytest.raises(ValidationError, match="at most 3 decimal places"):
        parse_request(northstar_catalog(conn), BALANCES, {"filters": [{"field": "reporting_value", "operator": "equals", "value": "1.0001"}]})


def test_values_are_compared_by_the_number_shown_whatever_their_currency(conn, household):
    account_id = household["usd"]
    for day, cents in (("2026-02-01", 1_000), ("2026-02-02", 100_000)):                 # $10.00 and $1,000.00
        add_balance(conn, account_id, day, cents)
    add_balance(conn, household["jpy"], "2026-02-03", 10)                               # 10 yen shows as 10, like $10.00
    add_balance(conn, household["jpy"], "2026-02-04", 1_000)                            # 1,000 yen shows as 1,000, like $1,000.00
    conn.commit()
    rows = everything(conn, {"columns": ["account", "amount_cents"], "sort": {"field": "amount_cents", "direction": "asc"}})
    shown = [(r["amount_cents"]["value"], r["amount_cents"]["scale"]) for r in rows]
    normalised = [normalise(v, s) for v, s in shown]
    assert normalised == sorted(normalised)
    ten = [r for r in rows if normalise(r["amount_cents"]["value"], r["amount_cents"]["scale"]) == 10_000]
    assert {r["amount_cents"]["unit"] for r in ten} == {"USD", "JPY"} and [r["_id"] for r in ten] == sorted(r["_id"] for r in ten)
    at_least = everything(conn, {"columns": ["account"], "filters": [{"field": "amount_cents", "operator": "at_least", "value": "1000"}]})
    got = {r["_id"] for r in at_least}
    assert {(r["account"]) for r in at_least if r["_id"] in got} >= {"Test dollars", "Test yen"}
    assert got == {r["_id"] for r in rows if normalise(r["amount_cents"]["value"], r["amount_cents"]["scale"]) >= 1_000_000}
    exact = everything(conn, {"columns": ["account"], "filters": [{"field": "amount_cents", "operator": "equals", "value": "10"}]})
    assert {r["account"] for r in exact} == {"Test dollars", "Test yen"}
    assert {r["_id"] for r in exact} == {r["_id"] for r in rows if normalise(r["amount_cents"]["value"], r["amount_cents"]["scale"]) == 10_000}


def test_search_finds_a_balance_by_the_name_of_its_account_or_its_note(conn, household):
    assert {r["account"] for r in everything(conn, {"search": "yen"})} == {"Test yen"}
    assert len(everything(conn, {"search": "test note"})) == 1
    assert everything(conn, {"search": "deleted"}) == []


def test_grouping_balances_by_account_type_counts_each_group(conn, household):
    rows = everything(conn, {"columns": ["account"], "group": "account.type"})
    sizes = {}
    for row in rows:
        sizes[row["_group"]] = sizes.get(row["_group"], 0) + 1
    assert all(r["_group_count"] == sizes[r["_group"]] for r in rows) and set(sizes) == {"Checking", "Credit card", "Savings"}


def test_nothing_is_converted_while_the_system_currency_is_not_set_and_the_note_says_so(conn, household):
    conn.execute("UPDATE system_properties SET value = NULL, read_only = 0 WHERE name = 'system.currency'")
    rows = everything(conn, {"columns": ["account", "reporting_value"]})
    assert {r["reporting_value"]["note"] for r in rows} == {"The system currency is not set"}


def test_converting_on_today_uses_the_latest_rate_as_of_the_day_the_page_was_asked(conn, household):
    compute = conversion.reporting_value(None)
    row = {"amount_cents": 100_000, "account.currency.minor_units": 2, "account.currency": "EUR", "as_of_date": "ignored"}
    [answer] = compute(conn, ListContext(today=date(2026, 6, 3)), [row])
    assert answer.value == 110_000                                                       # 1,000.00 x 1.10
    rate(conn, "EUR", "2026-06-01", "1.20")
    [later] = compute(conn, ListContext(today=date(2026, 6, 3)), [row])
    assert later.value == 120_000
    [earlier] = compute(conn, ListContext(today=date(2026, 5, 20)), [row])
    assert earlier.value == 110_000                                                      # a later rate is never used


# -- Accounts and Users --

def test_accounts_reach_their_class_through_their_type_and_leave_out_deleted_ones(conn, household):
    rows = everything(conn, definition=ACCOUNTS)
    assert [r["name"] for r in rows] == ["Test card", "Test dollars", "Test euros", "Test yen"]
    assert {r["name"]: r["type.class"] for r in rows} == {"Test card": "Liability", "Test dollars": "Asset",
                                                          "Test euros": "Asset", "Test yen": "Asset"}
    assert {r["name"]: r["currency"] for r in rows} == {"Test card": "USD", "Test dollars": "USD", "Test euros": "EUR", "Test yen": "JPY"}
    by_class = everything(conn, {"filters": [{"field": "type.class", "operator": "is_any_of", "value": [LIABILITY]}]}, ACCOUNTS)
    assert [r["name"] for r in by_class] == ["Test card"]
    with pytest.raises(ValidationError, match="not a column"):
        parse_request(northstar_catalog(conn), ACCOUNTS, {"columns": ["class"]})


def test_users_are_listed_without_the_system_user_or_deleted_users_and_never_with_a_password(conn):
    admin = users.create_user(op(conn), "a@example.test", "Test A", "synthetic-pass-123", is_admin=True)
    users.create_user(op(conn), "b@example.test", "Test B", "synthetic-pass-123")
    gone = users.create_user(op(conn), "c@example.test", "Test C", "synthetic-pass-123")
    conn.execute("UPDATE users SET deleted = 1 WHERE id = ?", (gone,))
    rows = everything(conn, definition=USERS)
    assert [(r["display_name"], r["email"], r["is_admin"]) for r in rows] == [("Test A", "a@example.test", 1), ("Test B", "b@example.test", 0)]
    assert {r["_id"] for r in rows} >= {admin}
    assert [r["display_name"] for r in everything(conn, {"search": "b@example"}, USERS)] == ["Test B"]
    for key in ("password_hash", "is_system", "deleted"):
        with pytest.raises(ValidationError):
            parse_request(northstar_catalog(conn), USERS, {"columns": ["display_name", key]})
