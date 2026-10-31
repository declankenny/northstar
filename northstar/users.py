"""Local user accounts. Plain functions plus a small command line.

    python -m northstar.users create EMAIL NAME [--admin]
    python -m northstar.users set-password EMAIL
    python -m northstar.users list

Passwords are asked for at a prompt, never taken from the command line, so they stay out of shell
history. Nothing here prints a password or a hash.
"""

import argparse
import base64
import getpass
import hashlib
import hmac
import secrets
import sqlite3
import sys
import threading
from contextlib import closing

from northstar import config, db, sessions
from northstar.errors import ValidationError

MIN_PASSWORD_LENGTH = 12
MAX_NAME_LENGTH = 100
THEMES = ("light", "dark")
# The cost of one hash: OWASP's first-listed scrypt setting, N=2^17 (128 MiB of memory), r=8, p=1. It takes
# about as long as N=2^16 with p=2 and makes an attacker pay twice the memory. See docs/decisions.md.
PRODUCTION_SCRYPT = {"n": 2**17, "r": 8, "p": 1}
SCRYPT = dict(PRODUCTION_SCRYPT)    # what new hashes use. The tests lower it (tests/conftest.py).

# A stored hash is read with the cost it carries, so a corrupt or tampered row must not be able to ask for
# unbounded memory or time.
_MAX_N, _MAX_R, _MAX_P, _MAX_MEMORY = 2**20, 32, 16, 2**29

# One hash can need 128 MiB, so at most two run at once and the rest wait their turn. Without this, many
# simultaneous sign-in attempts could use all the memory of a small machine.
_HASH_SLOTS = threading.BoundedSemaphore(2)


def _acceptable_cost(n: int, r: int, p: int) -> bool:
    return (2 <= n <= _MAX_N and n & (n - 1) == 0 and 1 <= r <= _MAX_R and 1 <= p <= _MAX_P
            and 128 * n * r <= _MAX_MEMORY)


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    with _HASH_SLOTS:
        return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p,
                              maxmem=128 * n * r + 128 * r * p + 2**22)


def hash_password(password: str) -> str:
    """scrypt (in Python's standard library) with a random salt, in a self-describing string that carries
    its own cost, so the cost can be raised later while old hashes still verify."""
    salt = secrets.token_bytes(16)
    n, r, p = SCRYPT["n"], SCRYPT["r"], SCRYPT["p"]
    digest = _scrypt(password, salt, n, r, p)
    b64 = lambda raw: base64.b64encode(raw).decode()
    return f"scrypt${n}${r}${p}${b64(salt)}${b64(digest)}"


def _parse(stored: str):
    """(n, r, p, salt, digest) of a stored hash, or None when it is not a well-formed scrypt hash."""
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return None
    try:
        return int(parts[1]), int(parts[2]), int(parts[3]), base64.b64decode(parts[4], validate=True), base64.b64decode(parts[5], validate=True)
    except ValueError:
        return None


def verify_password(password: str, stored: str) -> bool:
    parsed = _parse(stored)
    if parsed is None or not _acceptable_cost(*parsed[:3]):
        return False
    n, r, p, salt, digest = parsed
    try:
        actual = _scrypt(password, salt, n, r, p)
    except ValueError:
        return False
    return hmac.compare_digest(actual, digest)


def needs_rehash(stored: str) -> bool:
    """True when the stored hash was made with a lower cost than the current one. A stronger hash is left
    alone, and anything that is not a well-formed hash is not this function's business: it just fails to verify."""
    parsed = _parse(stored)
    if parsed is None or not _acceptable_cost(*parsed[:3]):
        return False
    n, r, p = parsed[:3]
    return n < SCRYPT["n"] or r < SCRYPT["r"] or p < SCRYPT["p"]


# Checked when the email is unknown, so a miss takes as long as a wrong password. The app builds it at startup
# (prepare_dummy_hash): building it on the first miss would make that one miss take twice as long, which
# tells a patient visitor that the email is unknown. It is built again if the cost changes.
_dummy_hashes: dict[tuple, str] = {}


def prepare_dummy_hash() -> None:
    """Build the hash used for unknown emails now, so the first unknown email costs the same as any other."""
    _dummy_hash()


def _dummy_hash() -> str:
    key = (SCRYPT["n"], SCRYPT["r"], SCRYPT["p"])
    if key not in _dummy_hashes:
        _dummy_hashes[key] = hash_password("not-a-real-password")
    return _dummy_hashes[key]


def _clean_email(email: str) -> str:
    email = email.strip().lower()
    if not email or " " in email or email.count("@") != 1 or email.startswith("@") or email.endswith("@"):
        raise ValidationError("Enter a valid email address.")
    return email


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"The password must be at least {MIN_PASSWORD_LENGTH} characters.")


def create_user(conn: sqlite3.Connection, email: str, display_name: str, password: str,
                is_admin: bool = False) -> int:
    email = _clean_email(email)
    display_name = display_name.strip()
    if not display_name:
        raise ValidationError("Enter a name.")
    _check_password(password)
    try:
        cur = conn.execute(
            "INSERT INTO users (email, display_name, password_hash, is_admin) VALUES (?, ?, ?, ?)",
            (email, display_name, hash_password(password), 1 if is_admin else 0),
        )
    except sqlite3.IntegrityError:
        raise ValidationError("A user with that email already exists.")
    return cur.lastrowid


def authenticate(conn: sqlite3.Connection, email: str, password: str) -> sqlite3.Row | None:
    """The user if the email and password match, otherwise None. Never says which part was wrong."""
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip(),)).fetchone()
    if row is None:
        verify_password(password, _dummy_hash())
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    if needs_rehash(row["password_hash"]):
        # The password is right and the hash is weaker than today's cost: store a fresh one. The condition
        # on the old value means a password changed in the meantime is not overwritten.
        try:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ? AND password_hash = ?",
                         (hash_password(password), row["id"], row["password_hash"]))
        except sqlite3.Error:
            pass            # signing in matters more than the upgrade, which happens at the next sign-in
    return row


def get_user(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, email, display_name, is_admin, theme FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if row is None:
        raise ValidationError("That user no longer exists.")
    return row


def set_password(conn: sqlite3.Connection, email: str, password: str) -> None:
    """Change a password by email (the command line) and sign that user out everywhere."""
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email.strip(),)).fetchone()
    if row is None:
        raise ValidationError("There is no user with that email.")
    set_user_password(conn, row["id"], password)


def set_user_password(conn: sqlite3.Connection, user_id: int, password: str,
                      keep_token: str | None = None) -> None:
    """Change a password and end the user's sessions, except the one holding keep_token."""
    _check_password(password)
    get_user(conn, user_id)
    with db.write_transaction(conn):
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user_id))
        sessions.end_sessions(conn, user_id, except_token=keep_token)


class WrongPasswordError(ValidationError):
    """The current password typed was not the account's password. Sign-in throttling counts these."""


def change_own_password(conn: sqlite3.Connection, user_id: int, current: str, new: str,
                        keep_token: str | None) -> None:
    """A user changes their own password. Needs the current one. Their other browsers are signed out."""
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or not verify_password(current, row["password_hash"]):
        raise WrongPasswordError("The current password is wrong.")
    set_user_password(conn, user_id, new, keep_token=keep_token)


def _clean_name(display_name: str) -> str:
    display_name = display_name.strip()
    if not display_name:
        raise ValidationError("Enter a name.")
    if len(display_name) > MAX_NAME_LENGTH:
        raise ValidationError(f"The name can be at most {MAX_NAME_LENGTH} characters.")
    return display_name


def set_display_name(conn: sqlite3.Connection, user_id: int, display_name: str) -> None:
    display_name = _clean_name(display_name)
    get_user(conn, user_id)
    conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (display_name, user_id))


def set_theme(conn: sqlite3.Connection, user_id: int, theme: str) -> None:
    if theme not in THEMES:
        raise ValidationError("The theme must be light or dark.")
    get_user(conn, user_id)
    conn.execute("UPDATE users SET theme = ? WHERE id = ?", (theme, user_id))


def _is_last_admin(conn: sqlite3.Connection, user: sqlite3.Row) -> bool:
    return bool(user["is_admin"]) and conn.execute(
        "SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0] == 1


def update_user(conn: sqlite3.Connection, user_id: int, acting_user_id: int, email: str | None = None,
                display_name: str | None = None, is_admin: bool | None = None) -> None:
    """An admin changes another user's email, name and admin flag (None leaves a field alone).

    Everything is checked before anything is written, so a refusal changes nothing. Changing an email
    doesn't end the user's sessions: they stay signed in and use the new address next time. You can't
    remove your own admin, and the last admin can't be demoted.
    """
    with db.write_transaction(conn):       # counting the admins and demoting one are a single step
        user = get_user(conn, user_id)
        new_email = user["email"] if email is None else _clean_email(email)
        new_name = user["display_name"] if display_name is None else _clean_name(display_name)
        new_admin = bool(user["is_admin"]) if is_admin is None else is_admin
        if not new_admin and user["is_admin"]:
            if _is_last_admin(conn, user):
                raise ValidationError("There must be at least one admin.")
            if user_id == acting_user_id:
                raise ValidationError("You can't remove your own admin. Ask another admin.")
        try:
            conn.execute("UPDATE users SET email = ?, display_name = ?, is_admin = ? WHERE id = ?",
                         (new_email, new_name, 1 if new_admin else 0, user_id))
        except sqlite3.IntegrityError:
            raise ValidationError("A user with that email already exists.")


def delete_user(conn: sqlite3.Connection, user_id: int, acting_user_id: int) -> None:
    """Delete a user and their sessions. Not yourself, and never the last admin."""
    with db.write_transaction(conn):
        user = get_user(conn, user_id)
        if user_id == acting_user_id:
            raise ValidationError("You can't delete your own account.")
        if _is_last_admin(conn, user):
            raise ValidationError("There must be at least one admin.")
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def list_users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, email, display_name, is_admin, created_at FROM users ORDER BY email COLLATE NOCASE"
    ).fetchall()


def _ask_password() -> str:
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat the password: "):
        raise ValidationError("The two passwords did not match.")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m northstar.users",
        description="Manage Northstar users (NORTHSTAR_DB, default data/northstar.db).")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="add a user (asks for a password)")
    create.add_argument("email")
    create.add_argument("name")
    create.add_argument("--admin", action="store_true", help="make the user an admin")
    reset = commands.add_parser("set-password", help="change a user's password and sign them out")
    reset.add_argument("email")
    commands.add_parser("list", help="list users")
    args = parser.parse_args(argv)
    try:
        path = config.database_path()
        if not path.is_file():      # connecting would create an empty one, and only the app sets a database up
            raise ValidationError(f"There is no database at {path}. Start Northstar once to set one up, then run this again.")
        with closing(db.connect(path)) as conn:
            db.require_current(conn, path)
            if args.command == "create":
                create_user(conn, args.email, args.name, _ask_password(), args.admin)
                print(f"Created {args.email.strip().lower()}{' (admin)' if args.admin else ''}.")
            elif args.command == "set-password":
                set_password(conn, args.email, _ask_password())
                print(f"Password changed for {args.email.strip().lower()}. They are signed out everywhere.")
            else:
                for row in list_users(conn):
                    print(f"{row['email']}\t{row['display_name']}\t{'admin' if row['is_admin'] else 'user'}")
    except ValidationError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
