"""Two requests at the same moment. Synthetic data only.

Each test forces a particular interleaving: one request pauses between checking a rule and writing, and
a second request, on its own connection in its own thread, tries to act in that gap. The invariants must
hold whichever way it goes: a closed account never has a nonzero latest balance, and the household always
has at least one admin. Run against code that checks and writes in separate autocommit statements, these
tests fail.
"""

import threading
import time
from datetime import date

import pytest

from northstar import accounts, balances, db, users
from northstar.errors import ValidationError

from conftest import add_account, add_balance

PASSWORD = "synthetic-pass-123"
TODAY = date(2026, 10, 30)
GAP_SECONDS = 0.4      # how long the paused request waits for the other one to try


class Paused:
    """A connection that, right after the first statement containing `needle`, runs `hook` once.

    The hook starts the second request and gives it time to try. Everything else passes straight through.
    """

    def __init__(self, conn, needle, hook):
        self._conn, self._needle, self._hook, self._fired = conn, needle, hook, False

    def execute(self, sql, *args, **kwargs):
        result = self._conn.execute(sql, *args, **kwargs)
        if not self._fired and self._needle in sql:
            self._fired = True
            self._hook()
        return result

    def __getattr__(self, name):
        return getattr(self._conn, name)


class Other:
    """A second request: it runs `work(conn)` on a fresh connection in its own thread."""

    def __init__(self, path, work):
        self.error = None
        self.done = threading.Event()

        def target():
            other = db.connect(path)
            try:
                work(other)
            except ValidationError as err:
                self.error = err                       # a refusal is a valid outcome
            finally:
                other.close()
                self.done.set()

        self.thread = threading.Thread(target=target)

    def start_and_wait_a_moment(self):
        self.thread.start()
        time.sleep(GAP_SECONDS)

    def join(self):
        self.thread.join(timeout=15)
        assert self.done.is_set(), "the second request never finished"


def path_of(conn):
    return conn.execute("PRAGMA database_list").fetchone()["file"]


def closed_account_with_nonzero_balance(conn, account_id):
    row = conn.execute("SELECT is_open FROM accounts WHERE id = ?", (account_id,)).fetchone()
    latest = conn.execute(
        "SELECT amount_cents FROM balances WHERE account_id = ? ORDER BY as_of_date DESC LIMIT 1",
        (account_id,)).fetchone()
    return row["is_open"] == 0 and latest is not None and latest["amount_cents"] != 0


# -- the transaction helper itself --

def test_a_write_transaction_commits_and_a_failure_rolls_everything_back(conn):
    with db.write_transaction(conn):
        add_account(conn, "Kept", 1, "Checking")
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
    with pytest.raises(RuntimeError):
        with db.write_transaction(conn):
            add_account(conn, "Not kept", 1, "Checking")
            raise RuntimeError("something went wrong")
    assert [r["name"] for r in conn.execute("SELECT name FROM accounts")] == ["Kept"]
    assert not conn.in_transaction


def test_a_write_transaction_inside_another_joins_it(conn):
    with pytest.raises(RuntimeError):
        with db.write_transaction(conn):
            with db.write_transaction(conn):
                add_account(conn, "Inner", 1, "Checking")
            assert conn.in_transaction                  # the inner block did not commit on its own
            raise RuntimeError("the outer block fails")
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0


# -- closing an account and changing its balances at the same moment (#3) --

@pytest.fixture
def zero_account(conn):
    """An open account whose latest balance is zero, so it may be closed."""
    account = add_account(conn, "Old card", 2, "Credit card")
    add_balance(conn, account, "2026-10-01", 5000)
    add_balance(conn, account, "2026-10-20", 0)
    return account


def test_a_balance_entered_between_the_close_check_and_the_close_cannot_leave_a_closed_nonzero_account(conn, zero_account):
    path = path_of(conn)
    other = Other(path, lambda c: balances.record_balance(c, zero_account, TODAY, 12345))
    closer = Paused(db.connect(path), "SELECT amount_cents FROM balances", other.start_and_wait_a_moment)
    accounts.close_account(closer, zero_account)
    other.join()
    assert not closed_account_with_nonzero_balance(conn, zero_account)
    # The close won the race, so the balance was refused because the account is closed.
    assert other.error is not None and "closed" in str(other.error)


@pytest.mark.parametrize("change", ["record", "update"])
def test_a_close_between_the_open_check_and_the_balance_write_cannot_leave_a_closed_nonzero_account(conn, zero_account, change):
    path = path_of(conn)
    zero_id = conn.execute("SELECT id FROM balances WHERE account_id = ? AND amount_cents = 0", (zero_account,)).fetchone()["id"]
    other = Other(path, lambda c: accounts.close_account(c, zero_account))
    mine = db.connect(path)
    if change == "record":
        paused = Paused(mine, "SELECT id, amount_cents, note FROM balances WHERE account_id", other.start_and_wait_a_moment)
        balances.record_balance(paused, zero_account, TODAY, 12345)
    else:
        paused = Paused(mine, "SELECT 1 FROM balances WHERE account_id", other.start_and_wait_a_moment)
        balances.update_balance(paused, zero_id, "2026-10-20", "123.45", None, TODAY)
    other.join()
    assert not closed_account_with_nonzero_balance(conn, zero_account)
    # The balance won the race, so the close was refused: the latest balance is not zero.
    assert other.error is not None and "not zero" in str(other.error)


# -- two admins changing each other at the same moment (#5) --

@pytest.fixture
def two_admins(conn):
    first = users.create_user(conn, "first@example.com", "First", PASSWORD, is_admin=True)
    second = users.create_user(conn, "second@example.com", "Second", PASSWORD, is_admin=True)
    return first, second


def admin_count(conn):
    return conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0]


ADMIN_COUNT = "SELECT COUNT(*) FROM users WHERE is_admin = 1"


def test_two_admins_demoting_each_other_at_the_same_moment_cannot_leave_no_admin(conn, two_admins):
    first, second = two_admins
    path = path_of(conn)
    other = Other(path, lambda c: users.update_user(c, first, second, is_admin=False))
    paused = Paused(db.connect(path), ADMIN_COUNT, other.start_and_wait_a_moment)
    users.update_user(paused, second, first, is_admin=False)
    other.join()
    assert admin_count(conn) >= 1
    assert other.error is not None and "at least one admin" in str(other.error)


def test_two_admins_deleting_each_other_at_the_same_moment_cannot_leave_no_admin(conn, two_admins):
    first, second = two_admins
    path = path_of(conn)
    other = Other(path, lambda c: users.delete_user(c, first, second))
    paused = Paused(db.connect(path), ADMIN_COUNT, other.start_and_wait_a_moment)
    users.delete_user(paused, second, first)
    other.join()
    assert admin_count(conn) >= 1
    assert other.error is not None and "at least one admin" in str(other.error)
