"""System properties: named, typed settings for the whole installation. Plain functions, no web code.
See docs/design/system-properties/design.md.

Every write of a value goes through `set_property`. It applies the generic checks (the setting exists, is not locked,
the text conforms to its data type, an unset value is allowed), then the feature validators named for the property in
ref_property_validators, in position order, all in one write transaction. The first refusal is raised as a
ValidationError whose message is written for the person who made the change, and nothing is written.

A validator is a plain function with no side effects. It gets a `Context`, raises a ValidationError to refuse, and
returns ACCEPT or ACCEPT_AND_LOCK. The service collects the decisions and makes the change, and the lock, as one write.
`VALIDATORS` is the only way a name in ref_property_validators becomes a function: never an import or a lookup by name.
"""

import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlsplit

from northstar import clock, config, db, writer
from northstar.errors import NotFoundError, ValidationError
from northstar.writer import Operation

log = logging.getLogger(__name__)

ACCEPT = "accept"
ACCEPT_AND_LOCK = "accept_and_lock"

STRING_MAX = 256
# The range JavaScript represents exactly, because the frontend reads an Integer as a number.
INTEGER_MAX = 2**53 - 1
_INTEGER = re.compile(r"-?\d{1,16}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
_TIME = re.compile(r"([01]\d|2[0-3]):[0-5]\d", re.ASCII)      # HH:MM on a 24-hour clock
SYSTEM_CURRENCY = "system.currency"     # saving it also enables that currency (see set_property)
SYSTEM_TIMEZONE = "system.timezone"     # saving it also sets the clock's zone (see set_property)
OIDC_ENABLED = "oidc.enabled"
OIDC_ISSUER = "oidc.issuer"
OIDC_CLIENT_ID = "oidc.client_id"
LOCAL_SIGNIN = "system.auth.local.enabled"
SESSION_HOURS_MAX = 24 * 365    # a year: a larger number would only overflow the expiry date


@dataclass(frozen=True)
class Context:
    """What a validator is told. `current` and `proposed` are typed (an int for an Integer, a bool for a Boolean, else text) and None when
    unset. `conn` may be read, never written."""
    name: str
    current: str | int | bool | None
    proposed: str | int | bool | None
    actor_id: int | None
    conn: sqlite3.Connection


def positive_integer(ctx: Context) -> str:
    if ctx.proposed is not None and ctx.proposed < 1:
        raise ValidationError("Enter a whole number of 1 or more.")
    return ACCEPT


def catalog_currency(ctx: Context) -> str:
    """The system currency: a code in the currency catalog, chosen before any account exists, and locked as soon as it is
    saved. Deleted accounts count, because they keep their currency."""
    if ctx.proposed is None:
        return ACCEPT
    if ctx.conn.execute("SELECT 1 FROM currencies WHERE code = ?", (ctx.proposed,)).fetchone() is None:
        raise ValidationError("That isn't a currency in the catalog. Search by code or name, such as USD or US Dollar.")
    if ctx.conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone() is not None:
        raise ValidationError("The system currency can't be changed once an account exists.")
    return ACCEPT_AND_LOCK


def catalog_locale(ctx: Context) -> str:
    """The default number and date format: a tag in the locale catalog. It does not lock, so it can be changed later."""
    if ctx.proposed is not None and ctx.conn.execute(
            "SELECT 1 FROM ref_locales WHERE tag = ?", (ctx.proposed,)).fetchone() is None:
        raise ValidationError("That isn't a supported number and date format.")
    return ACCEPT


def iana_timezone(ctx: Context) -> str:
    """The installation's time zone: a name in the zone database, such as America/Chicago. It does not lock."""
    if ctx.proposed is not None:
        try:
            clock.zone_for(ctx.proposed)
        except ValueError:
            raise ValidationError("That isn't a time zone name. Use a name such as America/Chicago or Europe/London.") from None
    return ACCEPT


def _linked_admin_exists(conn: sqlite3.Connection, issuer: str) -> bool:
    """Whether an active administrator has signed in through (is linked to) this issuer. Nobody can be linked until the
    identity storage exists (step 2 of docs/design/oidc, #167), which replaces this with the real query. Until then it
    refuses, which is the safe answer: password sign-in cannot be switched off."""
    return False


def _oidc_missing(conn: sqlite3.Connection) -> list[str]:
    """What OIDC sign-in still needs before it can be on, in words for an admin. Empty when it is complete."""
    missing = []
    if get_value(conn, OIDC_ISSUER) is None:
        missing.append("the issuer (oidc.issuer)")
    if get_value(conn, OIDC_CLIENT_ID) is None:
        missing.append("the client ID (oidc.client_id)")
    try:
        if config.oidc_client_secret() is None:
            missing.append("the client secret (NORTHSTAR_OIDC_CLIENT_SECRET or NORTHSTAR_OIDC_CLIENT_SECRET_FILE, then restart)")
        url = config.public_url()
    except config.ConfigurationError as err:
        raise ValidationError(f"{err} Fix it and restart Northstar.") from None
    if url is None:
        missing.append("the public address (NORTHSTAR_PUBLIC_URL, then restart)")
    elif url.startswith("https://") and not config.cookie_secure():
        missing.append("NORTHSTAR_COOKIE_SECURE=1, because Northstar is served over HTTPS")
    return missing


def oidc_enabled(ctx: Context) -> str:
    """OIDC sign-in can be turned on only when it is fully set up, and off only while password sign-in is on, so that one of
    the two ways in always works."""
    if ctx.proposed is True:
        missing = _oidc_missing(ctx.conn)
        if missing:
            raise ValidationError("OIDC sign-in can't be turned on yet. Still needed: " + "; ".join(missing) + ".")
    elif get_value(ctx.conn, LOCAL_SIGNIN) is False:
        raise ValidationError("Turn password sign-in on first. With both off, nobody could sign in.")
    return ACCEPT


def local_signin(ctx: Context) -> str:
    """Password sign-in can be turned off only when OIDC works and an admin has already signed in through it, because
    otherwise a mistake in the provider's setup would lock everyone out. Turning it on is always allowed."""
    if ctx.proposed is True:
        return ACCEPT
    if get_value(ctx.conn, OIDC_ENABLED) is not True or _oidc_missing(ctx.conn):
        raise ValidationError("Password sign-in can't be turned off until OIDC sign-in is on and fully set up.")
    if not _linked_admin_exists(ctx.conn, get_value(ctx.conn, OIDC_ISSUER)):
        raise ValidationError(
            "Password sign-in can't be turned off until an admin has signed in through OIDC. Sign in that way once "
            "first, so you know it works.")
    return ACCEPT


def oidc_issuer(ctx: Context) -> str:
    """The issuer is an exact address: HTTPS (plain HTTP only for localhost), with no query or fragment. It can't be cleared
    while OIDC is on, and can't change while password sign-in is off, because the admins' links belong to the old one."""
    if ctx.proposed is None:
        if get_value(ctx.conn, OIDC_ENABLED) is True:
            raise ValidationError("Turn OIDC sign-in off before clearing the issuer.")
        return ACCEPT
    try:
        parts = urlsplit(ctx.proposed)
        host, _ = parts.hostname, parts.port
    except ValueError:
        parts, host = None, None
    local = host in ("localhost", "127.0.0.1", "::1")
    if host is None or (parts.scheme != "https" and not (parts.scheme == "http" and local)) \
            or parts.username is not None or "?" in ctx.proposed or "#" in ctx.proposed:
        raise ValidationError("Enter the issuer as an https:// address with no query or fragment, such as https://id.example.com.")
    if get_value(ctx.conn, LOCAL_SIGNIN) is False:
        raise ValidationError("Turn password sign-in on before changing the issuer. The admins signed in through the old one.")
    return ACCEPT


def oidc_client_id(ctx: Context) -> str:
    """The client ID can't be cleared while OIDC sign-in is on."""
    if ctx.proposed is None and get_value(ctx.conn, OIDC_ENABLED) is True:
        raise ValidationError("Turn OIDC sign-in off before clearing the client ID.")
    return ACCEPT


def oidc_session_hours(ctx: Context) -> str:
    if ctx.proposed is None or not 1 <= ctx.proposed <= SESSION_HOURS_MAX:
        raise ValidationError(f"Enter a whole number of hours from 1 to {SESSION_HOURS_MAX}.")
    return ACCEPT


VALIDATORS = {
    "positive_integer": positive_integer,
    "catalog_currency": catalog_currency,
    "catalog_locale": catalog_locale,
    "iana_timezone": iana_timezone,
    "oidc_enabled": oidc_enabled,
    "local_signin": local_signin,
    "oidc_issuer": oidc_issuer,
    "oidc_client_id": oidc_client_id,
    "oidc_session_hours": oidc_session_hours,
}


def _typed(data_type: str, value: str | None) -> str | int | bool | None:
    if value is None:
        return None
    if data_type == "Integer":
        return int(value)
    if data_type == "Boolean":
        return value == "true"
    return value


def _row(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT p.id, p.name, t.name AS data_type, p.value, p.allow_null, p.hint, p.read_only "
        "FROM system_properties p JOIN ref_property_data_types t ON t.id = p.data_type_id WHERE p.name = ?", (name,)
    ).fetchone()
    if row is None:
        raise NotFoundError("That setting doesn't exist.")
    return row


def get_value(conn: sqlite3.Connection, name: str) -> str | int | bool | None:
    """The value of a property as its type: an int for an Integer, a bool for a Boolean, else text, and None when it is unset. The one way the
    rest of the application reads a setting."""
    row = _row(conn, name)
    return _typed(row["data_type"], row["value"])


def list_properties(conn: sqlite3.Connection) -> list[dict]:
    """Every property with its type, its hint and, for a Lookup, its options, ordered by name."""
    options: dict[int, list[dict]] = {}
    for row in conn.execute("SELECT property_id, value, label FROM ref_property_lookups ORDER BY id"):
        options.setdefault(row["property_id"], []).append({"value": row["value"], "label": row["label"]})
    return [
        {"name": row["name"], "type": row["data_type"], "value": row["value"], "allow_null": bool(row["allow_null"]),
         "hint": row["hint"], "read_only": bool(row["read_only"]), "options": options.get(row["id"], [])}
        for row in conn.execute(
            "SELECT p.id, p.name, t.name AS data_type, p.value, p.allow_null, p.hint, p.read_only "
            "FROM system_properties p JOIN ref_property_data_types t ON t.id = p.data_type_id ORDER BY p.name")]


def _normalized(text: str | None) -> str | None:
    """The submitted text without surrounding whitespace, or None when nothing is left: a blank submission means unset."""
    text = (text or "").strip()
    return text or None


def _checked(conn: sqlite3.Connection, row: sqlite3.Row, text: str) -> str:
    """The stored form of text that is not blank, if it conforms to the property's data type."""
    data_type = row["data_type"]
    if data_type == "Integer":
        if not _INTEGER.fullmatch(text) or abs(int(text)) > INTEGER_MAX:
            raise ValidationError("Enter a whole number.")
        return str(int(text))
    if data_type == "Boolean":
        if text not in ("true", "false"):
            raise ValidationError("Choose Yes or No.")
        return text
    if data_type == "Date":
        try:
            if not _DATE.fullmatch(text):
                raise ValueError
            date.fromisoformat(text)
        except ValueError:
            raise ValidationError("Enter a date like 2026-11-06.") from None
        return text
    if data_type == "Time":
        if not _TIME.fullmatch(text):
            raise ValidationError("Enter a time of day like 04:30, on a 24-hour clock.")
        return text
    if len(text) > STRING_MAX:
        raise ValidationError(f"Use {STRING_MAX} characters or fewer.")
    if data_type == "Lookup" and not conn.execute(
            "SELECT 1 FROM ref_property_lookups WHERE property_id = ? AND value = ?", (row["id"], text)).fetchone():
        raise ValidationError("Choose one of the listed options.")
    return text


def set_property(op: Operation, name: str, text: str | None) -> str | None:
    """Set a property from submitted text and return what is now stored (None when unset). A submission that, once
    normalized, equals the stored value writes nothing and runs no validator. Saving the time zone also makes it the
    zone `today()` uses, once the change has been committed."""
    stored = save_property(op, name, text)
    if name == SYSTEM_TIMEZONE:
        clock.set_zone(stored)
    return stored


def is_read_only(conn: sqlite3.Connection, name: str) -> bool:
    """Whether a property is locked, so a value can no longer be written to it."""
    return bool(_row(conn, name)["read_only"])


def apply_timezone(conn: sqlite3.Connection, environment: str | None = None) -> None:
    """At startup: set the clock's zone from the system.timezone property. While the property is empty and TZ names a
    zone, TZ is saved into it once, by the system user, and from then on TZ is ignored (see clock.start_zone)."""
    use, save = clock.start_zone(get_value(conn, SYSTEM_TIMEZONE), environment)
    if save:
        set_property(Operation(conn, None, "cli"), SYSTEM_TIMEZONE, save)
    clock.set_zone(use)


def save_property(op: Operation, name: str, text: str | None) -> str | None:
    """The write of `set_property`, without its last step. A caller that saves several properties in one transaction of its
    own (first-run setup) uses this, and applies the time zone itself once that transaction has committed: the clock is
    process-wide, so it must not change for a save that is rolled back."""
    conn = op.conn
    with db.write_transaction(conn):
        row = _row(conn, name)
        if row["read_only"]:
            raise ValidationError("This setting is locked and can't be changed.")
        proposed = _normalized(text)
        if proposed is None:
            if not row["allow_null"]:
                raise ValidationError("This setting is required.")
        else:
            proposed = _checked(conn, row, proposed)
        if proposed == row["value"]:
            return proposed
        context = Context(name, _typed(row["data_type"], row["value"]), _typed(row["data_type"], proposed),
                          op.actor_id, conn)
        lock = False
        for (validator,) in conn.execute(
                "SELECT validator FROM ref_property_validators WHERE property_id = ? ORDER BY position", (row["id"],)).fetchall():
            function = VALIDATORS.get(validator)
            if function is None:
                log.error("%s names the validator %r, which does not exist. The change was refused.", name, validator)
                raise ValidationError("This setting can't be changed right now.")
            decision = function(context)
            if decision not in (ACCEPT, ACCEPT_AND_LOCK):
                raise RuntimeError(f"The validator {validator} returned {decision!r}, not a decision.")
            lock = lock or decision == ACCEPT_AND_LOCK
        writer.update(op, "system_properties", row["id"], {"value": proposed, **({"read_only": 1} if lock else {})})
        if name == SYSTEM_CURRENCY and proposed is not None:
            # The system currency is always enabled: it is the one currency that needs no rates, so nothing else enables it.
            currency = conn.execute("SELECT id FROM currencies WHERE code = ?", (proposed,)).fetchone()
            writer.update(op, "currencies", currency["id"], {"is_enabled": 1})
        return proposed
