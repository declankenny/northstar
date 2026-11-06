"""The currency catalog, the currency of an account and the system currency. Synthetic data only."""

import re
import shutil
import sqlite3

import pytest

from datetime import date

from fastapi.testclient import TestClient

from conftest import add_account, op, sign_in, type_id, with_db
from northstar import accounts, backup, balance_export, balances, currencies, db, system_properties as sp
from northstar.errors import ValidationError
from northstar.money import MAX_MINOR, format_plain, parse_amount
from northstar.web.app import create_app

ASSET_CLASS = 1


def unset_currency(conn):
    """The state of a fresh installation: no system currency, and the setting not yet locked."""
    conn.execute("UPDATE system_properties SET value = NULL, read_only = 0 WHERE name = 'system.currency'")


def use_currency(conn, code):
    """Set the system currency by the same route an administrator does, so it is checked and locked."""
    unset_currency(conn)
    sp.set_property(op(conn), "system.currency", code)


def currency_id(conn, code):
    return conn.execute("SELECT id FROM currencies WHERE code = ?", (code,)).fetchone()[0]


# -- the catalog --

def test_the_catalog_has_the_155_currencies_from_the_proposal(conn):
    rows = {r["code"]: r for r in conn.execute("SELECT * FROM currencies")}
    assert len(rows) == 155
    by_precision = {k: sum(1 for r in rows.values() if r["minor_units"] == k) for k in (0, 2, 3)}
    assert by_precision == {0: 16, 2: 132, 3: 7}
    assert (rows["USD"]["minor_units"], rows["JPY"]["minor_units"], rows["KWD"]["minor_units"]) == (2, 0, 3)
    assert rows["USD"]["name"] == "US Dollar"
    assert {r["is_enabled"] for r in rows.values()} == {0}


@pytest.mark.parametrize("code", [
    "XAU", "XAG", "XPT", "XPD", "XDR", "XTS", "XXX", "XBA", "XSU", "XUA",     # metals, units of account, special codes
    "BOV", "CHE", "CHW", "CLF", "COU", "MXV", "USN", "UYI", "UYW", "XAD",     # funds
    "HRK", "BGN"])                                                             # withdrawn, so not in the current list
def test_no_fund_metal_special_or_withdrawn_code_is_in_the_catalog(conn, code):
    assert conn.execute("SELECT 1 FROM currencies WHERE code = ?", (code,)).fetchone() is None


def test_the_shared_codes_are_one_row_each(conn):
    for code in ("EUR", "USD", "XOF", "XAF", "XPF", "XCD"):
        assert conn.execute("SELECT COUNT(*) FROM currencies WHERE code = ?", (code,)).fetchone()[0] == 1


def test_the_catalog_is_authored_by_the_system_user(conn):
    system = conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]
    assert {tuple(r) for r in conn.execute("SELECT created_by, updated_by FROM currencies")} == {(system, system)}


def test_a_currency_cannot_be_deleted_changed_in_code_or_precision_but_can_be_enabled(conn):
    for sql in ("DELETE FROM currencies WHERE code = 'JPY'", "UPDATE currencies SET code = 'JPX' WHERE code = 'JPY'",
                "UPDATE currencies SET minor_units = 2 WHERE code = 'JPY'"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(sql)
    conn.execute("UPDATE currencies SET is_enabled = 1 WHERE code = 'JPY'")
    assert conn.execute("SELECT is_enabled FROM currencies WHERE code = 'JPY'").fetchone()[0] == 1


def test_the_code_must_be_three_capital_letters_and_the_precision_0_2_or_3(conn):
    system = "(SELECT id FROM users WHERE is_system = 1)"
    for code, units in (("usd", 2), ("US", 2), ("ABCD", 2), ("AB1", 2), ("ZZZ", 4), ("ZZZ", 1)):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"INSERT INTO currencies (code, name, minor_units, created_by, updated_by) "
                         f"VALUES (?, 'Test', ?, {system}, {system})", (code, units))


# -- an account's currency --

def test_an_account_is_created_in_the_system_currency(conn):
    use_currency(conn, "JPY")
    account = accounts.add_account(op(conn), "Test savings", ASSET_CLASS, type_id(conn, "Savings"))
    assert currencies.account_currency(conn, account).code == "JPY"


def test_an_accounts_currency_cannot_be_changed(conn):
    account = add_account(conn, "Test savings", ASSET_CLASS, "Savings")
    with pytest.raises(sqlite3.IntegrityError, match="cannot be changed"):
        conn.execute("UPDATE accounts SET currency_id = ? WHERE id = ?", (currency_id(conn, "EUR"), account))
    assert currencies.account_currency(conn, account).code == "USD"


def test_an_account_needs_a_currency_the_database_has_no_default(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO accounts (name, class_id, type_id, created_by, updated_by) VALUES ('X', 1, 1, 1, 1)")


def test_an_account_cannot_be_given_a_currency_that_is_not_enabled(conn):
    with pytest.raises(ValidationError, match="enabled"):
        accounts.add_account(op(conn), "Test savings", ASSET_CLASS, type_id(conn, "Savings"), None, currency_id(conn, "EUR"))
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0


def test_an_enabled_currency_can_be_chosen_and_the_account_keeps_it(conn):
    conn.execute("UPDATE currencies SET is_enabled = 1 WHERE code = 'KWD'")
    account = accounts.add_account(op(conn), "Test savings", ASSET_CLASS, type_id(conn, "Savings"), None,
                                   currency_id(conn, "KWD"))
    assert currencies.account_currency(conn, account).code == "KWD"
    assert balances.add_balance(op(conn), account, "2026-01-31", "1.234", None, date(2026, 2, 1)) == "added"
    assert conn.execute("SELECT amount_cents FROM live_balances WHERE account_id = ?", (account,)).fetchone()[0] == 1234


def test_the_system_currency_is_usable_whether_or_not_it_is_enabled(conn):
    assert conn.execute("SELECT is_enabled FROM currencies WHERE code = 'USD'").fetchone()[0] == 0
    assert currencies.is_usable(conn, currency_id(conn, "USD"))
    assert not currencies.is_usable(conn, currency_id(conn, "EUR"))


# -- the guard while the system currency is unset --

def test_no_account_can_be_added_while_the_system_currency_is_unset(conn):
    unset_currency(conn)
    with pytest.raises(ValidationError, match="Choose the system currency first"):
        accounts.add_account(op(conn), "Test savings", ASSET_CLASS, type_id(conn, "Savings"))
    with pytest.raises(ValidationError, match="Choose the system currency first"):
        balances.add_account_with_balance(op(conn), "asset", "Test savings", type_id(conn, "Savings"), None, "5", None,
                                          date(2026, 2, 1))
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0


def test_the_server_refuses_to_add_an_account_while_it_is_unset_and_the_list_says_so(tmp_path):
    client = sign_in(TestClient(create_app(tmp_path / "web.db")))
    with with_db(client) as conn:
        unset_currency(conn)
        savings = type_id(conn, "Savings")
    assert client.get("/api/accounts").json()["currency"] is None
    response = client.post("/api/accounts", json={"account_class": "asset", "name": "Test savings", "type_id": savings})
    assert response.status_code == 422 and "Choose the system currency first" in response.json()["detail"]
    with with_db(client) as conn:
        assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0
        sp.set_property(op(conn), "system.currency", "EUR")
    assert client.get("/api/accounts").json()["currency"] == {"code": "EUR", "name": "Euro", "minor_units": 2}
    assert client.post("/api/accounts", json={"account_class": "asset", "name": "Test savings", "type_id": savings}).status_code == 201


def test_me_carries_the_system_currency(client):
    assert client.get("/api/me").json()["currency"] == {"code": "USD", "name": "US Dollar", "minor_units": 2}
    with with_db(client) as conn:
        unset_currency(conn)
    assert client.get("/api/me").json()["currency"] is None


# -- the system currency --

def test_a_fresh_installation_has_it_unset_and_unlocked(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.migrate(conn)
    row = conn.execute("SELECT value, read_only, allow_null FROM system_properties WHERE name = 'system.currency'").fetchone()
    assert (row["value"], row["read_only"], row["allow_null"]) == (None, 0, 0)
    assert currencies.system_currency(conn) is None


def test_it_is_validated_by_the_catalog_not_by_its_shape(conn):
    names = [r[0] for r in conn.execute(
        "SELECT validator FROM ref_property_validators v JOIN system_properties p ON p.id = v.property_id "
        "WHERE p.name = 'system.currency' ORDER BY position")]
    assert names == ["catalog_currency"]
    unset_currency(conn)
    for text in ("ZZZ", "usd", "US", "XAU", "BGN"):
        with pytest.raises(ValidationError, match="isn't a currency in the catalog"):
            sp.set_property(op(conn), "system.currency", text)
    assert sp.get_value(conn, "system.currency") is None


def test_setting_it_stores_the_code_and_locks_it_in_the_same_audited_change(conn):
    unset_currency(conn)
    conn.execute("DELETE FROM sys_record_changes")
    conn.execute("DELETE FROM sys_operations")
    assert sp.set_property(op(conn), "system.currency", " JPY ") == "JPY"
    row = conn.execute("SELECT value, read_only FROM system_properties WHERE name = 'system.currency'").fetchone()
    assert (row["value"], row["read_only"]) == ("JPY", 1)
    [change] = conn.execute("SELECT new_json FROM sys_record_changes WHERE tablename = 'system_properties'").fetchall()
    assert re.search(r'"value": ?"JPY"', change[0]) and re.search(r'"read_only": ?1', change[0])
    with pytest.raises(ValidationError, match="locked"):
        sp.set_property(op(conn), "system.currency", "EUR")
    assert currencies.system_currency(conn).code == "JPY"


def test_it_cannot_be_set_once_an_account_exists_even_if_it_were_unlocked(conn):
    add_account(conn, "Test savings", ASSET_CLASS, "Savings")
    conn.execute("UPDATE system_properties SET read_only = 0 WHERE name = 'system.currency'")
    with pytest.raises(ValidationError, match="once an account exists"):
        sp.set_property(op(conn), "system.currency", "EUR")
    assert sp.get_value(conn, "system.currency") == "USD"


def test_a_deleted_account_still_counts(conn):
    account = add_account(conn, "Test savings", ASSET_CLASS, "Savings")
    accounts.delete_account(op(conn), account)
    conn.execute("UPDATE system_properties SET read_only = 0 WHERE name = 'system.currency'")
    with pytest.raises(ValidationError, match="once an account exists"):
        sp.set_property(op(conn), "system.currency", "EUR")


def test_the_page_lists_the_catalog_for_its_search_box(client):
    listed = client.get("/api/system-properties").json()
    assert len(listed["currencies"]) == 155
    assert {"code": "KWD", "name": "Kuwaiti Dinar", "minor_units": 3} in listed["currencies"]


def test_an_admin_sets_it_through_the_page_endpoint_and_a_bad_code_is_a_422(client):
    with with_db(client) as conn:
        unset_currency(conn)
    refused = client.put("/api/system-properties/system.currency", json={"value": "usd"})
    assert refused.status_code == 422 and "isn't a currency in the catalog" in refused.json()["detail"]
    saved = client.put("/api/system-properties/system.currency", json={"value": "CHF"})
    assert saved.status_code == 200
    row = {p["name"]: p for p in saved.json()["properties"]}["system.currency"]
    assert (row["value"], row["read_only"]) == ("CHF", True)


# -- precision and entry limits per currency --

@pytest.mark.parametrize("text, units, expected", [
    ("1234", 0, 1234), ("1,234", 0, 1234), ("-25", 0, -25), ("0", 0, 0),
    ("1234.56", 2, 123456), ("1,234.5", 2, 123450), ("-25.00", 2, -2500), (".5", 2, 50), ("7", 2, 700),
    ("1.234", 3, 1234), ("1.2", 3, 1200), ("-0.001", 3, -1), ("12", 3, 12000),
])
def test_an_amount_is_read_in_the_currencys_minor_units(text, units, expected):
    assert parse_amount(text, units) == expected


@pytest.mark.parametrize("text, units", [
    ("12.5", 0), ("12.", 0), ("1.", 2), ("1.234", 2), ("1.2345", 3), (".", 2), ("", 2), ("-", 2), ("abc", 2),
    ("1,23", 2), ("1e3", 2), ("$5", 2), ("١٢٣", 2),
])
def test_more_decimals_than_the_currency_has_is_refused_never_rounded(text, units):
    with pytest.raises(ValidationError):
        parse_amount(text, units)


def test_the_dollar_sign_is_only_for_dollars():
    assert parse_amount("-$25", 2, dollar_sign=True) == -2500
    with pytest.raises(ValidationError):
        parse_amount("$25", 0)


@pytest.mark.parametrize("units", [0, 2, 3])
def test_the_ceiling_is_the_same_count_of_minor_units_for_every_currency(units):
    assert parse_amount(str(MAX_MINOR // 10**units) + ("" if units == 0 else "." + "9" * units), units) <= MAX_MINOR
    with pytest.raises(ValidationError, match="too large"):
        parse_amount(str((MAX_MINOR + 1) // 10**units + 1), units)


def test_the_error_message_shows_an_example_with_the_right_number_of_places():
    for units, example in ((0, "1234 or -25"), (2, "1234.56 or -25.00"), (3, "1234.567 or -25.000")):
        with pytest.raises(ValidationError) as caught:
            parse_amount("x", units)
        assert example in str(caught.value)


@pytest.mark.parametrize("amount, units, text", [
    (123456, 2, "1234.56"), (-8000, 2, "-80.00"), (5, 2, "0.05"), (1234, 0, "1234"), (-7, 0, "-7"), (1234, 3, "1.234"),
    (-1, 3, "-0.001"), (0, 3, "0.000"), (0, 0, "0")])
def test_the_plain_form_has_the_currencys_digits(amount, units, text):
    assert format_plain(amount, units) == text
    assert parse_amount(text, units) == amount


@pytest.mark.parametrize("code, typed, stored, exported", [
    ("JPY", "12,345", 12345, "12345"), ("KWD", "12.345", 12345, "12.345"), ("USD", "123.45", 12345, "123.45")])
def test_an_amount_is_stored_in_the_minor_unit_and_exported_with_the_same_digits(conn, code, typed, stored, exported):
    use_currency(conn, code)
    account = accounts.add_account(op(conn), "Test savings", ASSET_CLASS, type_id(conn, "Savings"))
    assert balances.add_balance(op(conn), account, "2026-01-31", typed, None, date(2026, 2, 1)) == "added"
    assert conn.execute("SELECT amount_cents FROM live_balances WHERE account_id = ?", (account,)).fetchone()[0] == stored
    assert balance_export.export_csv(conn, account).splitlines()[1].endswith("," + exported)


def test_an_account_in_yen_refuses_decimals_in_every_way_amounts_are_entered(conn):
    use_currency(conn, "JPY")
    first = accounts.add_account(op(conn), "Test one", ASSET_CLASS, type_id(conn, "Savings"))
    second = accounts.add_account(op(conn), "Test two", ASSET_CLASS, type_id(conn, "Savings"))
    today = date(2026, 2, 1)
    with pytest.raises(ValidationError, match="Enter a whole amount like 1234"):
        balances.add_balance(op(conn), first, "2026-01-31", "10.5", None, today)
    balances.add_balance(op(conn), first, "2026-01-31", "10", None, today)
    entry = conn.execute("SELECT id FROM live_balances WHERE account_id = ?", (first,)).fetchone()[0]
    with pytest.raises(ValidationError):
        balances.update_balance(op(conn), entry, "2026-01-31", "10.5", None, today)
    with pytest.raises(balances.EntryErrors) as caught:
        balances.save_update(op(conn), "2026-01-31", {first: "11", second: "1.5"}, today)
    assert list(caught.value.by_account) == [second]
    with pytest.raises(ValidationError):
        balances.add_account_with_balance(op(conn), "asset", "Test three", type_id(conn, "Savings"), None, "2.5", None, today)
    assert conn.execute("SELECT COUNT(*) FROM live_accounts").fetchone()[0] == 2


def test_the_importer_accepts_a_whole_unit_account(conn):
    from northstar import balance_import
    use_currency(conn, "JPY")
    account = accounts.add_account(op(conn), "Test savings", ASSET_CLASS, type_id(conn, "Savings"))
    assert balance_import.plan_import(conn, account, []).errors == []


# -- upgrading from v0.2 on a copy of a database --

V02 = ["0001_initial", "0002_login_attempts", "0003_unique_account_names", "0004_audit_columns_and_system_user",
       "0005_sys_table_names", "0006_user_soft_delete", "0007_account_soft_delete", "0008_change_log", "0009_system_properties"]


@pytest.fixture
def v02_migrations(tmp_path):
    folder = tmp_path / "v02"
    folder.mkdir()
    for name in V02:
        shutil.copy(db.MIGRATIONS_DIR / f"{name}.sql", folder)
    return folder


def v02_database(tmp_path, v02_migrations, accounts_to_add=1, delete_all=False):
    """A database as v0.2 left it (before this migration) holding synthetic accounts and balances."""
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path, v02_migrations)
    conn = db.connect(path)
    system = "(SELECT id FROM users WHERE is_system = 1)"
    for number in range(accounts_to_add):
        conn.execute(f"INSERT INTO accounts (name, class_id, type_id, deleted, created_by, updated_by) "
                     f"VALUES (?, 1, 1, ?, {system}, {system})", (f"Test account {number}", 1 if delete_all else 0))
        conn.execute(f"INSERT INTO balances (account_id, as_of_date, amount_cents, created_by, updated_by) "
                     f"VALUES (?, '2026-01-31', 123456, {system}, {system})", (number + 1,))
    conn.commit()
    conn.close()
    return path


def test_an_upgrade_with_accounts_makes_them_dollars_and_locks_the_system_currency(tmp_path, v02_migrations):
    path = v02_database(tmp_path, v02_migrations, accounts_to_add=2)
    assert db.upgrade(path) == ["0010_currencies", "0011_locales", "0012_rename_stale_days_property"]
    conn = db.connect(path)
    assert [r[0] for r in conn.execute("SELECT c.code FROM accounts a JOIN currencies c ON c.id = a.currency_id")] == ["USD", "USD"]
    assert [r[0] for r in conn.execute("SELECT amount_cents FROM live_balances")] == [123456, 123456]     # no amount changed
    row = conn.execute("SELECT value, read_only FROM system_properties WHERE name = 'system.currency'").fetchone()
    assert (row["value"], row["read_only"]) == ("USD", 1)
    assert currencies.system_currency(conn).code == "USD"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'")} == {"live_accounts", "live_balances"}


def test_an_upgrade_with_only_a_deleted_account_still_counts_as_having_one(tmp_path, v02_migrations):
    path = v02_database(tmp_path, v02_migrations, delete_all=True)
    db.upgrade(path)
    conn = db.connect(path)
    assert (sp.get_value(conn, "system.currency"),
            conn.execute("SELECT read_only FROM system_properties WHERE name = 'system.currency'").fetchone()[0]) == ("USD", 1)


def test_an_upgrade_with_no_account_leaves_the_system_currency_unset(tmp_path, v02_migrations):
    path = v02_database(tmp_path, v02_migrations, accounts_to_add=0)
    db.upgrade(path)
    conn = db.connect(path)
    row = conn.execute("SELECT value, read_only FROM system_properties WHERE name = 'system.currency'").fetchone()
    assert (row["value"], row["read_only"]) == (None, 0)
    with pytest.raises(ValidationError, match="Choose the system currency first"):
        accounts.add_account(op(conn), "Test savings", ASSET_CLASS, type_id(conn, "Savings"))


def test_the_upgrade_keeps_the_audit_trail_and_the_unique_name_rule(tmp_path, v02_migrations):
    path = v02_database(tmp_path, v02_migrations, accounts_to_add=1)
    db.upgrade(path)
    conn = db.connect(path)
    row = conn.execute("SELECT created_by, updated_by FROM accounts").fetchone()
    system = conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]
    assert (row["created_by"], row["updated_by"]) == (system, system)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO accounts (name, class_id, type_id, currency_id, created_by, updated_by) "
                     "VALUES ('TEST ACCOUNT 0', 1, 1, 1, ?, ?)", (system, system))


def test_a_backup_is_made_before_the_upgrade_and_restores_to_the_old_version(tmp_path, v02_migrations):
    path = v02_database(tmp_path, v02_migrations, accounts_to_add=1)
    db.upgrade(path)
    [saved] = sorted((path.parent / "backups").glob("pre-migration-*.db"))
    assert backup.check_database(saved)["migrations"] == len(V02)       # a valid database as it was before
    restored = tmp_path / "restored" / "northstar.db"
    backup.restore_backup(saved, restored)
    conn = sqlite3.connect(restored)
    assert "currencies" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert conn.execute("SELECT amount_cents FROM balances").fetchone()[0] == 123456
    conn.close()
    assert db.upgrade(restored) == ["0010_currencies", "0011_locales", "0012_rename_stale_days_property"]               # and the old version upgrades again


def test_a_backup_of_the_new_version_restores_with_its_currencies(tmp_path, v02_migrations):
    path = v02_database(tmp_path, v02_migrations, accounts_to_add=1)
    db.upgrade(path)
    copy = tmp_path / "copy.db"
    backup.create_backup(path, copy)
    assert backup.check_database(copy)["migrations"] == len(V02) + 3
    restored = tmp_path / "again" / "northstar.db"
    backup.restore_backup(copy, restored)
    conn = db.connect(restored)
    assert conn.execute("SELECT COUNT(*) FROM currencies").fetchone()[0] == 155
    assert currencies.account_currency(conn, 1).code == "USD" and currencies.system_currency(conn).code == "USD"
