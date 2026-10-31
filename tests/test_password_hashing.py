"""Password hashing: the cost, the self-describing format, upgrade on sign-in, and the safety limits.

The suite normally runs with a minimal scrypt cost (see conftest), so each test here sets the cost it
needs. Synthetic passwords only.
"""

import base64
import hashlib
import threading
import time

import pytest

from northstar import users

PASSWORD = "synthetic-pass-123"


def hash_with(password, n, r, p):
    """A stored hash made with a particular cost, as an older or newer version of the app would have made it."""
    salt = b"0123456789abcdef"
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=2**28)
    b64 = lambda raw: base64.b64encode(raw).decode()
    return f"scrypt${n}${r}${p}${b64(salt)}${b64(digest)}"


# -- the cost --

def test_the_production_cost_is_owasps_first_listed_scrypt_setting():
    """N=2^17, r=8, p=1 (128 MiB). It costs about as much time as N=2^16 with p=2 and makes an attacker pay
    twice the memory, which is the point of scrypt."""
    assert users.PRODUCTION_SCRYPT == {"n": 2**17, "r": 8, "p": 1}
    assert 128 * users.PRODUCTION_SCRYPT["n"] * users.PRODUCTION_SCRYPT["r"] == 128 * 2**20


def test_a_hash_at_the_production_cost_verifies_and_describes_itself(monkeypatch):
    monkeypatch.setattr(users, "SCRYPT", dict(users.PRODUCTION_SCRYPT))
    stored = users.hash_password(PASSWORD)
    assert stored.startswith("scrypt$131072$8$1$")
    assert users.verify_password(PASSWORD, stored)
    assert not users.verify_password("a different password", stored)


def test_a_new_hash_carries_the_current_cost_and_a_random_salt():
    one, two = users.hash_password(PASSWORD), users.hash_password(PASSWORD)
    n, r, p = users.SCRYPT["n"], users.SCRYPT["r"], users.SCRYPT["p"]
    assert one.startswith(f"scrypt${n}${r}${p}$") and one != two


# -- old hashes still work, and are upgraded --

def test_a_hash_made_with_a_different_cost_still_verifies():
    for cost in [(2**4, 8, 1), (2**10, 8, 1), (2**12, 4, 2)]:
        assert users.verify_password(PASSWORD, hash_with(PASSWORD, *cost))


@pytest.mark.parametrize("stored_cost, wanted", [
    ((2**3, 8, 1), True),       # lower n
    ((2**4, 4, 1), True),       # lower r
    ((2**4, 8, 1), False),      # the same as the current cost
    ((2**6, 8, 1), False),      # stronger than the current cost: never downgraded
    ((2**4, 8, 2), False),      # a higher p is stronger
])
def test_needs_rehash_is_true_only_for_a_weaker_hash(stored_cost, wanted):
    assert users.needs_rehash(hash_with(PASSWORD, *stored_cost)) is wanted


def test_garbage_does_not_need_rehashing_it_just_does_not_verify():
    assert users.needs_rehash("garbage") is False and not users.verify_password(PASSWORD, "garbage")


def test_signing_in_with_a_weaker_hash_upgrades_it(conn):
    users.create_user(conn, "a@example.com", "A", PASSWORD)
    old = hash_with(PASSWORD, 2**3, 8, 1)
    conn.execute("UPDATE users SET password_hash = ? WHERE email = 'a@example.com'", (old,))
    assert users.authenticate(conn, "a@example.com", PASSWORD) is not None
    now = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    assert now != old and now.startswith(f"scrypt${users.SCRYPT['n']}$")
    assert users.authenticate(conn, "a@example.com", PASSWORD) is not None       # and still works


def test_a_failed_sign_in_does_not_change_the_stored_hash(conn):
    users.create_user(conn, "a@example.com", "A", PASSWORD)
    old = hash_with(PASSWORD, 2**3, 8, 1)
    conn.execute("UPDATE users SET password_hash = ?", (old,))
    assert users.authenticate(conn, "a@example.com", "wrong-password-123") is None
    assert conn.execute("SELECT password_hash FROM users").fetchone()[0] == old


def test_a_stronger_hash_is_never_downgraded_by_signing_in(conn):
    users.create_user(conn, "a@example.com", "A", PASSWORD)
    strong = hash_with(PASSWORD, 2**6, 8, 1)
    conn.execute("UPDATE users SET password_hash = ?", (strong,))
    users.authenticate(conn, "a@example.com", PASSWORD)
    assert conn.execute("SELECT password_hash FROM users").fetchone()[0] == strong


def test_an_unknown_email_still_costs_a_full_hash(conn, monkeypatch):
    """So a miss takes about as long as a wrong password."""
    calls = []
    real = users.verify_password
    monkeypatch.setattr(users, "verify_password", lambda password, stored: calls.append(stored) or real(password, stored))
    assert users.authenticate(conn, "nobody@example.com", PASSWORD) is None
    assert len(calls) == 1 and calls[0].startswith(f"scrypt${users.SCRYPT['n']}${users.SCRYPT['r']}${users.SCRYPT['p']}$")


# -- a tampered or corrupt stored hash cannot be used to exhaust memory --

@pytest.mark.parametrize("n, r, p", [
    (2**30, 8, 1),              # far too much memory
    (2**20, 64, 1),             # too much memory through r
    (2**17, 8, 5000),           # absurd p
    (12345, 8, 1),              # not a power of two
    (1, 8, 1), (0, 8, 1),       # too small to be scrypt at all
    (2**4, 0, 1), (2**4, 8, 0), # zero
    (-16, 8, 1),
])
def test_a_stored_hash_with_unreasonable_parameters_is_refused_without_computing_it(n, r, p, monkeypatch):
    called = []
    monkeypatch.setattr(hashlib, "scrypt", lambda *a, **k: called.append(1) or b"")
    stored = f"scrypt${n}${r}${p}$AAAA$AAAA"
    assert users.verify_password(PASSWORD, stored) is False
    assert not called


@pytest.mark.parametrize("stored", ["", "scrypt", "scrypt$1$2$3", "bcrypt$16$8$1$AAAA$AAAA", "scrypt$x$8$1$AAAA$AAAA",
                                    "scrypt$16$8$1$!!!$AAAA", "scrypt$16$8$1$AAAA$AAAA$extra"])
def test_malformed_stored_hashes_do_not_verify_and_do_not_crash(stored):
    assert users.verify_password(PASSWORD, stored) is False
    assert users.needs_rehash(stored) is False


# -- how many hashes run at once --

def test_at_most_two_hashes_are_computed_at_the_same_time(monkeypatch):
    """Each hash can take 128 MiB, so many sign-ins at once must queue instead of exhausting memory."""
    running, peak, lock = [0], [0], threading.Lock()

    def slow_scrypt(*args, **kwargs):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.05)
        with lock:
            running[0] -= 1
        return b"x" * 64

    monkeypatch.setattr(hashlib, "scrypt", slow_scrypt)
    stored = "scrypt$16$8$1$AAAA$AAAA"
    threads = [threading.Thread(target=lambda: users.verify_password(PASSWORD, stored)) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert peak[0] == 2


def test_the_unknown_email_hash_is_built_when_the_app_starts_not_on_the_first_miss(tmp_path, monkeypatch):
    """Otherwise the first unknown email would take twice as long as any other and give itself away."""
    from northstar.web.app import create_app
    monkeypatch.setattr(users, "_dummy_hashes", {})
    create_app(tmp_path / "web.db")
    assert users._dummy_hashes, "the dummy hash was not prepared at startup"
    built = dict(users._dummy_hashes)

    from northstar import db
    conn = db.connect(tmp_path / "web.db")
    assert users.authenticate(conn, "nobody@example.com", PASSWORD) is None
    assert users._dummy_hashes == built                      # the first miss did not build anything
    conn.close()
