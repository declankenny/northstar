"""Login sessions kept in the database. Plain functions, no web code.

The browser holds a random token in a cookie. The database holds only its SHA-256. A session records how it was started:
`local` (a password, 30 days) or `oidc` (the identity provider, for the lifetime the caller gives, and with a fingerprint
of the provider configuration it was made under, so a session outlives neither a change of provider nor turning OIDC off).
Neither kind is extended by use.
"""

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from northstar import writer

SESSION_DAYS = 30
_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _stamp(moment: datetime) -> str:
    return moment.strftime(_FORMAT)


def _now() -> datetime:
    return datetime.now(timezone.utc)


LOCAL = "local"
OIDC = "oidc"


def create_session(conn: sqlite3.Connection, user_id: int, now: datetime | None = None, *,
                   method: str = LOCAL, fingerprint: str | None = None, lifetime: timedelta | None = None) -> str:
    """Start a session and return its token, which is shown to the browser once. A local session lasts SESSION_DAYS. An OIDC
    session must say how long it lasts and which provider configuration it was made under."""
    if method == OIDC:
        if fingerprint is None or lifetime is None:
            raise ValueError("An OIDC session needs a lifetime and a configuration fingerprint.")
    elif method != LOCAL or fingerprint is not None:
        raise ValueError("A local session has no fingerprint.")
    now = now or _now()
    writer.sys_delete(conn, "sys_sessions", [("expires_at", "<=", _stamp(now))])
    token = secrets.token_urlsafe(32)
    writer.sys_insert(conn, "sys_sessions", {
        "token_hash": _hash(token), "user_id": user_id, "created_at": _stamp(now),
        "expires_at": _stamp(now + (lifetime if lifetime is not None else timedelta(days=SESSION_DAYS))),
        "auth_method": method, "config_fingerprint": fingerprint})
    return token


def user_for_token(conn: sqlite3.Connection, token: str | None, now: datetime | None = None) -> sqlite3.Row | None:
    """The signed-in user for a token, or None if it is unknown or expired. The row also says how the session was started
    (`auth_method`) and its `config_fingerprint`, which is None for a local session."""
    if not token:
        return None
    return conn.execute(
        "SELECT u.id, u.email, u.display_name, u.is_admin, s.auth_method, s.config_fingerprint FROM sys_sessions s "
        "JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ? AND u.deleted = 0",
        (_hash(token), _stamp(now or _now())),
    ).fetchone()


def end_session(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        writer.sys_delete(conn, "sys_sessions", [("token_hash", "=", _hash(token))])


def end_sessions(conn: sqlite3.Connection, user_id: int, except_token: str | None = None) -> None:
    """Sign a user out everywhere, optionally keeping the browser that holds except_token."""
    if except_token:
        writer.sys_delete(conn, "sys_sessions", [("user_id", "=", user_id), ("token_hash", "!=", _hash(except_token))])
    else:
        writer.sys_delete(conn, "sys_sessions", [("user_id", "=", user_id)])
