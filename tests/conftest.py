import pytest
from fastapi.testclient import TestClient

from northstar import clock, db, sessions, users
from northstar.writer import Operation
from northstar.web.app import create_app


def op(conn, actor_id=None, kind="ui_edit"):
    """A write operation on a connection, for tests that call the application's write functions directly."""
    return Operation(conn, actor_id, kind)


def use_dollars(conn):
    """Set the system currency to US dollars, as an administrator would before the first account. A fresh database has it
    unset, and no account can be created until it is set; most tests are about accounts, so their fixtures set it."""
    conn.execute("UPDATE system_properties SET value = 'USD', read_only = 1 WHERE name = 'system.currency'")
    conn.execute("UPDATE currencies SET is_enabled = 1 WHERE code = 'USD'")      # saving the system currency enables it


@pytest.fixture
def conn(tmp_path):
    """A fresh, migrated database in a temporary folder, with the system currency set to US dollars. Synthetic data only."""
    connection = db.connect(tmp_path / "test.db")
    db.migrate(connection)
    use_dollars(connection)
    yield connection
    connection.close()


@pytest.fixture
def anon_client(tmp_path):
    """A client that is not signed in."""
    return TestClient(create_app(tmp_path / "web.db"), follow_redirects=False)


def sign_in(test_client, email="test@example.com", name="Test User", is_admin=True):
    """Create a synthetic user (an admin unless said otherwise) and sign the client in as them."""
    with db.connect(test_client.app.state.db_path) as connection:
        use_dollars(connection)
        user_id = users.create_user(op(connection), email, name, "test-password-123", is_admin=is_admin)
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
    """Insert an account straight into the table. The class is the type's, so `class_id` is only checked: a test that names a
    type from the other class has set up something that cannot exist."""
    assert conn.execute("SELECT class_id FROM account_types WHERE name = ?", (type_name,)).fetchone()["class_id"] == class_id
    cur = conn.execute(
        "INSERT INTO accounts (name, type_id, currency_id, created_by, updated_by) VALUES (?, ?, (SELECT id FROM currencies WHERE code = 'USD'), (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1))",
        (name, type_id(conn, type_name)),
    )
    return cur.lastrowid


def balances_of(client, account_id):
    """An account's live balances as the database holds them, newest date first, with the version a change must send back."""
    with with_db(client) as conn:
        return [dict(row) for row in conn.execute(
            "SELECT id, as_of_date, amount_cents, note, version FROM live_balances WHERE account_id = ? ORDER BY as_of_date DESC",
            (account_id,))]


def add_balance(conn, account_id, as_of_date, amount_cents):
    conn.execute(
        "INSERT INTO balances (account_id, as_of_date, amount_cents, created_by, updated_by) VALUES (?, ?, ?, (SELECT id FROM users WHERE is_system = 1), (SELECT id FROM users WHERE is_system = 1))",
        (account_id, as_of_date, amount_cents),
    )


@pytest.fixture(autouse=True)
def cheap_password_hashing(monkeypatch):
    """Production hashing takes half a second and 128 MiB, and the tests hash hundreds of passwords, so they
    use the cheapest valid cost. The tests that are about the cost set what they need (test_password_hashing)."""
    monkeypatch.setattr("northstar.users.SCRYPT", {"n": 2**4, "r": 8, "p": 1})


@pytest.fixture(autouse=True)
def utc_clock_zone(monkeypatch):
    """The clock's zone is process-wide and create_app sets it, so every test starts and ends in UTC, and TZ on the
    machine running the tests never reaches a test's database."""
    monkeypatch.delenv("TZ", raising=False)
    clock.set_zone(None)
    yield
    clock.set_zone(None)


@pytest.fixture(autouse=True)
def no_built_frontend(monkeypatch, tmp_path_factory):
    """Tests must not depend on whether the React bundle happens to be built on this machine.
    A test that wants a bundle sets SPA_DIR itself."""
    monkeypatch.setattr("northstar.web.app.SPA_DIR", tmp_path_factory.mktemp("no-spa") / "missing")


def fake_spa(tmp_path, monkeypatch):
    """A (fake) React build: an index page and one script. Set before the app is created, which is when it looks for the build."""
    spa = tmp_path / "spa"
    (spa / "assets").mkdir(parents=True)
    (spa / "index.html").write_text("<!doctype html><title>Northstar</title>")
    (spa / "assets" / "app.js").write_text("console.log('app')")
    monkeypatch.setattr("northstar.web.app.SPA_DIR", spa)


@pytest.fixture
def anon_spa_client(tmp_path, monkeypatch):
    """A client that is not signed in, for an app that has a React build (so it can serve the sign-in page)."""
    fake_spa(tmp_path, monkeypatch)
    return TestClient(create_app(tmp_path / "web.db"), follow_redirects=False)


def post_sign_in(test_client, email, password, next=None):
    """Sign in the way the sign-in page does: JSON to the sign-in endpoint."""
    body = {"email": email, "password": password}
    if next is not None:
        body["next"] = next
    return test_client.post("/api/auth/login", json=body)
