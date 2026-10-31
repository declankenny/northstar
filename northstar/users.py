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
from contextlib import closing

from northstar import config, db, sessions
from northstar.errors import ValidationError

MIN_PASSWORD_LENGTH = 12
MAX_NAME_LENGTH = 100
THEMES = ("light", "dark")
_SCRYPT = {"n": 2**15, "r": 8, "p": 1}
_SCRYPT_MAXMEM = 2**27


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=_SCRYPT_MAXMEM)


def hash_password(password: str) -> str:
    """scrypt (in Python's standard library) with a random salt, in a self-describing string."""
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, **_SCRYPT)
    b64 = lambda raw: base64.b64encode(raw).decode()
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        actual = _scrypt(password, base64.b64decode(salt), int(n), int(r), int(p))
        return hmac.compare_digest(actual, base64.b64decode(digest))
    except ValueError:
        return False


# Checked when the email is unknown, so a miss takes as long as a wrong password.
_DUMMY_HASH = hash_password("not-a-real-password")


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
        verify_password(password, _DUMMY_HASH)
        return None
    return row if verify_password(password, row["password_hash"]) else None


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
    conn.execute("BEGIN")
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user_id))
    sessions.end_sessions(conn, user_id, except_token=keep_token)
    conn.execute("COMMIT")


def change_own_password(conn: sqlite3.Connection, user_id: int, current: str, new: str,
                        keep_token: str | None) -> None:
    """A user changes their own password. Needs the current one. Their other browsers are signed out."""
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or not verify_password(current, row["password_hash"]):
        raise ValidationError("The current password is wrong.")
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
        with closing(db.connect(config.database_path())) as conn:
            db.migrate(conn)
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
