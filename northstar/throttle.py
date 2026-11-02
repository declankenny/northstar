"""Sign-in throttling. Plain functions; the only web-shaped input is a request's headers.

Every failed attempt is counted, in a sliding window, against three limits:

  1. one email from one client address: 5 in 15 minutes. This is the everyday limit. An attacker at
     another address only trips their own address, not the owner's.
  2. one email from any address: 30 in an hour. This stops an attack spread over many addresses. It is
     high, because any cap on an account can be used by a persistent attacker to slow its owner's sign-in.
  3. one client address for any email: 20 in 15 minutes. This stops one machine trying many accounts. It
     only applies when the address can be trusted (see client_address).

An attempt takes its slot before the password is checked, in one write transaction, so a slow check
cannot let many simultaneous requests all start before the first failure is recorded. A success deletes
that email's rows for that address. A blocked attempt is not recorded, so a block cannot grow or extend
itself. The limiter never looks at the users table, so unknown emails behave exactly like real ones.
"""

import hashlib
import ipaddress
import logging
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from northstar import db, writer

PAIR_LIMIT, PAIR_WINDOW = 5, timedelta(minutes=15)
ACCOUNT_LIMIT, ACCOUNT_WINDOW = 30, timedelta(hours=1)
ADDRESS_LIMIT, ADDRESS_WINDOW = 20, timedelta(minutes=15)
KEEP = max(PAIR_WINDOW, ACCOUNT_WINDOW, ADDRESS_WINDOW)

# Uvicorn's own logger, so these lines appear in the container log in the server's format.
log = logging.getLogger("uvicorn.error")


def hash_value(kind: str, value: str) -> str:
    """What is stored instead of an email or an address."""
    return hashlib.sha256(f"{kind}:{value}".encode("utf-8")).hexdigest()


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _wait(conn: sqlite3.Connection, where: str, params: tuple, limit: int, window: timedelta,
          now: datetime) -> int | None:
    """Seconds until one more attempt would be allowed under this limit, or None when it already is.

    `where` is built from constants in this module, never from what a person typed.
    """
    rows = conn.execute(
        f"SELECT attempted_at FROM login_attempts WHERE {where} AND attempted_at > ? "
        "ORDER BY attempted_at, id", (*params, _stamp(now - window))).fetchall()
    if len(rows) < limit:
        return None
    frees_a_slot = _parse(rows[len(rows) - limit]["attempted_at"]) + window
    return max(1, math.ceil((frees_a_slot - now).total_seconds()))


def begin(conn: sqlite3.Connection, email: str, address: str | None, now: datetime) -> tuple[int | None, int | None]:
    """Take a slot for one sign-in attempt. Returns (attempt id, None), or (None, seconds to wait).

    A returned id means the attempt may go ahead and its slot is recorded as a failure until the caller
    clears it after a success. With a wait, nothing was recorded.
    """
    email_hash = hash_value("email", email.strip().lower())
    address_hash = hash_value("address", address) if address else None
    with db.write_transaction(conn):
        writer.sys_delete(conn, "login_attempts", [("attempted_at", "<=", _stamp(now - KEEP))])
        waits = [
            _wait(conn, "email_hash = ? AND address_hash IS ?", (email_hash, address_hash), PAIR_LIMIT, PAIR_WINDOW, now),
            _wait(conn, "email_hash = ?", (email_hash,), ACCOUNT_LIMIT, ACCOUNT_WINDOW, now),
        ]
        if address_hash is not None:
            waits.append(_wait(conn, "address_hash = ?", (address_hash,), ADDRESS_LIMIT, ADDRESS_WINDOW, now))
        blocked = [wait for wait in waits if wait is not None]
        if blocked:
            return None, max(blocked)
        return writer.sys_insert(conn, "login_attempts", {
            "email_hash": email_hash, "address_hash": address_hash, "attempted_at": _stamp(now)}), None


def clear(conn: sqlite3.Connection, email: str, address: str | None) -> None:
    """After a success: forget this email's attempts from this address, and nobody else's."""
    writer.sys_delete(conn, "login_attempts", [
        ("email_hash", "=", hash_value("email", email.strip().lower())),
        ("address_hash", "IS", hash_value("address", address) if address else None)])


def describe(seconds: int) -> str:
    """A wait in whole minutes, rounded up, for the message people read."""
    minutes = max(1, math.ceil(seconds / 60))
    return f"{minutes} minute{'' if minutes == 1 else 's'}"


# -- who is asking --

class Address(NamedTuple):
    value: str | None                 # the client's address when it can be trusted, otherwise None
    behind_untrusted_proxy: bool      # a proxy is in front but is not in uvicorn's trusted list


def _ip(text: str | None) -> str | None:
    try:
        return ipaddress.ip_address((text or "").strip()).compressed
    except ValueError:
        return None


def _forwarded_host(entry: str) -> str:
    """The address in one X-Forwarded-For entry, which may carry a port: 1.2.3.4:80 or [::1]:80."""
    entry = entry.strip()
    if entry.startswith("["):
        end = entry.find("]")
        return entry[1:end] if end != -1 else entry
    if entry.count(":") == 1:
        return entry.rsplit(":", 1)[0]
    return entry


def client_address(client_host: str | None, headers) -> Address:
    """The client's address, if it can be trusted.

    Uvicorn replaces the connecting address with the one from X-Forwarded-For only when the connection
    comes from a proxy listed in FORWARDED_ALLOW_IPS. So when that header is present, the address is
    real exactly when it appears in the header's chain. Otherwise it is the proxy's own address, which
    every visitor would share, and the address limit must not use it: an attacker could then block
    everyone.

    X-Forwarded-For is the only forwarding header uvicorn acts on, so when it is present it alone decides,
    whatever else comes with it. Traefik and nginx send X-Real-IP beside it on every request, and that must
    not make a trusted proxy look untrusted. Forwarded and X-Real-IP matter only when X-Forwarded-For is
    missing: the proxy then speaks in a way uvicorn cannot read, and the address is the proxy's.
    """
    host = _ip(client_host)
    forwarded = ",".join(headers.getlist("x-forwarded-for"))
    if forwarded.strip():
        chain = {_ip(_forwarded_host(entry)) for entry in forwarded.split(",")}
        if host is not None and host in chain:
            return Address(host, False)
        return Address(None, True)
    if headers.get("forwarded") is not None or headers.get("x-real-ip") is not None:
        return Address(None, True)
    return Address(host, False)


_warned = False


def address_of(request) -> str | None:
    """The trusted client address of a request, or None. Warns the operator once if a proxy is not trusted."""
    global _warned
    found = client_address(request.client.host if request.client else None, request.headers)
    if found.behind_untrusted_proxy and not _warned:
        _warned = True
        log.warning(
            "Sign-in requests arrive through a proxy that is not trusted, so the limit on attempts per address "
            "is off. Set FORWARDED_ALLOW_IPS to the proxy's address (a comma-separated list of addresses or "
            "networks) so the real client addresses are used.")
    return found.value


def reset_warning_for_tests() -> None:
    global _warned
    _warned = False


def log_limits() -> None:
    """Say at startup what the limits are, so an operator can see them in the log."""
    log.info(
        "Sign-in limits: %d failed attempts in %d minutes per email and address, %d per hour per email, "
        "and %d in %d minutes per address when the address can be trusted (behind a reverse proxy, set "
        "FORWARDED_ALLOW_IPS).",
        PAIR_LIMIT, PAIR_WINDOW.total_seconds() // 60, ACCOUNT_LIMIT, ADDRESS_LIMIT,
        ADDRESS_WINDOW.total_seconds() // 60)
