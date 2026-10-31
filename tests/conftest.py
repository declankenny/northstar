import pytest
from fastapi.testclient import TestClient

from northstar import db, sessions, users
from northstar.web.app import create_app


@pytest.fixture
def conn(tmp_path):
    """A fresh, migrated database in a temporary folder. Synthetic data only."""
    connection = db.connect(tmp_path / "test.db")
    db.migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def anon_client(tmp_path):
    """A client that is not signed in."""
    return TestClient(create_app(tmp_path / "web.db"), follow_redirects=False)


def sign_in(test_client, email="test@example.com", name="Test User", is_admin=True):
    """Create a synthetic user (an admin unless said otherwise) and sign the client in as them."""
    with db.connect(test_client.app.state.db_path) as connection:
        user_id = users.create_user(connection, email, name, "test-password-123", is_admin=is_admin)
        test_client.cookies.set("northstar_session", sessions.create_session(connection, user_id))
    return test_client


@pytest.fixture
def client(tmp_path):
    """A client signed in as a synthetic admin, so existing page tests need no login step."""
    return sign_in(TestClient(create_app(tmp_path / "web.db")))


@pytest.fixture
def member_client(tmp_path):
    """A client signed in as an ordinary user who is not an admin."""
    return sign_in(TestClient(create_app(tmp_path / "web.db")), "member@example.com", "Member", is_admin=False)


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


@pytest.fixture(autouse=True)
def no_built_frontend(monkeypatch, tmp_path_factory):
    """Tests must not depend on whether the React bundle happens to be built on this machine.
    A test that wants a bundle sets SPA_DIR itself."""
    monkeypatch.setattr("northstar.web.app.SPA_DIR", tmp_path_factory.mktemp("no-spa") / "missing")
