"""The locale catalog and a person's locale. Plain functions, no web code. See docs/design/locale.md.

A locale is how numbers and dates are shown and typed: a decimal mark, a group mark, a date template and where a currency goes.
The conventions are the rows of `ref_locales`, loaded by a migration from CLDR and read by nothing else: the application never
reads CLDR. Three rules are not columns: groups of three digits, grouping from four digits and an ASCII minus.
"""

import sqlite3
from dataclasses import asdict, dataclass

from northstar import system_properties
from northstar.errors import ValidationError

DEFAULT_TAG = "en-US"                     # what an existing user has, and what the command line (no user) reads with
DEFAULT_PROPERTY = "ui.locale.default"    # the system property that says what a new or reactivated user starts with


@dataclass(frozen=True)
class Locale:
    tag: str
    label: str
    decimal_mark: str
    group_mark: str
    date_template: str
    currency_position: str          # "prefix" or "suffix"
    currency_code_spacing: str      # the exact text between an alphabetic currency code and the number

    def as_dict(self) -> dict:
        return asdict(self)


_COLUMNS = "tag, label, decimal_mark, group_mark, date_template, currency_position, currency_code_spacing"


def _locale(row: sqlite3.Row) -> Locale:
    return Locale(**{key: row[key] for key in row.keys()})


def find(conn: sqlite3.Connection, tag: str | None) -> Locale | None:
    row = conn.execute(f"SELECT {_COLUMNS} FROM ref_locales WHERE tag = ?", (tag,)).fetchone()
    return None if row is None else _locale(row)


def get(conn: sqlite3.Connection, tag: str | None) -> Locale:
    """The locale with this tag, or a ValidationError that is fit to show."""
    locale = find(conn, tag)
    if locale is None:
        raise ValidationError("Choose a number and date format from the list.")
    return locale


def catalog(conn: sqlite3.Connection) -> list[dict]:
    """Every locale a person can choose, by label, for a choice list."""
    return [{"tag": row["tag"], "label": row["label"]}
            for row in conn.execute("SELECT tag, label FROM ref_locales ORDER BY label")]


def default_tag(conn: sqlite3.Connection) -> str:
    """The tag new and reactivated users start with: the `ui.locale.default` property, which must be in the catalog."""
    tag = system_properties.get_value(conn, DEFAULT_PROPERTY)
    if find(conn, tag) is None:
        raise ValidationError(f"The default number and date format setting ({DEFAULT_PROPERTY}) is not one of the supported "
                              "formats, so a user cannot be added. Correct the setting first.")
    return tag


def for_user(conn: sqlite3.Connection, user_id: int | None) -> Locale:
    """The locale a person reads and types in. The command line has no user and reads in US English."""
    row = None if user_id is None else conn.execute("SELECT locale FROM users WHERE id = ?", (user_id,)).fetchone()
    return get(conn, DEFAULT_TAG if row is None else row["locale"])
