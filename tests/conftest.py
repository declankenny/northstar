import pytest

from northstar import db


@pytest.fixture
def conn(tmp_path):
    """A fresh, migrated database in a temporary folder. Synthetic data only."""
    connection = db.connect(tmp_path / "test.db")
    db.migrate(connection)
    yield connection
    connection.close()


def type_id(conn, name):
    return conn.execute("SELECT id FROM account_types WHERE name = ?", (name,)).fetchone()["id"]


def add_account(conn, name, class_id, type_name):
    cur = conn.execute(
        "INSERT INTO accounts (name, class_id, type_id) VALUES (?, ?, ?)",
        (name, class_id, type_id(conn, type_name)),
    )
    return cur.lastrowid
