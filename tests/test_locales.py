"""The locale catalog, a person's locale and the parser that reads amounts in it. Synthetic data only.

The expected results are in frontend/src/testdata/locale_vectors.json, written by hand. The same file is read by the frontend tests."""

import importlib.util
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from conftest import add_account, op, sign_in, type_id, with_db
from fastapi.testclient import TestClient
from northstar import accounts, backup, balances, db, locales, system_properties as sp, users, writer
from northstar.errors import ValidationError
from northstar.money import parse_amount
from northstar.web.app import create_app

ROOT = Path(__file__).resolve().parent.parent
VECTORS = json.loads((ROOT / "frontend" / "src" / "testdata" / "locale_vectors.json").read_text(encoding="utf-8"))
ASSET = 1
COLUMNS = ("decimal_mark", "group_mark", "date_template", "currency_position", "currency_code_spacing")


def generator():
    """The developer tool that wrote the migration. Babel is a development requirement, so a missing Babel is a failure here."""
    spec = importlib.util.spec_from_file_location("generate_locales", ROOT / "scripts" / "generate_locales.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def locale_of(conn, tag):
    return locales.get(conn, tag)


# -- the catalog --

def test_the_six_locales_are_loaded(conn):
    assert [r["tag"] for r in conn.execute("SELECT tag FROM ref_locales ORDER BY tag")] == [
        "de-CH", "de-DE", "en-GB", "en-US", "fr-FR", "ja-JP"]


def test_the_migrated_rows_equal_what_the_generator_writes_from_cldr(conn):
    migrated = [dict(r) for r in conn.execute(
        "SELECT tag, label, decimal_mark, group_mark, date_template, currency_position, currency_code_spacing, cldr_version "
        "FROM ref_locales ORDER BY tag")]
    assert migrated == generator().rows()


def test_the_vectors_assume_the_conventions_that_are_migrated(conn):
    assert set(VECTORS["locales"]) == {r["tag"] for r in conn.execute("SELECT tag FROM ref_locales")}
    for tag, expected in VECTORS["locales"].items():
        row = conn.execute("SELECT * FROM ref_locales WHERE tag = ?", (tag,)).fetchone()
        assert {c: row[c] for c in COLUMNS} == expected, tag


def test_the_odd_characters_are_the_ones_the_design_names(conn):
    got = {r["tag"]: (r["group_mark"], r["currency_code_spacing"]) for r in conn.execute("SELECT * FROM ref_locales")}
    assert got["fr-FR"][0] == "\u202f" and got["de-CH"][0] == "\u2019"
    assert {spacing for _, spacing in got.values()} == {"\u00a0"}


def test_the_catalog_is_read_only_to_the_application(conn):
    with pytest.raises(ValueError, match="cannot be written this way"):
        writer.insert(op(conn), "ref_locales", {"tag": "xx-XX"})
    with pytest.raises(ValueError, match="cannot be written this way"):
        writer.update(op(conn), "ref_locales", 1, {"label": "x"})


@pytest.mark.parametrize("change", [
    "decimal_mark = ','", "group_mark = '.'", "decimal_mark = '', group_mark = ''", "currency_position = 'middle'",
    "label = ''", "date_template = ''", "cldr_version = ''", "decimal_mark = group_mark"])
def test_the_table_refuses_a_row_that_breaks_its_own_rules(conn, change):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f"UPDATE ref_locales SET {change} WHERE tag = 'en-US'")


def test_the_generator_refuses_a_locale_beyond_the_rules():
    g = generator()
    g.SUPPORTED["en-IN"] = "English (India)"                  # lakh grouping, 12,34,567
    g.SUPPORTED["sv-SE"] = "Swedish (Sweden)"                  # a typographic minus
    for tag in ("en-IN", "sv-SE"):
        with pytest.raises(g.Unsupported):
            g.babel_row(tag)
    with pytest.raises(g.Unsupported):
        g.date_template("EEEE d MMMM y", "xx-XX")


def test_the_generator_turns_cldr_date_patterns_into_templates():
    g = generator()
    assert g.date_template("MMM d, y", "t") == "{month_short} {day}, {year}"
    assert g.date_template("dd.MM.y", "t") == "{day2}.{month2}.{year}"
    assert g.date_template("y/MM/dd", "t") == "{year}/{month2}/{day2}"


# -- the parser: shared vectors --

@pytest.mark.parametrize("vector", VECTORS["parse_ok"], ids=lambda v: f"{v['locale']} {v['units']} {v['text']!r}")
def test_an_amount_is_read_in_the_locale(conn, vector):
    assert parse_amount(vector["text"], vector["units"], locale_of(conn, vector["locale"])) == vector["minor"]


@pytest.mark.parametrize("vector", VECTORS["parse_dollar_ok"], ids=lambda v: f"{v['locale']} {v['text']!r}")
def test_a_dollar_sign_is_accepted_only_when_the_currency_is_dollars(conn, vector):
    assert parse_amount(vector["text"], vector["units"], locale_of(conn, vector["locale"]), dollar_sign=True) == vector["minor"]


@pytest.mark.parametrize("vector", VECTORS["parse_refused"], ids=lambda v: f"{v['locale']} {v['units']} {v['text']!r}")
def test_what_the_locale_does_not_allow_is_refused_with_a_message(conn, vector):
    with pytest.raises(ValidationError) as caught:
        parse_amount(vector["text"], vector["units"], locale_of(conn, vector["locale"]))
    assert vector["says"] in str(caught.value)


def test_a_missing_locale_reads_as_us_english():
    assert parse_amount("1,234.56", 2) == 123456
    with pytest.raises(ValidationError):
        parse_amount("1.234,56", 2)


def test_look_alike_marks_are_read_only_as_the_group_mark_they_resemble(conn):
    fr, ch, us = (locale_of(conn, t) for t in ("fr-FR", "de-CH", "en-US"))
    assert parse_amount("1\u00a0234,5", 2, fr) == 123450 and parse_amount("1 234,5", 2, fr) == 123450
    assert parse_amount("1\u02bc234.5", 2, ch) == 123450
    for text, locale in (("1 234", us), ("1'234", us), ("1\u202f234", us)):          # a comma group does not take them
        with pytest.raises(ValidationError):
            parse_amount(text, 2, locale)
    with pytest.raises(ValidationError):                                                # and arbitrary spaces are not removed
        parse_amount("1 2", 2, us)


# -- a person's locale --

def test_existing_users_get_us_english_and_the_column_is_a_foreign_key(tmp_path):
    older = tmp_path / "older"
    older.mkdir()
    for file in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        if file.stem < "0011":
            shutil.copy(file, older)
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path, older)
    conn = db.connect(path)
    system = "(SELECT id FROM users WHERE is_system = 1)"            # the app cannot add a user before the catalog exists
    conn.execute(f"INSERT INTO users (email, display_name, password_hash, created_by, updated_by) "
                 f"VALUES ('a@example.com', 'Test A', '!', {system}, {system})")
    conn.commit()
    conn.close()
    assert db.upgrade(path) == ["0011_locales", "0012_rename_stale_days_property", "0013_exchange_rates", "0014_system_timezone", "0015_scheduler", "0016_rate_fetch", "0017_oidc_settings"]
    conn = db.connect(path)
    assert [r[0] for r in conn.execute("SELECT locale FROM users WHERE is_system = 0")] == ["en-US"]
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1                            # enforcement is back on
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE users SET locale = 'xx-XX'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM ref_locales WHERE tag = 'en-US'")                          # a tag in use stays


def test_the_locale_is_not_logged_like_the_theme(conn):
    assert conn.execute("SELECT is_logged FROM sys_audited_fields WHERE tablename = 'users' AND fieldname = 'locale'").fetchone()[0] == 0


def test_the_command_line_and_an_unknown_user_read_in_us_english(conn):
    assert locales.for_user(conn, None).tag == "en-US"
    assert locales.for_user(conn, 99999).tag == "en-US"


# -- the default for new users --

def locale_of_user(conn, email):
    return conn.execute("SELECT locale FROM users WHERE email = ?", (email,)).fetchone()[0]


def test_the_default_is_seeded_as_a_string_checked_by_the_catalog_with_no_lookup_rows(conn):
    row = conn.execute(
        "SELECT p.id, t.name AS type, p.value, p.allow_null, p.read_only FROM system_properties p "
        "JOIN ref_property_data_types t ON t.id = p.data_type_id WHERE p.name = 'ui.locale.default'").fetchone()
    assert (row["type"], row["value"], row["allow_null"], row["read_only"]) == ("String", "en-US", 0, 0)
    assert [r[0] for r in conn.execute("SELECT validator FROM ref_property_validators WHERE property_id = ? ORDER BY position", (row["id"],))] == ["catalog_locale"]
    assert conn.execute("SELECT COUNT(*) FROM ref_property_lookups WHERE property_id = ?", (row["id"],)).fetchone()[0] == 0


def test_a_new_user_starts_with_the_default(conn):
    users.create_user(op(conn), "a@example.com", "Test A", "synthetic-pass-123")
    assert locale_of_user(conn, "a@example.com") == "en-US"


def test_a_supported_tag_is_accepted_and_does_not_lock_the_default(conn):
    assert sp.set_property(op(conn), "ui.locale.default", "de-DE") == "de-DE"
    assert sp.set_property(op(conn), "ui.locale.default", "fr-FR") == "fr-FR"
    assert conn.execute("SELECT read_only FROM system_properties WHERE name = 'ui.locale.default'").fetchone()[0] == 0


@pytest.mark.parametrize("text", ["xx-XX", "de-de", "German", "en_US", "en-US; DROP TABLE users", "' OR '1'='1"])
def test_an_unsupported_tag_is_refused_and_nothing_changes(conn, text):
    with pytest.raises(ValidationError, match="isn't a supported number and date format"):
        sp.set_property(op(conn), "ui.locale.default", text)
    assert sp.get_value(conn, "ui.locale.default") == "en-US"


def test_a_changed_default_applies_to_new_users_only(conn):
    users.create_user(op(conn), "old@example.com", "Test Old", "synthetic-pass-123")
    sp.set_property(op(conn), "ui.locale.default", "ja-JP")
    users.create_user(op(conn), "new@example.com", "Test New", "synthetic-pass-123")
    assert (locale_of_user(conn, "old@example.com"), locale_of_user(conn, "new@example.com")) == ("en-US", "ja-JP")


def test_a_reactivated_user_takes_the_current_default(conn):
    admin = users.create_user(op(conn), "admin@example.com", "Test Admin", "synthetic-pass-123", is_admin=True)
    target = users.create_user(op(conn), "gone@example.com", "Test Gone", "synthetic-pass-123")
    conn.execute("UPDATE users SET locale = 'fr-FR' WHERE id = ?", (target,))
    users.delete_user(op(conn, admin), target, admin)
    sp.set_property(op(conn), "ui.locale.default", "de-DE")
    assert users.create_user(op(conn), "gone@example.com", "Test Gone", "synthetic-pass-123") == target
    assert locale_of_user(conn, "gone@example.com") == "de-DE"


def test_the_command_line_adds_users_with_the_default_too(conn):
    sp.set_property(op(conn, kind="cli"), "ui.locale.default", "en-GB")
    users.create_user(op(conn, kind="cli"), "cli@example.com", "Test Cli", "synthetic-pass-123")
    assert locale_of_user(conn, "cli@example.com") == "en-GB"


def test_a_default_the_catalog_does_not_know_stops_a_user_being_added_and_says_why(conn):
    conn.execute("UPDATE system_properties SET value = 'xx-XX' WHERE name = 'ui.locale.default'")
    with pytest.raises(ValidationError, match="ui.locale.default"):
        users.create_user(op(conn), "a@example.com", "Test A", "synthetic-pass-123")
    assert conn.execute("SELECT COUNT(*) FROM users WHERE email = 'a@example.com'").fetchone()[0] == 0


# -- money is read in the signed-in person's locale --

def use_locale(conn, email, tag):
    conn.execute("UPDATE users SET locale = ? WHERE email = ?", (tag, email))


def test_an_amount_is_read_in_the_locale_of_the_person_who_enters_it(conn):
    from datetime import date
    admin = users.create_user(op(conn), "admin@example.com", "Test Admin", "synthetic-pass-123", is_admin=True)
    use_locale(conn, "admin@example.com", "de-DE")
    account = add_account(conn, "Test savings", ASSET, "Savings")
    assert balances.add_balance(op(conn, admin), account, "2026-01-31", "1.234,56", None, date(2026, 2, 1)) == "added"
    assert conn.execute("SELECT amount_cents FROM live_balances").fetchone()[0] == 123456
    with pytest.raises(ValidationError, match="Use , for decimals"):
        balances.add_balance(op(conn, admin), account, "2026-02-01", "12.50", None, date(2026, 2, 2))
    assert balances.add_balance(op(conn), account, "2026-02-01", "12.50", None, date(2026, 2, 2)) == "added"   # the command line reads US English


def test_every_way_of_entering_money_uses_the_locale(conn):
    from datetime import date
    admin = users.create_user(op(conn), "admin@example.com", "Test Admin", "synthetic-pass-123", is_admin=True)
    use_locale(conn, "admin@example.com", "fr-FR")
    first = add_account(conn, "Test one", ASSET, "Savings")
    today = date(2026, 2, 1)
    balances.add_balance(op(conn, admin), first, "2026-01-31", "1\u202f000,5", None, today)
    entry = conn.execute("SELECT id FROM live_balances WHERE account_id = ?", (first,)).fetchone()[0]
    assert balances.update_balance(op(conn, admin), entry, "2026-01-31", "2 000,25", None, today) == "updated"
    assert balances.save_update(op(conn, admin), "2026-02-01", {first: "3\u00a0000,75"}, today) == {"added": 1, "updated": 0, "unchanged": 0}
    balances.add_account_with_balance(op(conn, admin), "asset", "Test two", type_id(conn, "Savings"), None, "4 000,5", None, today)
    assert sorted(r[0] for r in conn.execute("SELECT amount_cents FROM live_balances")) == [200025, 300075, 400050]
    with pytest.raises(balances.EntryErrors):
        balances.save_update(op(conn, admin), "2026-02-01", {first: "3.000,75"}, today)


# -- the web --

def test_me_carries_the_locale_and_its_formatting_fields(client):
    me = client.get("/api/me").json()
    assert me["locale"] == {
        "tag": "en-US", "label": "English (United States)", "decimal_mark": ".", "group_mark": ",",
        "date_template": "{month_short} {day}, {year}", "currency_position": "prefix", "currency_code_spacing": "\u00a0"}


def test_me_follows_the_users_own_locale(tmp_path):
    client = sign_in(TestClient(create_app(tmp_path / "web.db")))
    with with_db(client) as conn:
        use_locale(conn, "test@example.com", "de-CH")
    assert client.get("/api/me").json()["locale"]["group_mark"] == "\u2019"


def test_the_properties_page_lists_the_locales_for_its_search_box(client):
    listed = client.get("/api/system-properties").json()
    assert {"tag": "de-CH", "label": "German (Switzerland)"} in listed["locales"]
    assert len(listed["locales"]) == 6


def test_an_admin_sets_the_default_from_the_page_and_a_bad_tag_is_a_422(client):
    refused = client.put("/api/system-properties/ui.locale.default", json={"value": "nope"})
    assert refused.status_code == 422 and "isn't a supported number and date format" in refused.json()["detail"]
    saved = client.put("/api/system-properties/ui.locale.default", json={"value": "fr-FR"})
    row = {p["name"]: p for p in saved.json()["properties"]}["ui.locale.default"]
    assert (row["value"], row["read_only"], row["options"]) == ("fr-FR", False, [])


def test_the_api_reads_an_entered_amount_in_the_users_locale(tmp_path):
    client = sign_in(TestClient(create_app(tmp_path / "web.db")))
    with with_db(client) as conn:
        use_locale(conn, "test@example.com", "de-DE")
        account = add_account(conn, "Test savings", ASSET, "Savings")
    ok = client.post(f"/api/accounts/{account}/balances", json={"date": "2026-01-31", "amount": "1.234,56"})
    assert ok.status_code == 200
    refused = client.post(f"/api/accounts/{account}/balances", json={"date": "2026-02-28", "amount": "1,234.56"})
    assert refused.status_code == 422
    with with_db(client) as conn:
        assert [r[0] for r in conn.execute("SELECT amount_cents FROM live_balances")] == [123456]


# -- upgrade, backup and restore --

def test_a_backup_of_the_new_version_restores_with_its_locales(tmp_path):
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path)
    copy = tmp_path / "copy.db"
    backup.create_backup(path, copy)
    restored = tmp_path / "again" / "northstar.db"
    backup.restore_backup(copy, restored)
    conn = db.connect(restored)
    assert conn.execute("SELECT COUNT(*) FROM ref_locales").fetchone()[0] == 6
    assert sp.get_value(conn, "ui.locale.default") == "en-US"
