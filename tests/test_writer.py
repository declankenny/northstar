"""The write chokepoint: every write the application makes goes through northstar.writer. Synthetic data only."""

import ast
import re
import sqlite3
from pathlib import Path

import pytest

from northstar import db, writer
from northstar.writer import NOW, Operation

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
    assert writer.update(op(conn), "balances", balance, {"amount_cents": 10000, "updated_at": NOW}) is False
    assert balance_row(conn)["updated_at"] == "2020-01-01T00:00:00Z"        # NOW alone is not a change


def test_now_is_applied_together_with_a_real_change(conn, balance):
    assert writer.update(op(conn), "balances", balance, {"amount_cents": 1, "updated_at": NOW}) is True
    row = balance_row(conn)
    assert row["updated_at"] > "2020-01-01T00:00:00Z" and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", row["updated_at"])


def test_update_of_a_missing_row_changes_nothing(conn):
    assert writer.update(op(conn), "balances", 999, {"amount_cents": 1}) is False


def test_update_only_if_the_guard_still_holds(conn):
    user = conn.execute("INSERT INTO users (email, display_name, password_hash) VALUES ('a@example.com', 'A', 'old')").lastrowid
    assert writer.update(op(conn), "users", user, {"password_hash": "new"}, only_if={"password_hash": "stale"}) is False
    assert conn.execute("SELECT password_hash FROM users").fetchone()[0] == "old"
    assert writer.update(op(conn), "users", user, {"password_hash": "new"}, only_if={"password_hash": "old"}) is True
    assert conn.execute("SELECT password_hash FROM users").fetchone()[0] == "new"


def test_a_database_rule_still_refuses_a_bad_update(conn):
    types = [row[0] for row in conn.execute("SELECT id FROM account_types ORDER BY id")]
    with pytest.raises(sqlite3.IntegrityError):
        writer.update(op(conn), "account_types", types[0], {"name": "savings"})      # another type's name, ignoring case


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
        conn.execute("INSERT INTO users (email, display_name, password_hash) VALUES (?, 'U', 'x')", (f"{token}@example.com",))
        conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, '2026-12-01T00:00:00Z')", (token, user))
    assert writer.sys_delete(conn, "sessions", [("user_id", "=", 1), ("token_hash", "!=", "a")]) == 1
    assert [row[0] for row in conn.execute("SELECT token_hash FROM sessions ORDER BY token_hash")] == ["a", "c"]
    assert writer.sys_delete(conn, "sessions", [("expires_at", "<=", "2026-12-01T00:00:00Z")]) == 2


def test_sys_insert_returns_the_rowid(conn):
    first = writer.sys_insert(conn, "login_attempts", {"email_hash": "e", "address_hash": None, "attempted_at": "2026-01-01T00:00:00Z"})
    second = writer.sys_insert(conn, "login_attempts", {"email_hash": "e", "address_hash": None, "attempted_at": "2026-01-01T00:00:00Z"})
    assert second == first + 1
    assert writer.sys_delete(conn, "login_attempts", [("email_hash", "=", "e"), ("address_hash", "IS", None)]) == 2


# -- what the writer refuses --

@pytest.mark.parametrize("call", [
    lambda c: writer.insert(op(c), "no_such_table", {"a": 1}),
    lambda c: writer.insert(op(c), "accounts", {"no_such_column": 1}),
    lambda c: writer.insert(op(c), "accounts", {"name) VALUES ('x'); --": 1}),            # SQL text in a column name
    lambda c: writer.insert(op(c), "accounts; DROP TABLE accounts", {"name": "x"}),       # and in a table name
    lambda c: writer.update(op(c), "accounts", 1, {"name": "x", "bogus": 1}),
    lambda c: writer.update(op(c), "accounts", 1, {"name": "x"}, only_if={"bogus": 1}),
    lambda c: writer.delete(op(c), "no_such_table", 1),
    lambda c: writer.insert(op(c), "sessions", {"token_hash": "x", "user_id": 1, "expires_at": "x"}),   # system table, no operation
    lambda c: writer.update(op(c), "login_attempts", 1, {"email_hash": "x"}),
    lambda c: writer.sys_insert(c, "accounts", {"name": "x"}),                            # household table without one
    lambda c: writer.sys_delete(c, "balances", [("id", "=", 1)]),
    lambda c: writer.sys_delete(c, "sessions", []),                                       # never "delete everything" by accident
    lambda c: writer.sys_delete(c, "sessions", [("user_id", "LIKE", 1)]),
    lambda c: writer.sys_delete(c, "sessions", [("user_id = 1 OR 1", "=", 1)]),
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
