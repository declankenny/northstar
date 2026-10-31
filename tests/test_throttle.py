"""Sign-in throttling. Synthetic data only, with a fixed clock.

Three limits, each counting failed attempts in a sliding window (see docs/decisions.md):
  1. one email from one address: 5 in 15 minutes,
  2. one email from any address: 30 in an hour,
  3. one address for any email: 20 in 15 minutes, only when the address can be trusted.
"""

import threading
from datetime import datetime, timedelta, timezone

import pytest
from starlette.datastructures import Headers

from northstar import db, throttle

NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
ME = "owner@example.com"
HOME = "203.0.113.5"
ELSEWHERE = "198.51.100.7"


def attempt(conn, email=ME, address=HOME, now=NOW):
    """One sign-in attempt that fails: it takes its slot and the slot is kept."""
    return throttle.begin(conn, email, address, now)


def allowed(result):
    attempt_id, wait = result
    return attempt_id is not None and wait is None


# -- limit 1: one email from one address --

def test_the_sixth_attempt_for_one_email_from_one_address_is_blocked(conn):
    assert all(allowed(attempt(conn)) for _ in range(5))
    attempt_id, wait = attempt(conn)
    assert attempt_id is None and wait == 15 * 60          # until the first attempt leaves the window


def test_the_wait_shrinks_as_time_passes_and_ends_when_the_oldest_attempt_leaves(conn):
    for _ in range(5):
        attempt(conn)
    assert attempt(conn, now=NOW + timedelta(minutes=10))[1] == 5 * 60
    assert allowed(attempt(conn, now=NOW + timedelta(minutes=15, seconds=1)))


def test_the_wait_is_until_enough_old_attempts_expire_not_until_all_do(conn):
    for minute in range(5):                                # attempts at 0, 1, 2, 3, 4 minutes
        attempt(conn, now=NOW + timedelta(minutes=minute))
    _, wait = attempt(conn, now=NOW + timedelta(minutes=5))
    assert wait == 10 * 60                                 # the first leaves at 15, which frees one slot


def test_a_blocked_attempt_is_not_recorded_so_it_cannot_extend_the_block(conn):
    for _ in range(5):
        attempt(conn)
    for _ in range(10):
        assert attempt(conn)[0] is None
    assert conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0] == 5


def test_an_attacker_at_another_address_does_not_block_the_owner_at_home(conn):
    for _ in range(5):
        attempt(conn, address=ELSEWHERE)
    assert attempt(conn, address=ELSEWHERE)[0] is None
    assert allowed(attempt(conn, address=HOME))


def test_the_email_is_matched_ignoring_case_and_surrounding_spaces(conn):
    for _ in range(5):
        attempt(conn, email="Owner@Example.com ")
    assert attempt(conn, email="  owner@example.COM")[0] is None


def test_an_unknown_email_is_throttled_exactly_like_a_real_one(conn):
    """The limiter never looks at the users table, so the response cannot reveal who exists."""
    real = [attempt(conn, email=ME)[0] is not None for _ in range(7)]
    unknown = [attempt(conn, email="nobody@example.com")[0] is not None for _ in range(7)]
    assert real == unknown == [True] * 5 + [False] * 2


# -- limit 2: one email from any address --

def test_thirty_attempts_on_one_email_from_many_addresses_block_a_new_address(conn):
    for index in range(6):                                 # six addresses, five attempts each
        for _ in range(5):
            assert allowed(attempt(conn, address=f"198.51.100.{index + 10}"))
    attempt_id, wait = attempt(conn, address="198.51.100.99")
    assert attempt_id is None and wait == 60 * 60


def test_the_account_limit_has_an_hour_window(conn):
    for index in range(6):
        for _ in range(5):
            attempt(conn, address=f"198.51.100.{index + 10}")
    assert allowed(attempt(conn, address="198.51.100.99", now=NOW + timedelta(hours=1, seconds=1)))


# -- limit 3: one address for any email --

def test_twenty_attempts_from_one_address_on_different_emails_block_the_next(conn):
    for index in range(20):
        assert allowed(attempt(conn, email=f"user{index}@example.com"))
    attempt_id, wait = attempt(conn, email="another@example.com")
    assert attempt_id is None and wait == 15 * 60


def test_the_address_limit_does_not_apply_when_the_address_is_not_known(conn):
    """Behind a proxy that is not trusted every request would look like one address, so the limit is off."""
    for index in range(40):
        assert allowed(attempt(conn, email=f"user{index}@example.com", address=None))


def test_an_unknown_address_shares_one_bucket_per_email(conn):
    for _ in range(5):
        attempt(conn, address=None)
    assert attempt(conn, address=None)[0] is None
    assert allowed(attempt(conn, address=HOME))            # a known address is a different bucket


# -- success --

def test_a_successful_sign_in_clears_that_emails_failures_from_that_address_only(conn):
    for _ in range(4):
        attempt(conn)
    for _ in range(4):
        attempt(conn, address=ELSEWHERE)
    attempt_id, _ = attempt(conn)                          # the attempt that is about to succeed
    throttle.clear(conn, ME, HOME)
    assert conn.execute("SELECT COUNT(*) FROM login_attempts WHERE address_hash = ?",
                        (throttle.hash_value("address", HOME),)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM login_attempts WHERE address_hash = ?",
                        (throttle.hash_value("address", ELSEWHERE),)).fetchone()[0] == 4
    assert all(allowed(attempt(conn)) for _ in range(5))   # a fresh allowance at home
    assert attempt(conn)[0] is None


def test_clearing_does_not_touch_other_emails_from_the_same_address(conn):
    for _ in range(3):
        attempt(conn, email="victim@example.com")
    throttle.clear(conn, ME, HOME)
    assert conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0] == 3


# -- what is stored --

def test_only_hashes_are_stored_never_the_email_or_the_address(conn):
    attempt(conn, email="secret-typed-text@example.com", address=HOME)
    row = conn.execute("SELECT * FROM login_attempts").fetchone()
    stored = " ".join(str(value) for value in tuple(row))
    assert "secret-typed-text" not in stored and HOME not in stored
    assert len(row["email_hash"]) == 64 and len(row["address_hash"]) == 64
    assert row["attempted_at"] == "2026-10-31T12:00:00Z"


def test_an_attempt_with_no_known_address_stores_no_address(conn):
    attempt(conn, address=None)
    assert conn.execute("SELECT address_hash FROM login_attempts").fetchone()[0] is None


def test_rows_older_than_the_longest_window_are_removed(conn):
    attempt(conn, now=NOW)
    attempt(conn, email="other@example.com", now=NOW + timedelta(hours=1, minutes=1))
    assert conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0] == 1


# -- many requests at once --

def test_simultaneous_attempts_cannot_all_slip_past_the_limit(conn):
    """A slow password check must not let many requests start before any failure is recorded: each attempt
    takes its slot before the password is checked, in one write transaction."""
    path = conn.execute("PRAGMA database_list").fetchone()["file"]
    results = []
    start = threading.Barrier(30)

    def worker():
        own = db.connect(path)
        try:
            start.wait()
            results.append(throttle.begin(own, ME, HOME, NOW))
        finally:
            own.close()

    threads = [threading.Thread(target=worker) for _ in range(30)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert len(results) == 30
    assert sum(1 for attempt_id, _ in results if attempt_id is not None) == 5


# -- the client address --

def headers(**values):
    return Headers({name.replace("_", "-"): value for name, value in values.items()})


def test_a_direct_connection_uses_the_connecting_address():
    assert throttle.client_address(HOME, headers()) == (HOME, False)


def test_a_trusted_proxy_is_recognised_because_the_address_is_in_the_forwarded_chain():
    """Uvicorn replaces the connecting address with the one from X-Forwarded-For only for a trusted proxy."""
    assert throttle.client_address(ELSEWHERE, headers(x_forwarded_for=f"{ELSEWHERE}")) == (ELSEWHERE, False)
    assert throttle.client_address(ELSEWHERE, headers(x_forwarded_for=f"10.0.0.9, {ELSEWHERE}")) == (ELSEWHERE, False)
    assert throttle.client_address(ELSEWHERE, headers(x_forwarded_for=f"{ELSEWHERE}:52311")) == (ELSEWHERE, False)


def test_a_proxy_that_is_not_trusted_leaves_the_address_unknown_and_is_flagged():
    """The connecting address is the proxy's, not in the chain it forwarded."""
    assert throttle.client_address("172.18.0.2", headers(x_forwarded_for=ELSEWHERE)) == (None, True)


@pytest.mark.parametrize("name", ["forwarded", "x_real_ip"])
def test_headers_uvicorn_does_not_interpret_also_mean_an_untrusted_proxy(name):
    assert throttle.client_address(HOME, headers(**{name: "for=198.51.100.7"})) == (None, True)


# What Traefik sends with every request it forwards: X-Real-Ip as well as X-Forwarded-For, and others.
TRAEFIK = dict(x_forwarded_host="northstar.example.com", x_forwarded_port="443", x_forwarded_proto="https",
               x_forwarded_server="proxy")


def test_x_real_ip_next_to_x_forwarded_for_does_not_hide_a_trusted_proxy():
    """Uvicorn acts only on X-Forwarded-For. X-Real-Ip beside it, as Traefik and nginx send it, changes nothing."""
    sent = headers(x_forwarded_for=ELSEWHERE, x_real_ip=ELSEWHERE, **TRAEFIK)
    assert throttle.client_address(ELSEWHERE, sent) == (ELSEWHERE, False)


def test_the_forwarded_header_next_to_x_forwarded_for_does_not_hide_a_trusted_proxy_either():
    sent = headers(x_forwarded_for=ELSEWHERE, forwarded=f"for={ELSEWHERE}", x_real_ip=ELSEWHERE)
    assert throttle.client_address(ELSEWHERE, sent) == (ELSEWHERE, False)


def test_an_untrusted_proxy_is_still_flagged_when_it_also_sends_x_real_ip():
    """The connecting address is the proxy's and is not in the chain, whatever else arrives with it."""
    sent = headers(x_forwarded_for=ELSEWHERE, x_real_ip=ELSEWHERE, **TRAEFIK)
    assert throttle.client_address("172.18.0.2", sent) == (None, True)


def test_a_made_up_chain_with_x_real_ip_does_not_get_a_trusted_address():
    """Someone connecting directly who claims to be another address: it is not in the chain, so it is unknown."""
    sent = headers(x_forwarded_for="192.0.2.1", x_real_ip="192.0.2.1")
    assert throttle.client_address(ELSEWHERE, sent) == (None, True)


def test_x_real_ip_alone_still_means_a_proxy_that_uvicorn_cannot_read():
    assert throttle.client_address("172.18.0.2", headers(x_real_ip=ELSEWHERE, **TRAEFIK)) == (None, True)


def test_an_address_that_is_not_an_ip_is_unknown_without_a_proxy_flag():
    assert throttle.client_address("testclient", headers()) == (None, False)
    assert throttle.client_address(None, headers()) == (None, False)


def test_addresses_are_normalised():
    assert throttle.client_address("2001:0db8:0000:0000:0000:0000:0000:0001", headers()) == ("2001:db8::1", False)
    chain = headers(x_forwarded_for="[2001:db8::1]:443")
    assert throttle.client_address("2001:db8::1", chain) == ("2001:db8::1", False)


# -- the message --

@pytest.mark.parametrize("seconds, text", [(1, "1 minute"), (60, "1 minute"), (61, "2 minutes"), (900, "15 minutes"), (3600, "60 minutes")])
def test_the_wait_is_described_in_whole_minutes_rounded_up(seconds, text):
    assert throttle.describe(seconds) == text
