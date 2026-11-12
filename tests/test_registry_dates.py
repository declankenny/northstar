"""A report that excludes dates does it by the registry's declared kind (a Date or a Timestamp), so a date column the registry declares as
anything else would slip through. Nothing in the registry can vouch for itself, so this checks the declared kinds against evidence
that does not come from them.

Every date column in the schema is TEXT, so the declared type says nothing. Each one carries its own evidence in its table's
definition: a CHECK that uses date(column) or the ISO date pattern for that column, or a default made with strftime or date. That
evidence is definitive: a column that has it must be declared a date. A column whose values merely look like dates in a household
is not proof (a note can say "2026-11-12"), so it is a prompt for review: it must be declared a date or be listed in
REVIEWED_TEXT with the reason it is text. The convention that keeps this honest is in docs/schema.md: a date column is TEXT with a
CHECK on its format, and a timestamp has a strftime default. A date column that follows neither and holds no value in the
synthetic household below is not caught."""

import re
from dataclasses import replace

import pytest

from conftest import add_account, add_balance
from northstar.listdefs import catalog as household_catalog
from northstar.listdefs.tables import TABLES
from northstar.lists.kinds import Date, Text

ISO_GLOB = r"\[0-9\]\[0-9\]\[0-9\]\[0-9\]-\[0-9\]\[0-9\]-\[0-9\]\[0-9\]"
DEFAULTS = re.compile(r"strftime\s*\(|datetime\s*\(|\bdate\s*\(|CURRENT_(TIMESTAMP|DATE)", re.IGNORECASE)
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# Offered columns that are text although every value in the synthetic household looks like a date. None yet. An entry is
# (table, column): "why it is text".
REVIEWED_TEXT: dict[tuple[str, str], str] = {}


def schema_says_date(conn, owner: str, column: str) -> str | None:
    """Why the definition of table `owner` says `column` holds a date or a timestamp, or None."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name = ?", (owner,)).fetchone()
    sql = row[0] if row else ""
    for info in conn.execute(f'PRAGMA table_info("{owner}")'):
        if info["name"] == column and info["dflt_value"] and DEFAULTS.search(info["dflt_value"]):
            return f"its default is {info['dflt_value']}"
    if re.search(rf"\bdate\s*\(\s*{re.escape(column)}\s*\)", sql, re.IGNORECASE):
        return "a CHECK uses date() on it"
    if re.search(rf"\b{re.escape(column)}\s+GLOB\s+'{ISO_GLOB}'", sql, re.IGNORECASE):
        return "a CHECK matches it against the ISO date pattern"
    return None


def declared_wrongly(conn, tables) -> list[str]:
    """Offered columns the table definitions say are dates that the registry does not declare as dates."""
    wrong = []
    for name, table in tables.items():
        for column, field in table.fields.items():
            why = schema_says_date(conn, table.based_on or name, column)     # a view's column is the column of the table it is based on
            if why and not isinstance(field.kind, Date):
                wrong.append(f"{name}.{column}: {why}, but it is declared {type(field.kind).__name__}")
    return wrong


def looks_like_dates(conn, tables) -> list[str]:
    """Offered columns that are not declared dates but whose every value in the household is shaped like one (and there is one)."""
    found = []
    for name, table in tables.items():
        for column, field in table.fields.items():
            if isinstance(field.kind, Date) or (name, column) in REVIEWED_TEXT:
                continue
            values = [r[0] for r in conn.execute(f'SELECT DISTINCT "{column}" FROM "{name}" WHERE "{column}" IS NOT NULL LIMIT 200')]
            if values and all(isinstance(v, str) and (DAY.match(v) or INSTANT.match(v)) for v in values):
                found.append(f"{name}.{column}")
    return found


@pytest.fixture
def household(conn):
    """Accounts with balances, so the views that are worked out have rows, and every table the registry offers has a value to look at."""
    first, second = add_account(conn, "Alpha", 1, "Savings"), add_account(conn, "Beta", 2, "Credit card")
    for account, amount in ((first, 100_00), (second, 20_00)):
        add_balance(conn, account, "2026-06-30", amount)
        add_balance(conn, account, "2026-07-31", amount + 5_00)
    conn.commit()
    return conn


def test_every_column_the_table_definitions_say_is_a_date_is_declared_one(household):
    assert declared_wrongly(household, TABLES) == []


def test_the_check_finds_what_it_is_for(household):
    """The guard is only worth having if it sees the columns that are dates today, and the ones that are not."""
    says = {(table, column) for table, definition in TABLES.items() for column in definition.fields
            if schema_says_date(household, definition.based_on or table, column)}
    assert {("accounts", "created_at"), ("users", "updated_at"), ("live_balance_values", "as_of_date"), ("account_balances", "as_of_date"),
            ("currencies", "rates_start"), ("account_types", "created_at")} <= says
    assert ("accounts", "name") not in says and ("account_types", "stale_after_days") not in says and ("accounts", "is_open") not in says


def test_a_date_declared_as_text_is_caught(household):
    broken = {**TABLES, "accounts": replace(TABLES["accounts"], fields={**TABLES["accounts"].fields, "created_at": replace(TABLES["accounts"].fields["created_at"], kind=Text())}),
              "currencies": replace(TABLES["currencies"], fields={**TABLES["currencies"].fields, "rates_start": replace(TABLES["currencies"].fields["rates_start"], kind=Text())})}
    assert declared_wrongly(household, broken) == [
        "accounts.created_at: its default is strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), but it is declared Text",
        "currencies.rates_start: a CHECK matches it against the ISO date pattern, but it is declared Text"]


def test_each_kind_of_evidence_is_read_from_a_table_definition(conn):
    conn.execute("CREATE TABLE probe_dates (id INTEGER PRIMARY KEY, a TEXT CHECK (date(a) IS a), b TEXT CHECK (b GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'), "
                 "c TEXT DEFAULT (strftime('%Y', 'now')), d TEXT, e TEXT CHECK (length(e) < 5), f TEXT DEFAULT 'x')")
    assert {column for column in "abcdef" if schema_says_date(conn, "probe_dates", column)} == {"a", "b", "c"}


def test_a_column_that_only_looks_like_a_date_is_a_prompt_for_review_and_never_a_failure_by_itself(household):
    """Today nothing is shaped like a date without being one. A note that is, in a household, only needs a decision: declared a date,
    or reviewed and listed as text with the reason."""
    assert looks_like_dates(household, TABLES) == []
    household.execute("UPDATE accounts SET notes = '2026-11-12'")
    assert looks_like_dates(household, TABLES) == ["accounts.notes", "account_summaries.notes"]
    household.execute("UPDATE accounts SET notes = 'Opened 2026-11-12'")                       # a note that says more is plainly text
    assert looks_like_dates(household, TABLES) == []


def test_the_registry_offers_no_column_that_is_shaped_like_dates_and_not_declared_or_reviewed(household):
    household.execute("UPDATE accounts SET notes = NULL")
    assert looks_like_dates(household, TABLES) == [], "declare it a date, or list it in REVIEWED_TEXT with the reason it is text"


def test_the_registry_the_reports_use_is_the_one_checked(household):
    """Reports build their field tree from the household's catalog, so what is checked above is what they filter by."""
    catalog = household_catalog(household)
    for table in TABLES:
        assert catalog.tables[table] is TABLES[table]
