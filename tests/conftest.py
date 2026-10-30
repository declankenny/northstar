import pytest
from fastapi.testclient import TestClient

from northstar import db
from northstar.web.app import create_app


@pytest.fixture
def conn(tmp_path):
    """A fresh, migrated database in a temporary folder. Synthetic data only."""
    connection = db.connect(tmp_path / "test.db")
    db.migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "web.db"))


def with_db(client):
    return db.connect(client.app.state.db_path)


def type_id(conn, name):
    return conn.execute("SELECT id FROM account_types WHERE name = ?", (name,)).fetchone()["id"]


def add_account(conn, name, class_id, type_name):
    cur = conn.execute(
        "INSERT INTO accounts (name, class_id, type_id) VALUES (?, ?, ?)",
        (name, class_id, type_id(conn, type_name)),
    )
    return cur.lastrowid


def add_balance(conn, account_id, as_of_date, amount_cents):
    conn.execute(
        "INSERT INTO balances (account_id, as_of_date, amount_cents) VALUES (?, ?, ?)",
        (account_id, as_of_date, amount_cents),
    )
