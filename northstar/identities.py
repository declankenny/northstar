"""Who a validated OpenID Connect identity is. Plain functions, no web code. See docs/design/oidc/design.md.

By the time anything here runs, the identity provider's ID token has been fully validated (signature, issuer, audience, expiry,
nonce) and its claims are in a `Claims`. `sign_in` then decides, in one write transaction, which Northstar user the claims mean,
makes the user and the binding when that is allowed, and starts a session. Nothing is written unless the person is let in.

The rules, in order:
  1. A known identity (the exact issuer and subject) is its bound user, whatever their email or name has become. A deleted or
     system user is refused. A known identity is never matched again by email.
  2. An unknown identity needs a verified email: the claim `email_verified` must be exactly the boolean true.
  3. If that email belongs to an active user, the identity is bound to them and they sign in. This makes no user, so it is
     allowed when creation is off. Their name and role are kept.
  4. If it belongs to a deleted or system user, it is refused: nobody is brought back this way.
  5. If it belongs to nobody, a regular user is made only when `oidc.user.allow_creation` is on, with an unusable password.
A user has at most one binding per issuer, so a second subject presenting an email that is already bound is refused, and never
replaces the first. The change log records the new user and the binding, as the system user, in an operation of kind `oidc`.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from northstar import db, sessions, system_properties, users, writer
from northstar.errors import ValidationError
from northstar.writer import Operation

KIND = "oidc"
NOT_ALLOWED = "not_allowed"
EMAIL_UNVERIFIED = "email_unverified"
NOT_CONFIGURED = "not_configured"


class Refused(Exception):
    """An identity that may not sign in. `code` is one of NOT_ALLOWED (no account and none may be made, a deleted or system
    user, a conflicting binding or an unusable address: one message for all of them, so the sign-in page does not say which),
    EMAIL_UNVERIFIED, or NOT_CONFIGURED (OIDC is off or the issuer is not the configured one). `reason` is for the log: it
    never holds a claim, a token or an address."""

    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason

    def message(self, provider: str | None = None) -> str:
        """What the sign-in page says, naming the provider by the label the admin gave it."""
        label = provider or "Your identity provider"
        if self.code == EMAIL_UNVERIFIED:
            return f"{label} hasn't confirmed your email address. Verify it there, then try again."
        if self.code == NOT_CONFIGURED:
            return "Sign-in through an identity provider isn't available."
        return "This account can't sign in to Northstar. Ask a Northstar admin for access."


@dataclass(frozen=True)
class Claims:
    """The claims of a validated ID token that identity resolution reads. `email`, `email_verified` and `name` are exactly
    what the token held, of any type, because a wrong type is a refusal and not something to convert."""
    issuer: str
    subject: str
    email: object = None
    email_verified: object = None
    name: object = None


@dataclass(frozen=True)
class Resolved:
    user_id: int
    created: bool       # a user was made
    linked: bool        # an existing user was bound to this identity


@dataclass(frozen=True)
class SignedIn:
    token: str
    resolved: Resolved
    max_age: int        # how many seconds the session lasts, for the cookie


def fingerprint(issuer: str, client_id: str) -> str:
    """A SHA-256, as hex, of the provider configuration a session or a login in progress belongs to. It changes when the
    issuer or the client ID does, and not when the client secret or anything else does."""
    return hashlib.sha256(json.dumps([issuer, client_id], separators=(",", ":")).encode()).hexdigest()


def current_fingerprint(conn: sqlite3.Connection) -> str | None:
    """The fingerprint of the configuration now in force, or None when OIDC is off or not fully set."""
    if system_properties.get_value(conn, system_properties.OIDC_ENABLED) is not True:
        return None
    issuer = system_properties.get_value(conn, system_properties.OIDC_ISSUER)
    client_id = system_properties.get_value(conn, system_properties.OIDC_CLIENT_ID)
    return None if issuer is None or client_id is None else fingerprint(issuer, client_id)


def _display_name(claims: Claims, email: str) -> str:
    """The provider's name for a new user if it is usable (not blank, printable and short enough), else their email."""
    name = claims.name
    if isinstance(name, str):
        name = name.strip()
        if name and name.isprintable() and len(name) <= users.MAX_NAME_LENGTH:
            return name
    return email[:users.MAX_NAME_LENGTH]


def _bind(op: Operation, user_id: int, claims: Claims) -> None:
    try:
        writer.insert(op, "user_identities", {"user_id": user_id, "issuer": claims.issuer, "subject": claims.subject})
    except sqlite3.IntegrityError:
        # Another binding for this identity or this user appeared first. Under the write lock this should not happen.
        raise Refused(NOT_ALLOWED, "the identity or the user is already bound") from None


def _resolve(conn: sqlite3.Connection, claims: Claims) -> Resolved:
    known = conn.execute(
        "SELECT i.user_id, u.deleted, u.is_system FROM user_identities i JOIN users u ON u.id = i.user_id "
        "WHERE i.issuer = ? AND i.subject = ?", (claims.issuer, claims.subject)).fetchone()
    if known is not None:
        if known["deleted"] or known["is_system"]:
            raise Refused(NOT_ALLOWED, "the bound user is deleted or the system user")
        return Resolved(known["user_id"], created=False, linked=False)

    if not isinstance(claims.email, str) or claims.email_verified is not True:
        raise Refused(EMAIL_UNVERIFIED, "the email is missing or not verified")
    try:
        email = users._clean_email(claims.email)
    except ValidationError:
        raise Refused(NOT_ALLOWED, "the email is not a usable address") from None

    owner = conn.execute("SELECT id, deleted, is_system FROM users WHERE email = ?", (email,)).fetchone()
    if owner is not None:
        if owner["deleted"] or owner["is_system"]:
            raise Refused(NOT_ALLOWED, "the email belongs to a deleted or system user")
        if conn.execute("SELECT 1 FROM user_identities WHERE user_id = ? AND issuer = ?",
                        (owner["id"], claims.issuer)).fetchone() is not None:
            raise Refused(NOT_ALLOWED, "the user is already bound to another identity at this issuer")
        _bind(Operation(conn, None, KIND, {"action": "link"}), owner["id"], claims)
        return Resolved(owner["id"], created=False, linked=True)

    if system_properties.get_value(conn, "oidc.user.allow_creation") is not True:
        raise Refused(NOT_ALLOWED, "there is no account and creation is off")
    op = Operation(conn, None, KIND, {"action": "create"})
    user_id = writer.insert(op, "users", {
        "email": email, "display_name": _display_name(claims, email), "password_hash": users.UNUSABLE_HASH,
        "is_admin": 0, **users.new_user_defaults(conn)})
    _bind(op, user_id, claims)
    return Resolved(user_id, created=True, linked=False)


def sign_in(conn: sqlite3.Connection, claims: Claims, now: datetime | None = None) -> SignedIn:
    """Resolve the claims to a user, make the user and the binding if that is allowed, and start an OIDC session for them,
    all in one write transaction. A refusal raises `Refused` and leaves nothing behind: no user, no binding, no session.
    The configuration is read inside the transaction, so a change that has just been saved is the one that counts."""
    with db.write_transaction(conn):
        fingerprint_now = current_fingerprint(conn)
        if fingerprint_now is None or claims.issuer != system_properties.get_value(conn, system_properties.OIDC_ISSUER):
            raise Refused(NOT_CONFIGURED, "OIDC is off or the issuer is not the configured one")
        resolved = _resolve(conn, claims)
        hours = system_properties.get_value(conn, "oidc.session.lifetime_hours")
        token = sessions.create_session(conn, resolved.user_id, now, method=sessions.OIDC,
                                        fingerprint=fingerprint_now, lifetime=timedelta(hours=hours))
        return SignedIn(token, resolved, hours * 3600)
