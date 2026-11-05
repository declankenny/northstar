"""The locale catalog and a person's locale. Plain functions, no web code. See docs/design/locale.md.

A locale is how numbers and dates are shown and typed: a decimal mark, a group mark, a date template and where a currency goes.
The conventions are the rows of `ref_locales`, loaded by a migration from CLDR and read by nothing else: the application never
reads CLDR. Three rules are not columns: groups of three digits, grouping from four digits and an ASCII minus.
"""

import contextvars
import re
import sqlite3
from contextlib import contextmanager
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

    def date(self, value) -> str:
        """A calendar date, a `date` or its `YYYY-MM-DD` text, as this locale writes it: "May 7, 2026", "07.05.2026". Month
        names are English, like the rest of the interface. The same template the page fills, from the same text."""
        year, month, day = (int(part) for part in (value.isoformat() if hasattr(value, "isoformat") else str(value))[:10].split("-"))
        pieces = {"{year}": str(year), "{month}": str(month), "{month2}": f"{month:02d}", "{month_short}": MONTHS[month - 1],
                  "{day}": str(day), "{day2}": f"{day:02d}"}
        return re.sub(r"\{[a-z_0-9]+\}", lambda found: pieces.get(found.group(0), found.group(0)), self.date_template)

    def integer(self, n: int) -> str:
        """A whole number grouped from four digits with this locale's group mark: 1234567 is "1,234,567" or "1.234.567"."""
        digits = str(abs(int(n)))
        groups = []
        for end in range(len(digits), 0, -3):
            groups.insert(0, digits[max(0, end - 3):end])
        return ("-" if n < 0 else "") + self.group_mark.join(groups)


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# US English without a database, for text written where nobody is signed in (the command line, a test). It is the en-US row of
# ref_locales, and a test says so.
US_ENGLISH = Locale("en-US", "English (United States)", ".", ",", "{month_short} {day}, {year}", "prefix", "\u00a0")

# The locale of the person a request is for. Every message written for a person says its dates and numbers in it, and a
# message is written deep in the rules, far from the request, so the request sets it once (see web/auth_routes.run) and a
# message reads it with `speaking()`. Outside a request it is US English.
_speaking: contextvars.ContextVar[Locale | None] = contextvars.ContextVar("speaking", default=None)


def speaking() -> Locale:
    """The locale to write a message in: the signed-in person's during a request, US English otherwise."""
    return _speaking.get() or US_ENGLISH


@contextmanager
def speak_as(locale: Locale | None):
    """Write the messages inside the block in `locale` (nobody's, with None, leaves US English)."""
    token = _speaking.set(locale)
    try:
        yield
    finally:
        _speaking.reset(token)


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


class LocaleChanged(ValidationError):
    """A form was using one number and date format and the person's saved one is now another, so what was typed may mean
    something else. Nothing was saved. `now` is the saved locale, which the page shows and then reads the draft in."""

    def __init__(self, now: Locale):
        super().__init__(f"Your number and date format changed to {now.label}. Nothing was saved.")
        self.now = now

    @property
    def details(self) -> dict:
        return {"locale_changed": {"tag": self.now.tag, "label": self.now.label}}


def require_current(conn: sqlite3.Connection, user_id: int | None, tag: str | None) -> None:
    """Refuse with LocaleChanged unless the person's saved locale is the one the form says it was using. A form that does not
    say (the command line, a script) is not checked. Called inside the write transaction, so the preference cannot change
    between the check and the write."""
    if tag is None:
        return
    saved = for_user(conn, user_id)
    if saved.tag != tag:
        raise LocaleChanged(saved)


def reading_locale(conn: sqlite3.Connection, user_id: int | None, tag: str | None) -> Locale:
    """The locale to read typed amounts in: the one the form was using, which must still be the saved one, else the saved one."""
    require_current(conn, user_id, tag)
    return for_user(conn, user_id)
