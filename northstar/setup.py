"""First-run setup: create the first administrator and set the most important system properties in one transaction.
Plain functions, no web code. See docs/design/first-run-setup.md.

Setup is open only while no administrator row exists (deleted ones count, the system user does not). Whoever may use it
holds a *setup session*, which the person gets by entering the bootstrap token printed in the container log. The token and
the sessions live in this process's memory (`SetupGate`), because the server is one process (see the Dockerfile): a restart
makes a new token and ends every session, which is the agreed behaviour, and nothing needs storing in the database.
"""

import hashlib
import hmac
import logging
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from zoneinfo import available_timezones

from northstar import clock, currencies, db, locales, system_properties, users
from northstar.errors import ValidationError
from northstar.writer import Operation

SESSION_SECONDS = 30 * 60                # how long a browser's setup session lasts, not extended on use
WRONG_TOKEN_LIMIT, WRONG_TOKEN_WINDOW = 5, 15 * 60       # wrong tokens from one address, in seconds
_MAX_TRACKED_ADDRESSES = 1000
# Uvicorn's own logger, so the token appears in the container log in the server's format.
log = logging.getLogger("uvicorn.error")


class SetupClosed(ValidationError):
    """An administrator already exists, so setup is over."""


class SetupSessionEnded(ValidationError):
    """The browser holds no valid setup session: it was never granted, it expired, or the server restarted."""


class SetupInvalid(ValidationError):
    """The submission was refused. `errors` maps a field to its message, and nothing was saved."""

    def __init__(self, errors: dict[str, str]):
        super().__init__(next(iter(errors.values())))
        self.errors = errors

    @property
    def details(self) -> dict:
        return {"errors": self.errors}


class TooManyAttempts(Exception):
    """Too many wrong tokens from one address. `wait` is the seconds until another attempt is allowed."""

    def __init__(self, wait: int):
        super().__init__(f"Try again in {wait} seconds.")
        self.wait = wait


def is_open(conn: sqlite3.Connection) -> bool:
    """Whether setup is available: no administrator row exists. A deleted administrator still counts, so deleting one can
    never reopen setup, and the system user is not an administrator for this purpose."""
    return conn.execute("SELECT 1 FROM users WHERE is_admin = 1 AND is_system = 0 LIMIT 1").fetchone() is None


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass
class SetupGate:
    """The bootstrap token, the browsers' setup sessions and the count of wrong tokens, all in memory.

    `token` is None when an administrator existed at startup, so nothing was generated. `now` is the clock for expiry and
    throttling (monotonic seconds), replaceable in a test."""
    token: str | None
    now: Callable[[], float] = time.monotonic
    _sessions: dict[str, float] = field(default_factory=dict)      # SHA-256 of a session's cookie value -> when it expires
    _wrong: dict[str, list[float]] = field(default_factory=dict)   # address -> when its wrong tokens were entered
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def start(cls, conn: sqlite3.Connection) -> "SetupGate":
        """At startup: when setup is open, make a token and print it once. Otherwise there is no token."""
        if not is_open(conn):
            return cls(None)
        gate = cls(secrets.token_urlsafe(32))
        # Printing this credential is the one deliberate exception to never logging one: the container log is where an
        # operator who owns the machine looks, and the token only lets someone create the first administrator.
        log.info("Northstar has no administrator yet. Open /setup on this server's address and enter this setup token to "
                 "create one:\n\n    %s\n\nThe token is shown only now. It stops working when setup is finished or Northstar "
                 "restarts, and a restart prints a new one.", gate.token)
        return gate

    def check_token(self, candidate: str, address: str | None) -> bool:
        """Whether the candidate is the setup token. A wrong one counts against the address, and an address with too many
        raises TooManyAttempts without comparing anything. An address that cannot be trusted shares one count."""
        key = address or ""
        with self._lock:
            moment = self.now()
            recent = [t for t in self._wrong.get(key, []) if t > moment - WRONG_TOKEN_WINDOW]
            if len(recent) >= WRONG_TOKEN_LIMIT:
                self._wrong[key] = recent
                raise TooManyAttempts(max(1, int(recent[0] + WRONG_TOKEN_WINDOW - moment) + 1))
            if self.token is not None and hmac.compare_digest(_digest(candidate), _digest(self.token)):
                self._wrong.pop(key, None)
                return True
            recent.append(moment)
            if len(self._wrong) >= _MAX_TRACKED_ADDRESSES and key not in self._wrong:
                self._wrong = {k: v for k, v in self._wrong.items() if v and v[-1] > moment - WRONG_TOKEN_WINDOW}
            self._wrong[key] = recent
            return False

    def grant(self) -> str:
        """A new setup session for a browser that gave the token. Returns the value for its cookie."""
        value = secrets.token_urlsafe(32)
        with self._lock:
            moment = self.now()
            self._sessions = {k: v for k, v in self._sessions.items() if v > moment}
            self._sessions[_digest(value)] = moment + SESSION_SECONDS
        return value

    def authorized(self, cookie: str | None) -> bool:
        """Whether the cookie value is a setup session that has not expired."""
        if not cookie:
            return False
        with self._lock:
            expires = self._sessions.get(_digest(cookie))
            return expires is not None and expires > self.now()

    def consume(self) -> None:
        """After setup has been committed: the token and every setup session are unusable, in every browser."""
        with self._lock:
            self.token = None
            self._sessions.clear()
            self._wrong.clear()


def options(conn: sqlite3.Connection) -> dict:
    """What the form offers and where each choice starts: the stored values, the full catalogs. An existing locked system
    currency is given as it is, so the form shows it read-only."""
    return {
        "currency": {"value": system_properties.get_value(conn, system_properties.SYSTEM_CURRENCY),
                     "locked": system_properties.is_read_only(conn, system_properties.SYSTEM_CURRENCY)},
        "currencies": currencies.catalog(conn),
        "locale": locales.default_tag(conn),
        # The whole row of each, because the form shows an example in the chosen format and nobody can fetch the catalog yet.
        "locales": [locales.get(conn, entry["tag"]).as_dict() for entry in locales.catalog(conn)],
        "timezone": system_properties.get_value(conn, system_properties.SYSTEM_TIMEZONE) or "UTC",
        "timezones": sorted(available_timezones()),
    }


@dataclass(frozen=True)
class Submission:
    email: str
    display_name: str
    password: str
    currency: str | None
    locale: str
    timezone: str


def complete(conn: sqlite3.Connection, gate: SetupGate, cookie: str | None, submitted: Submission) -> str:
    """Create the administrator and save the initial properties as one transaction, and return the administrator's email.

    Everything is checked first where that costs nothing, and again under the database write lock where it matters: that
    no administrator exists yet, so two submissions at once cannot both succeed, and that the setup session is still valid.
    The administrator is made by the system user, because nobody is signed in. The properties are saved as that
    administrator through the property service, so its validation and locking apply and an unchanged value writes nothing.
    A refusal of any field rolls everything back and leaves the setup session usable. Only a commit consumes the gate."""
    require_session(conn, gate, cookie)         # before anything slow, so a visitor with no session costs the server nothing
    problems = users.check_new_user(submitted.email, submitted.display_name, submitted.password)
    zone_saved = False
    with db.write_transaction(conn):
        require_session(conn, gate, cookie)
        email = submitted.email.strip().lower()
        errors = dict(problems)
        # An existing user's email, deleted or not, is refused: setup never promotes or reactivates anyone (add_user would).
        if "email" not in errors and conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone() is not None:
            errors["email"] = "A user with that email already exists."
        if locales.find(conn, submitted.locale) is None:
            errors["locale"] = "Choose a number and date format from the list."
        admin_id = None
        if not errors:
            # This hashes the password while holding the write lock, which add_user otherwise avoids. Nobody else has
            # anything to write while there is no administrator, and it happens once.
            admin_id = users.add_user(Operation(conn, None, "ui_edit"), submitted.email, submitted.display_name,
                                      submitted.password, is_admin=True, locale=submitted.locale)[0]
        # With no administrator (a field above was refused) the properties are still tried, as the system user, so the person
        # is told about every field at once. All of it is rolled back below, and a form that is refused hashes nothing.
        acting = Operation(conn, admin_id, "ui_edit")
        for field_name, name, text in _property_changes(conn, submitted):
            if field_name == "currency" and not text.strip():      # required while it is unset: no currency is preselected
                errors["currency"] = "Choose the household reporting currency."
                continue
            try:
                system_properties.save_property(acting, name, text)
            except ValidationError as refusal:
                errors[field_name] = str(refusal)
            zone_saved = zone_saved or name == system_properties.SYSTEM_TIMEZONE
        if errors:
            raise SetupInvalid(errors)
    if zone_saved:
        clock.set_zone(system_properties.get_value(conn, system_properties.SYSTEM_TIMEZONE))
    gate.consume()
    return email


def _property_changes(conn: sqlite3.Connection, submitted: Submission) -> list[tuple[str, str, str]]:
    """(form field, property, submitted text) for each property the form sets. A locked currency is left alone, never
    written, whatever was submitted."""
    changes = []
    if not system_properties.is_read_only(conn, system_properties.SYSTEM_CURRENCY):
        changes.append(("currency", system_properties.SYSTEM_CURRENCY, submitted.currency or ""))
    changes.append(("locale", locales.DEFAULT_PROPERTY, submitted.locale))
    changes.append(("timezone", system_properties.SYSTEM_TIMEZONE, submitted.timezone))
    return changes


def require_session(conn: sqlite3.Connection, gate: SetupGate, cookie: str | None) -> None:
    """Setup is closed once an administrator exists, whatever the cookie says, so a retry after a lost response is told it
    is done and not that its session ended. Otherwise the browser needs a live setup session."""
    if not is_open(conn):
        raise SetupClosed("Setup has already been completed.")
    if not gate.authorized(cookie):
        raise SetupSessionEnded("Your setup session has ended. Enter the setup token again.")
