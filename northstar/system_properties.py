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

from northstar import db, writer
from northstar.errors import NotFoundError, ValidationError
from northstar.writer import Operation

log = logging.getLogger(__name__)

ACCEPT = "accept"
ACCEPT_AND_LOCK = "accept_and_lock"

STRING_MAX = 256
# The range JavaScript represents exactly, because the frontend reads an Integer as a number.
INTEGER_MAX = 2**53 - 1
_INTEGER = re.compile(r"-?\d{1,16}")


@dataclass(frozen=True)
class Context:
    """What a validator is told. `current` and `proposed` are typed (an int for an Integer, else text) and None when
    unset. `conn` may be read, never written."""
    name: str
    current: str | int | None
    proposed: str | int | None
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


VALIDATORS = {
    "positive_integer": positive_integer,
    "catalog_currency": catalog_currency,
    "catalog_locale": catalog_locale,
}


def _typed(data_type: str, value: str | None) -> str | int | None:
    return int(value) if data_type == "Integer" and value is not None else value


def _row(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT p.id, p.name, t.name AS data_type, p.value, p.allow_null, p.hint, p.read_only "
        "FROM system_properties p JOIN ref_property_data_types t ON t.id = p.data_type_id WHERE p.name = ?", (name,)
    ).fetchone()
    if row is None:
        raise NotFoundError("That setting doesn't exist.")
    return row


def get_value(conn: sqlite3.Connection, name: str) -> str | int | None:
    """The value of a property as its type: an int for an Integer, else text, and None when it is unset. The one way the
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
    if len(text) > STRING_MAX:
        raise ValidationError(f"Use {STRING_MAX} characters or fewer.")
    if data_type == "Lookup" and not conn.execute(
            "SELECT 1 FROM ref_property_lookups WHERE property_id = ? AND value = ?", (row["id"], text)).fetchone():
        raise ValidationError("Choose one of the listed options.")
    return text


def set_property(op: Operation, name: str, text: str | None) -> str | None:
    """Set a property from submitted text and return what is now stored (None when unset). A submission that, once
    normalized, equals the stored value writes nothing and runs no validator."""
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
        return proposed
