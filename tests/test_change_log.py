"""The change log (migration 0008): what the writer records for every kind of write, and the rules around it.
Synthetic data only."""

import ast
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from northstar import account_types, accounts, balances, db, sessions, users, writer
from northstar.errors import ValidationError

from conftest import add_account, add_balance, op, type_id, with_db
from test_migration_runner import v01_database

ASSET, LIABILITY = 1, 2
PASSWORD = "synthetic-pass-123"
TODAY = date(2026, 10, 30)


def headers(conn):
    return [dict(row) for row in conn.execute("SELECT * FROM sys_operations ORDER BY id")]


def changes(conn, operation_id=None):
    rows = conn.execute("SELECT * FROM sys_record_changes " + ("WHERE operation_id = ? " if operation_id else "") +
                        "ORDER BY id", (operation_id,) if operation_id else ())
    return [{**dict(row), "old": json.loads(row["old_json"]) if row["old_json"] else None,
             "new": json.loads(row["new_json"]) if row["new_json"] else None} for row in rows]


def clear_log(conn):
    """Forget what the setup did, so a test sees only what it is about."""
    conn.execute("DELETE FROM sys_record_changes")
    conn.execute("DELETE FROM sys_operations")


def the_one_change(conn):
    [header] = headers(conn)
    [change] = changes(conn)
    assert change["operation_id"] == header["id"]
    return header, change


def system_id(conn):
    return conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]


@pytest.fixture
def admin(conn):
    return users.create_user(op(conn), "admin@example.com", "Admin", PASSWORD, is_admin=True)


@pytest.fixture
def checking(conn):
    account = accounts.add_account(op(conn), "Test checking", ASSET, type_id(conn, "Checking"))
    clear_log(conn)
    return account


# -- the schema rules --

def test_every_column_of_every_household_table_has_a_registry_row_and_nothing_else_does(conn):
    tables = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'sys\\_%' ESCAPE '\\' AND name NOT LIKE 'ref\\_%' ESCAPE '\\'")]
    columns = {(table, row["name"]) for table in tables for row in conn.execute(f"PRAGMA table_info({table})")}
    registry = {(row[0], row[1]) for row in conn.execute("SELECT tablename, fieldname FROM sys_audited_fields")}
    assert columns == registry, f"missing {sorted(columns - registry)}, stale {sorted(registry - columns)}"


def test_only_ids_secrets_and_generated_metadata_are_unlogged(conn):
    unlogged = {(row[0], row[1]) for row in conn.execute("SELECT tablename, fieldname FROM sys_audited_fields WHERE is_logged = 0")}
    tables = {table for table, _ in unlogged}
    expected = {(table, column) for table in tables for column in ("id", "updated_at", "updated_by")}
    expected |= {("balances", "version"), ("users", "password_hash"), ("users", "theme"), ("users", "is_system")}
    assert unlogged == expected
    logged = {(row[0], row[1]) for row in conn.execute("SELECT tablename, fieldname FROM sys_audited_fields WHERE is_logged = 1")}
    assert {(t, "created_at") for t in tables} | {(t, "created_by") for t in tables} <= logged     # so a restore keeps them
    assert {("balances", "amount_cents"), ("balances", "as_of_date"), ("accounts", "name")} <= logged


SEEDED_KINDS = {"ui_edit", "bulk_update", "import", "undo", "cli"}


def test_the_operation_kinds_are_seeded(conn):
    assert {row[0] for row in conn.execute("SELECT kind FROM sys_operation_kinds")} == SEEDED_KINDS


def test_an_operation_of_an_unknown_kind_is_refused_when_it_first_writes_and_changes_nothing(conn, checking):
    action = op(conn, kind="made_up")
    with pytest.raises(ValueError, match="'made_up' is not an operation kind. The kinds are bulk_update, cli, import, ui_edit, undo"):
        writer.update(action, "accounts", checking, {"notes": "x"})
    assert conn.execute("SELECT notes FROM accounts WHERE id = ?", (checking,)).fetchone()[0] is None
    assert headers(conn) == []


def test_a_new_kind_is_just_a_row(conn, checking):
    conn.execute("INSERT INTO sys_operation_kinds (kind) VALUES ('integration')")
    writer.update(op(conn, kind="integration"), "accounts", checking, {"notes": "x"})
    assert headers(conn)[0]["kind"] == "integration"


def kinds_used_in(source: str) -> set[str]:
    """Every operation kind written as a string in a module: the third argument of Operation(...) or operation(...), a
    kind= keyword, or the default of a parameter called kind."""
    tree = ast.parse(source)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if name in ("Operation", "operation", "op") and len(node.args) > 2 and isinstance(node.args[2], ast.Constant):
                found.add(node.args[2].value)
            found |= {kw.value.value for kw in node.keywords if kw.arg == "kind" and isinstance(kw.value, ast.Constant)}
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args.args
            for arg, default in zip(args[len(args) - len(node.args.defaults):], node.args.defaults):
                if arg.arg == "kind" and isinstance(default, ast.Constant):
                    found.add(default.value)
    return found


def test_the_scan_finds_the_kinds_in_each_way_they_are_written():
    source = ('Operation(conn, None, "cli")\noperation(request, conn, "bulk_update", {})\nop(conn, kind="undo")\n'
              'def helper(request, conn, kind: str = "ui_edit"): pass\nOperation(conn, None, kind_variable)')
    assert kinds_used_in(source) == {"cli", "bulk_update", "undo", "ui_edit"}


def test_every_kind_the_code_uses_is_a_row_in_the_table(conn):
    used = set()
    for file in sorted((Path(__file__).resolve().parent.parent / "northstar").rglob("*.py")):
        used |= kinds_used_in(file.read_text(encoding="utf-8"))
    assert {"ui_edit", "bulk_update", "cli"} <= used                       # the scan sees the call sites that exist
    assert used <= {row[0] for row in conn.execute("SELECT kind FROM sys_operation_kinds")}


def test_json_is_available_and_the_columns_check_it(conn):
    assert conn.execute("""SELECT json_extract('{"a": 1}', '$.a')""").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO sys_operations (kind, user_id, detail) VALUES ('cli', ?, 'not json')", (system_id(conn),))


def test_there_is_at_most_one_undo_per_operation_and_one_change_per_record(conn):
    me = system_id(conn)
    conn.execute("INSERT INTO sys_operations (kind, user_id) VALUES ('import', ?)", (me,))
    conn.execute("INSERT INTO sys_operations (kind, user_id, undoes_operation_id) VALUES ('undo', ?, 1)", (me,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO sys_operations (kind, user_id, undoes_operation_id) VALUES ('undo', ?, 1)", (me,))
    insert = "INSERT INTO sys_record_changes (operation_id, tablename, record_id, change) VALUES (1, 'accounts', 5, 'INSERT')"
    conn.execute(insert)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO sys_record_changes (operation_id, tablename, record_id, change) VALUES (1, 'accounts', 6, 'MOVE')")


def test_operations_use_autoincrement(conn):
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'sys_operations'").fetchone()[0]
    assert "AUTOINCREMENT" in sql.upper()


# -- creating --

def test_adding_an_account_logs_one_insert_with_every_logged_field(conn, admin):
    clear_log(conn)
    account = accounts.add_account(op(conn, admin), "Test savings", ASSET, type_id(conn, "Savings"), " a note ")
    header, change = the_one_change(conn)
    assert (header["kind"], header["user_id"], header["detail"], header["undoes_operation_id"]) == ("ui_edit", admin, None, None)
    assert (change["tablename"], change["record_id"], change["change"], change["old"]) == ("accounts", account, "INSERT", None)
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account,)).fetchone()
    assert change["new"] == {"name": "Test savings", "class_id": ASSET, "type_id": type_id(conn, "Savings"), "is_open": 1,
                             "notes": "a note", "deleted": 0,
                             "currency_id": conn.execute("SELECT id FROM currencies WHERE code = 'USD'").fetchone()[0], "created_at": row["created_at"], "created_by": admin}
    assert (row["created_by"], row["updated_by"]) == (admin, admin)             # the audit columns agree with the log


def test_values_keep_their_types_in_the_log(conn, checking):
    balances.record_balance(op(conn), checking, date(2026, 1, 31), -2500)
    new = changes(conn)[-1]["new"]
    assert new["amount_cents"] == -2500 and isinstance(new["amount_cents"], int)
    assert new["as_of_date"] == "2026-01-31" and new["note"] is None and new["source"] == "manual"


def test_adding_an_account_with_a_balance_is_one_operation_with_two_inserts(conn):
    balances.add_account_with_balance(op(conn), "asset", "Test new", type_id(conn, "Checking"), None, "12.50", "2026-01-31", TODAY)
    [header] = headers(conn)
    assert [(c["tablename"], c["change"], c["operation_id"]) for c in changes(conn)] == [
        ("accounts", "INSERT", header["id"]), ("balances", "INSERT", header["id"])]


# -- changing --

def test_an_update_logs_only_the_fields_that_changed(conn, checking, admin):
    clear_log(conn)                                    # the admin fixture was set up after the account
    accounts.update_account(op(conn, admin), checking, "Test checking", type_id(conn, "Savings"), "now with notes")
    header, change = the_one_change(conn)
    assert change["change"] == "UPDATE"
    assert change["old"] == {"type_id": type_id(conn, "Checking"), "notes": None}
    assert change["new"] == {"type_id": type_id(conn, "Savings"), "notes": "now with notes"}
    row = conn.execute("SELECT updated_by, created_by FROM accounts WHERE id = ?", (checking,)).fetchone()
    assert row["updated_by"] == admin == header["user_id"] and row["created_by"] == system_id(conn)


def test_saving_what_is_already_there_logs_nothing_and_touches_nothing(conn, checking):
    before = tuple(conn.execute("SELECT * FROM accounts WHERE id = ?", (checking,)).fetchone())
    accounts.update_account(op(conn), checking, "Test checking", type_id(conn, "Checking"))
    assert headers(conn) == [] and changes(conn) == []
    assert tuple(conn.execute("SELECT * FROM accounts WHERE id = ?", (checking,)).fetchone()) == before


def test_closing_reopening_and_changing_class_are_each_one_logged_update(conn, checking):
    accounts.close_account(op(conn), checking)
    accounts.reopen_account(op(conn), checking)
    accounts.change_class(op(conn), checking, type_id(conn, "Loan"))
    first, second, third = changes(conn)
    assert (first["old"], first["new"]) == ({"is_open": 1}, {"is_open": 0})
    assert (second["old"], second["new"]) == ({"is_open": 0}, {"is_open": 1})
    assert (third["old"], third["new"]) == ({"class_id": ASSET, "type_id": type_id(conn, "Checking")},
                                             {"class_id": LIABILITY, "type_id": type_id(conn, "Loan")})
    assert len(headers(conn)) == 3


def test_deleting_an_account_is_one_update_and_its_balances_are_not_touched(conn, checking):
    add_balance(conn, checking, "2026-01-31", 100)
    add_balance(conn, checking, "2026-02-28", 200)
    accounts.delete_account(op(conn), checking)
    header, change = the_one_change(conn)
    assert (change["tablename"], change["change"], change["old"], change["new"]) == (
        "accounts", "UPDATE", {"deleted": 0}, {"deleted": 1})
    assert conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0] == 2


def test_account_types_log_insert_update_and_delete(conn):
    new_id = account_types.add_type(op(conn), "Test type", ASSET, 40)
    account_types.update_type(op(conn), new_id, "Test type", 90)
    created = conn.execute("SELECT created_at, created_by FROM account_types WHERE id = ?", (new_id,)).fetchone()
    account_types.delete_type(op(conn), new_id)
    mine = [c for c in changes(conn) if c["record_id"] == new_id and c["tablename"] == "account_types"]
    assert [c["change"] for c in mine] == ["INSERT", "UPDATE", "DELETE"]
    assert mine[1]["old"] == {"stale_after_days": 40} and mine[1]["new"] == {"stale_after_days": 90}
    assert mine[2]["new"] is None and mine[2]["old"] == {            # everything logged, so a restore keeps the creator
        "name": "Test type", "class_id": ASSET, "stale_after_days": 90,
        "created_at": created["created_at"], "created_by": created["created_by"]}


# -- balances and their version --

def test_a_new_balance_takes_the_operations_id_as_its_version(conn, checking):
    balances.record_balance(op(conn), checking, date(2026, 1, 31), 100)
    header, change = the_one_change(conn)
    assert conn.execute("SELECT version FROM balances").fetchone()[0] == header["id"]
    assert "version" not in change["new"] and "updated_at" not in change["new"]


def test_a_changed_balance_takes_the_new_operations_id_and_logs_only_what_changed(conn, checking):
    balances.record_balance(op(conn), checking, date(2026, 1, 31), 100)
    balances.record_balance(op(conn), checking, date(2026, 1, 31), 250, "a note")
    first, second = headers(conn)
    assert conn.execute("SELECT version FROM balances").fetchone()[0] == second["id"] > first["id"]
    update = changes(conn)[-1]
    assert (update["change"], update["old"], update["new"]) == (
        "UPDATE", {"amount_cents": 100, "note": None}, {"amount_cents": 250, "note": "a note"})


def test_an_unchanged_balance_save_makes_no_operation_and_keeps_its_version(conn, checking):
    balances.record_balance(op(conn), checking, date(2026, 1, 31), 100)
    version = conn.execute("SELECT version FROM balances").fetchone()[0]
    stamp = tuple(conn.execute("SELECT updated_at, updated_by FROM balances").fetchone())
    assert balances.record_balance(op(conn), checking, date(2026, 1, 31), 100) == "unchanged"
    assert len(headers(conn)) == 1
    assert conn.execute("SELECT version FROM balances").fetchone()[0] == version
    assert tuple(conn.execute("SELECT updated_at, updated_by FROM balances").fetchone()) == stamp


def test_moving_a_balance_to_another_date_is_one_logged_update(conn, checking):
    balances.record_balance(op(conn), checking, date(2026, 1, 31), 100)
    balance_id = conn.execute("SELECT id FROM balances").fetchone()[0]
    balances.update_balance(op(conn), balance_id, "2026-02-28", "1.00", None, TODAY)
    update = changes(conn)[-1]
    assert (update["old"], update["new"]) == ({"as_of_date": "2026-01-31"}, {"as_of_date": "2026-02-28"})


def test_deleting_a_balance_logs_everything_it_had(conn, checking):
    balances.record_balance(op(conn), checking, date(2026, 1, 31), 100, "kept")
    balance_id = conn.execute("SELECT id FROM balances").fetchone()[0]
    created = conn.execute("SELECT created_at, created_by FROM balances").fetchone()
    balances.delete_balance(op(conn), balance_id)
    delete = changes(conn)[-1]
    assert (delete["change"], delete["record_id"], delete["new"]) == ("DELETE", balance_id, None)
    assert delete["old"] == {"account_id": checking, "as_of_date": "2026-01-31", "amount_cents": 100, "note": "kept",
                             "source": "manual", "created_at": created["created_at"], "created_by": created["created_by"]}


def test_a_bulk_save_is_one_operation_and_every_changed_balance_shares_its_id(conn):
    ids = [add_account(conn, f"Test {n}", ASSET, "Checking") for n in range(3)]
    clear_log(conn)
    counts = balances.save_update(op(conn, kind="bulk_update"), "2026-01-31",
                                  {ids[0]: "1.00", ids[1]: "2.00", ids[2]: ""}, TODAY)
    assert counts == {"added": 2, "updated": 0, "unchanged": 0}
    [header] = headers(conn)
    assert [c["operation_id"] for c in changes(conn)] == [header["id"]] * 2
    assert {row[0] for row in conn.execute("SELECT version FROM balances")} == {header["id"]}
    balances.save_update(op(conn, kind="bulk_update"), "2026-01-31", {ids[0]: "1.00", ids[1]: "5.00"}, TODAY)
    assert len(headers(conn)) == 2 and len(changes(conn, headers(conn)[1]["id"])) == 1       # only the one that changed


def test_a_balance_that_existed_before_the_log_has_version_zero(tmp_path):
    path = v01_database(tmp_path / "data" / "northstar.db")
    db.upgrade(path)
    conn = db.connect(path)
    assert conn.execute("SELECT version FROM balances").fetchone()[0] == 0
    assert headers(conn) == [] and changes(conn) == []                         # the upgrade writes no baseline
    balances.record_balance(op(conn), 1, date(2026, 1, 31), 99)
    assert conn.execute("SELECT version FROM balances").fetchone()[0] >= 1


def test_a_caller_cannot_set_the_version(conn, checking):
    with pytest.raises(ValueError, match="set by the writer"):
        writer.insert(op(conn), "balances", {"account_id": checking, "as_of_date": "2026-01-31", "amount_cents": 1, "version": 5})


# -- users: secrets are not logged, and unlogged changes leave no header --

def test_creating_a_user_logs_the_fields_that_are_not_secret(conn, admin):
    clear_log(conn)
    person = users.create_user(op(conn, admin), "p@example.com", "P", PASSWORD, is_admin=True)
    _, change = the_one_change(conn)
    assert change["record_id"] == person and set(change["new"]) == {
        "email", "display_name", "is_admin", "deleted", "created_at", "created_by"}
    assert change["new"]["is_admin"] == 1 and "password_hash" not in json.dumps(change)


def test_a_theme_change_or_password_change_alone_makes_no_header_but_stamps_the_row(conn, admin):
    person = users.create_user(op(conn, admin), "p@example.com", "P", PASSWORD)
    clear_log(conn)
    users.set_theme(op(conn, person), person, "light")
    users.set_user_password(op(conn, admin), person, "another-synthetic-pass-456")
    assert headers(conn) == [] and changes(conn) == []
    row = conn.execute("SELECT theme, updated_by FROM users WHERE id = ?", (person,)).fetchone()
    assert (row["theme"], row["updated_by"]) == ("light", admin)          # the later change, by the admin


def test_a_logged_edit_then_a_theme_change_leaves_only_the_edit_in_history(conn, admin):
    person = users.create_user(op(conn, admin), "p@example.com", "P", PASSWORD)
    clear_log(conn)
    users.set_display_name(op(conn, person), person, "Renamed")
    users.set_theme(op(conn, person), person, "light")
    header, change = the_one_change(conn)
    assert (change["old"], change["new"]) == ({"display_name": "P"}, {"display_name": "Renamed"})
    assert conn.execute("SELECT updated_by FROM users WHERE id = ?", (person,)).fetchone()[0] == person


def test_changing_the_name_and_theme_together_in_one_action_is_one_change(conn, admin):
    person = users.create_user(op(conn, admin), "p@example.com", "P", PASSWORD)
    clear_log(conn)
    action = op(conn, person)
    with db.write_transaction(conn):
        users.set_display_name(action, person, "Renamed")
        users.set_theme(action, person, "light")
    assert len(headers(conn)) == 1 and len(changes(conn)) == 1


def test_deleting_and_reactivating_a_user_are_each_one_update_without_secrets(conn, admin):
    person = users.create_user(op(conn, admin), "p@example.com", "P", PASSWORD, is_admin=True)
    clear_log(conn)
    users.delete_user(op(conn, admin), person, admin)
    users.add_user(op(conn, admin), "p@example.com", "P Again", "another-synthetic-pass-456")
    deleted, restored = changes(conn)
    assert (deleted["old"], deleted["new"]) == ({"deleted": 0}, {"deleted": 1})
    # Added again without an admin request, so a former admin is a regular user, and that is logged as a change.
    assert restored["old"] == {"display_name": "P", "is_admin": 1, "deleted": 1}
    assert restored["new"] == {"display_name": "P Again", "is_admin": 0, "deleted": 0}
    assert "password" not in json.dumps([deleted, restored])


def test_the_sign_in_password_upgrade_is_not_logged(conn, admin):
    person = users.create_user(op(conn, admin), "p@example.com", "P", PASSWORD)
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (_weak_hash(PASSWORD), person))
    clear_log(conn)
    assert users.authenticate(conn, "p@example.com", PASSWORD) is not None
    assert headers(conn) == []
    assert conn.execute("SELECT updated_by FROM users WHERE id = ?", (person,)).fetchone()[0] == person


def _weak_hash(password):
    import base64
    import hashlib
    salt = b"0123456789abcdef"
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**3, r=8, p=1)
    b64 = lambda raw: base64.b64encode(raw).decode()
    return f"scrypt$8$8$1${b64(salt)}${b64(digest)}"


# -- the command line and the web --

def test_the_command_line_is_the_system_user_with_the_cli_kind(tmp_path, monkeypatch):
    path = tmp_path / "data" / "northstar.db"
    db.upgrade(path)
    monkeypatch.setenv("NORTHSTAR_DB", str(path))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": PASSWORD)
    assert users.main(["create", "first@example.com", "First", "--admin"]) == 0
    conn = db.connect(path)
    [header] = headers(conn)
    assert (header["kind"], header["user_id"]) == ("cli", system_id(conn))


def test_web_actions_are_ui_edits_by_the_signed_in_user_and_the_bulk_save_says_its_date(client):
    with with_db(client) as conn:
        me = conn.execute("SELECT id FROM users WHERE email = 'test@example.com'").fetchone()[0]
        clear_log(conn)
    created = client.post("/api/accounts", json={"name": "Test api", "account_class": "asset", "type_id": 1})
    assert created.status_code == 201
    account = created.json()["accounts"][0]["id"]
    saved = client.post("/api/balances/update", json={"date": "2026-01-31", "amounts": {str(account): "10.00"}, "versions": {str(account): None}})
    assert saved.status_code == 200
    with with_db(client) as conn:
        first, second = headers(conn)
        assert (first["kind"], first["user_id"], first["detail"]) == ("ui_edit", me, None)
        assert (second["kind"], second["user_id"], json.loads(second["detail"])) == ("bulk_update", me, {"date": "2026-01-31"})


# -- atomic, and loud when misused --

def test_the_log_rolls_back_with_the_change_it_describes(conn, checking):
    with pytest.raises(RuntimeError):
        with db.write_transaction(conn):
            balances.record_balance(op(conn), checking, date(2026, 1, 31), 100)
            raise RuntimeError("something after the write failed")
    assert conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0] == 0
    assert headers(conn) == [] and changes(conn) == []


def test_changing_one_record_twice_in_one_operation_rolls_the_whole_operation_back(conn, checking):
    action = op(conn)
    with pytest.raises(writer.DuplicateChangeError):
        with db.write_transaction(conn):
            writer.update(action, "accounts", checking, {"notes": "first"})
            writer.update(action, "accounts", checking, {"notes": "second"})
    assert conn.execute("SELECT notes FROM accounts WHERE id = ?", (checking,)).fetchone()[0] is None
    assert headers(conn) == [] and changes(conn) == []


def test_an_operation_used_after_a_rollback_is_refused(conn, checking):
    action = op(conn)
    with pytest.raises(RuntimeError, match="fail"):
        with db.write_transaction(conn):
            writer.update(action, "accounts", checking, {"notes": "first"})
            raise RuntimeError("fail")
    with pytest.raises(RuntimeError, match="rolled back"):
        writer.update(action, "accounts", checking, {"notes": "again"})
    assert conn.execute("SELECT notes FROM accounts WHERE id = ?", (checking,)).fetchone()[0] is None


def test_a_column_missing_from_the_registry_stops_the_write_and_changes_nothing(conn):
    conn.execute("DELETE FROM sys_audited_fields WHERE tablename = 'accounts' AND fieldname = 'notes'")
    with pytest.raises(RuntimeError, match="accounts.notes has no row in sys_audited_fields"):
        accounts.add_account(op(conn), "Test", ASSET, type_id(conn, "Checking"))
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0 and headers(conn) == []


def test_the_registry_is_read_once_per_operation_and_table(conn, checking):
    reads = []

    class Spy:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *args):
            if "FROM sys_audited_fields" in sql:
                reads.append(sql)
            return self._inner.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    action = op(Spy(conn))
    with db.write_transaction(conn):
        writer.update(action, "accounts", checking, {"notes": "a"})
        writer.insert(action, "account_types", {"name": "X", "class_id": 1, "stale_after_days": 5})
        writer.insert(action, "account_types", {"name": "Y", "class_id": 1, "stale_after_days": 5})
    assert len(reads) == 2                                                  # accounts once, account_types once


# -- upgrading --

def test_the_upgrade_adds_the_log_without_writing_to_it(tmp_path):
    path = v01_database(tmp_path / "data" / "northstar.db")
    db.upgrade(path)
    conn = db.connect(path)
    for table in ("sys_operations", "sys_record_changes"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM sys_audited_fields").fetchone()[0] > 40
    assert {row[0] for row in conn.execute("SELECT kind FROM sys_operation_kinds")} == SEEDED_KINDS
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
