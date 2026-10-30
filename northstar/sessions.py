"""Login sessions kept in the database. Plain functions, no web code.

The browser holds a random token in a cookie. The database holds only its SHA-256.
"""

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

SESSION_DAYS = 30
_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _stamp(moment: datetime) -> str:
    return moment.strftime(_FORMAT)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_session(conn: sqlite3.Connection, user_id: int, now: datetime | None = None) -> str:
    """Start a session and return its token, which is shown to the browser once."""
    now = now or _now()
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (_stamp(now),))
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (_hash(token), user_id, _stamp(now), _stamp(now + timedelta(days=SESSION_DAYS))),
    )
    return token


def user_for_token(conn: sqlite3.Connection, token: str | None, now: datetime | None = None) -> sqlite3.Row | None:
    """The signed-in user for a token, or None if it is unknown or expired."""
    if not token:
        return None
    return conn.execute(
        "SELECT u.id, u.email, u.display_name, u.is_admin FROM sessions s "
        "JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?",
        (_hash(token), _stamp(now or _now())),
    ).fetchone()


def end_session(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))


def end_sessions(conn: sqlite3.Connection, user_id: int, except_token: str | None = None) -> None:
    """Sign a user out everywhere, optionally keeping the browser that holds except_token."""
    if except_token:
        conn.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user_id, _hash(except_token)))
    else:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
