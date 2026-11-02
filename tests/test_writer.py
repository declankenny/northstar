"""The write chokepoint: every write the application makes goes through northstar.writer. Synthetic data only."""

import ast
import re
import sqlite3
from pathlib import Path

import pytest

from northstar import db, writer
from northstar.writer import Operation

from conftest import add_account, add_balance, op


def balance_row(conn, account_id=None):
    return conn.execute("SELECT * FROM balances ORDER BY id LIMIT 1").fetchone()


@pytest.fixture
def balance(conn):
    account = add_account(conn, "Test account", 1, "Checking")
    add_balance(conn, account, "2026-01-31", 10000)
    conn.execute("UPDATE balances SET updated_at = '2020-01-01T00:00:00Z'")
    return balance_row(conn)["id"]


# -- the operation --

def test_an_operation_carries_the_connection_and_the_actor(conn):
    operation = Operation(conn, 7)
    assert operation.conn is conn and operation.actor_id == 7
    with pytest.raises(AttributeError):
        operation.actor_id = 8                                   # one action has one author


# -- insert --

def test_insert_adds_a_row_and_returns_its_id(conn):
    new_id = writer.insert(op(conn), "account_types", {"name": "Test type", "class_id": 1, "stale_after_days": 40})
    row = conn.execute("SELECT * FROM account_types WHERE id = ?", (new_id,)).fetchone()
    assert (row["name"], row["class_id"], row["stale_after_days"]) == ("Test type", 1, 40)


def test_a_database_rule_still_refuses_a_bad_insert(conn):
    with pytest.raises(sqlite3.IntegrityError):
        writer.insert(op(conn), "account_types", {"name": "Zero", "class_id": 1, "stale_after_days": 0})


# -- update --

def test_update_changes_the_fields_and_says_so(conn, balance):
    assert writer.update(op(conn), "balances", balance, {"amount_cents": 25000, "note": "a note"}) is True
    row = balance_row(conn)
    assert (row["amount_cents"], row["note"]) == (25000, "a note")


def test_update_with_nothing_different_touches_nothing(conn, balance):
    before = tuple(balance_row(conn))
    assert writer.update(op(conn), "balances", balance, {"amount_cents": 10000}) is False
    assert tuple(balance_row(conn)) == before                                  # not even updated_at or updated_by


def test_update_of_a_missing_row_changes_nothing(conn):
    assert writer.update(op(conn), "balances", 999, {"amount_cents": 1}) is False


def test_update_only_if_the_guard_still_holds(conn):
    user = conn.execute("INSERT INTO users (email, display_name, password_hash, created_by, updated_by) VALUES ('a@example.com', 'A', 'old', (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1))").lastrowid
    assert writer.update(op(conn), "users", user, {"password_hash": "new"}, only_if={"password_hash": "stale"}) is False
    assert conn.execute("SELECT password_hash FROM users WHERE id = ?", (user,)).fetchone()[0] == "old"
    assert writer.update(op(conn), "users", user, {"password_hash": "new"}, only_if={"password_hash": "old"}) is True
    assert conn.execute("SELECT password_hash FROM users WHERE id = ?", (user,)).fetchone()[0] == "new"


def test_a_database_rule_still_refuses_a_bad_update(conn):
    types = [row[0] for row in conn.execute("SELECT id FROM account_types ORDER BY id")]
    with pytest.raises(sqlite3.IntegrityError):
        writer.update(op(conn), "account_types", types[0], {"name": "savings"})      # another type's name, ignoring case


# -- the audit columns --

def system_user(conn):
    return conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]


def person(conn, email="p@example.com"):
    return writer.insert(op(conn), "users", {"email": email, "display_name": "P", "password_hash": "x"})


def test_an_insert_is_authored_by_the_actor(conn):
    actor = person(conn)
    new_id = writer.insert(Operation(conn, actor), "account_types", {"name": "Test type", "class_id": 1, "stale_after_days": 40})
    row = conn.execute("SELECT * FROM account_types WHERE id = ?", (new_id,)).fetchone()
    assert (row["created_by"], row["updated_by"]) == (actor, actor)
    assert row["created_at"] and row["updated_at"]


def test_an_operation_with_no_actor_is_made_by_the_system_user(conn):
    new_id = writer.insert(op(conn), "account_types", {"name": "Test type", "class_id": 1, "stale_after_days": 40})
    row = conn.execute("SELECT * FROM account_types WHERE id = ?", (new_id,)).fetchone()
    assert (row["created_by"], row["updated_by"]) == (system_user(conn), system_user(conn))


def test_a_real_change_stamps_who_and_when_and_leaves_the_creator_alone(conn, balance):
    actor = person(conn)
    conn.execute("UPDATE balances SET created_at = '2019-06-15T12:00:00Z'")      # long ago, so a rewrite to now would show
    created_by = balance_row(conn)["created_by"]
    assert writer.update(Operation(conn, actor), "balances", balance, {"amount_cents": 1}) is True
    row = balance_row(conn)
    assert row["updated_by"] == actor and row["created_by"] == created_by
    assert row["created_at"] == "2019-06-15T12:00:00Z"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", row["updated_at"]) and row["updated_at"] > "2020-01-01T00:00:00Z"


@pytest.mark.parametrize("column", ["created_by", "updated_by", "created_at", "updated_at"])
def test_a_caller_cannot_set_the_audit_columns(conn, balance, column):
    with pytest.raises(ValueError, match="set by the writer"):
        writer.insert(op(conn), "account_types", {"name": "X", "class_id": 1, "stale_after_days": 5, column: 1})
    with pytest.raises(ValueError, match="set by the writer"):
        writer.update(op(conn), "balances", balance, {column: 1})


# -- delete --

def test_delete_removes_the_row(conn, balance):
    writer.delete(op(conn), "balances", balance)
    assert conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0] == 0


def test_writes_roll_back_with_the_transaction_they_are_in(conn):
    with pytest.raises(RuntimeError):
        with db.write_transaction(conn):
            writer.insert(op(conn), "account_types", {"name": "Gone", "class_id": 1, "stale_after_days": 5})
            raise RuntimeError("something after the write failed")
    assert conn.execute("SELECT COUNT(*) FROM account_types WHERE name = 'Gone'").fetchone()[0] == 0


# -- the application's own tables --

def test_sys_delete_applies_every_condition(conn):
    for token, user in (("a", 1), ("b", 1), ("c", 2)):
        conn.execute("INSERT INTO users (email, display_name, password_hash, created_by, updated_by) VALUES (?, 'U', 'x', (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1))", (f"{token}@example.com",))
        conn.execute("INSERT INTO sys_sessions (token_hash, user_id, expires_at) VALUES (?, ?, '2026-12-01T00:00:00Z')", (token, user))
    assert writer.sys_delete(conn, "sys_sessions", [("user_id", "=", 1), ("token_hash", "!=", "a")]) == 1
    assert [row[0] for row in conn.execute("SELECT token_hash FROM sys_sessions ORDER BY token_hash")] == ["a", "c"]
    assert writer.sys_delete(conn, "sys_sessions", [("expires_at", "<=", "2026-12-01T00:00:00Z")]) == 2


def test_sys_insert_returns_the_rowid(conn):
    first = writer.sys_insert(conn, "sys_login_attempts", {"email_hash": "e", "address_hash": None, "attempted_at": "2026-01-01T00:00:00Z"})
    second = writer.sys_insert(conn, "sys_login_attempts", {"email_hash": "e", "address_hash": None, "attempted_at": "2026-01-01T00:00:00Z"})
    assert second == first + 1
    assert writer.sys_delete(conn, "sys_login_attempts", [("email_hash", "=", "e"), ("address_hash", "IS", None)]) == 2


# -- what the writer refuses --

@pytest.mark.parametrize("call", [
    lambda c: writer.insert(op(c), "no_such_table", {"a": 1}),
    lambda c: writer.insert(op(c), "accounts", {"no_such_column": 1}),
    lambda c: writer.insert(op(c), "accounts", {"name) VALUES ('x'); --": 1}),            # SQL text in a column name
    lambda c: writer.insert(op(c), "accounts; DROP TABLE accounts", {"name": "x"}),       # and in a table name
    lambda c: writer.update(op(c), "accounts", 1, {"name": "x", "bogus": 1}),
    lambda c: writer.update(op(c), "accounts", 1, {"name": "x"}, only_if={"bogus": 1}),
    lambda c: writer.delete(op(c), "no_such_table", 1),
    lambda c: writer.insert(op(c), "sys_sessions", {"token_hash": "x", "user_id": 1, "expires_at": "x"}),   # system table, no operation
    lambda c: writer.update(op(c), "sys_login_attempts", 1, {"email_hash": "x"}),
    lambda c: writer.sys_insert(c, "accounts", {"name": "x"}),                            # household table without one
    lambda c: writer.sys_delete(c, "balances", [("id", "=", 1)]),
    lambda c: writer.sys_delete(c, "sys_sessions", []),                                       # never "delete everything" by accident
    lambda c: writer.sys_delete(c, "sys_sessions", [("user_id", "LIKE", 1)]),
    lambda c: writer.sys_delete(c, "sys_sessions", [("user_id = 1 OR 1", "=", 1)]),
])
def test_the_writer_refuses_what_it_does_not_know(conn, call):
    with pytest.raises(ValueError):
        call(conn)
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0


# -- nothing writes around it --

SOURCE = Path(__file__).resolve().parent.parent / "northstar"
WRITES = re.compile(r"\b(INSERT\s+(OR\s+\w+\s+)?INTO|REPLACE\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b", re.I)
# The migration executor records each migration in the ledger, and runs migration files, which are the exception.
EXEMPT = {"writer.py", "db.py"}


def strings_in(source: str):
    """Every string literal in a module except docstrings, which may talk about SQL."""
    tree = ast.parse(source)
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.value


def writes_outside_the_writer(source: str) -> list[str]:
    return [text for text in strings_in(source) if WRITES.search(text)]


def test_the_scan_notices_a_write_and_ignores_a_docstring():
    assert writes_outside_the_writer('conn.execute("UPDATE accounts SET name = ?")')
    assert writes_outside_the_writer('conn.execute("insert into x values (1)" "DELETE FROM x")')
    assert writes_outside_the_writer('sql = f"INSERT OR REPLACE INTO {table} VALUES (1)"')
    assert not writes_outside_the_writer('def f():\n    """Runs UPDATE accounts SET name."""\n    return 1')
    assert not writes_outside_the_writer('conn.execute("SELECT name FROM accounts")')


def test_no_sql_writes_to_any_table_outside_the_writer():
    found = {}
    for file in sorted(SOURCE.rglob("*.py")):
        if file.name in EXEMPT and file.parent == SOURCE:
            continue
        hits = writes_outside_the_writer(file.read_text(encoding="utf-8"))
        if hits:
            found[str(file.relative_to(SOURCE))] = hits
    assert not found, f"These write to the database without going through northstar.writer: {found}"


def test_nothing_runs_a_script_or_a_batch_around_the_writer():
    pattern = re.compile(r"\.(executescript|executemany)\(")
    found = [str(file.relative_to(SOURCE)) for file in sorted(SOURCE.rglob("*.py"))
             if not (file.name in EXEMPT and file.parent == SOURCE) and pattern.search(file.read_text(encoding="utf-8"))]
    assert not found, f"These bypass northstar.writer: {found}"
