"""Balance import, step two: the dry run. See issue 101 and issue 79.

`plan_import` takes the rows the parser read and says exactly what an import into one account would do, and it records what the
account's balances looked like when it said so (an `Expectation` for every date in the file). It only reads. The commit, which
is the next step, recomputes the plan from the database as it is then and refuses the whole import if any expectation no longer
holds, so what is written is always what the person reviewed. Nothing is stored between the two: the server keeps no preview.

The same function, `expectations_for`, builds the expectations in both places.
"""

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from northstar import accounts, balances
from northstar.csvparse import ParsedRow, RowError
from northstar.errors import ValidationError

POLICIES = ("skip", "replace")
# What an import does with one row: add a balance, replace a different one (policy replace), leave an identical one alone,
# or leave a different one alone (policy skip).
OUTCOMES = ("add", "replace", "unchanged", "skip")


@dataclass(frozen=True)
class Expectation:
    """What one date of the account looked like: no balance (both None), or the id and version of the balance there. The
    version is the id of the operation that last wrote it, 0 for a balance from before the change log, so any edit after
    the review changes it."""
    date: str                  # YYYY-MM-DD
    balance_id: int | None
    version: int | None


@dataclass(frozen=True)
class PlannedRow:
    record: int
    date: date
    outcome: str
    cents: int                 # what the file says
    note: str | None           # what the file says; None when blank
    old_cents: int | None      # what the account has on that date now
    old_note: str | None
    result_note: str | None    # the note the balance would have after the import: the file's, or the old one if the file's is blank


@dataclass(frozen=True)
class ImportPlan:
    account_id: int
    policy: str
    rows: list[PlannedRow]
    errors: list[RowError]
    expectations: list[Expectation]    # one per distinct date in the file, oldest first

    @property
    def can_commit(self) -> bool:
        return not self.errors

    @property
    def counts(self) -> dict[str, int]:
        found = {outcome: 0 for outcome in OUTCOMES}
        for row in self.rows:
            found[row.outcome] += 1
        return found


def _existing(conn: sqlite3.Connection, account_id: int) -> dict[str, sqlite3.Row]:
    return {row["as_of_date"]: row for row in conn.execute(
        "SELECT id, as_of_date, amount_cents, note, version FROM live_balances WHERE account_id = ?", (account_id,))}


def _expectations(existing: dict[str, sqlite3.Row], dates: Iterable[date]) -> list[Expectation]:
    found = []
    for day in sorted(set(dates)):
        row = existing.get(day.isoformat())
        found.append(Expectation(day.isoformat(), None if row is None else row["id"], None if row is None else row["version"]))
    return found


def expectations_for(conn: sqlite3.Connection, account_id: int, dates: Iterable[date]) -> list[Expectation]:
    """The expectation for each distinct date, oldest first, from the account's balances as they are now."""
    return _expectations(_existing(conn, account_id), dates)


def _duplicate_errors(rows: list[ParsedRow]) -> list[RowError]:
    """Every record that shares its date with another is an error naming the others. Nothing is collapsed and no row is
    chosen over another, because even identical rows may mean a mistake in the file."""
    by_date = defaultdict(list)
    for row in rows:
        by_date[row.date].append(row.record)
    errors = []
    for day, records in sorted(by_date.items()):
        if len(records) < 2:
            continue
        named = ", ".join(str(record) for record in records[:-1]) + f" and {records[-1]}"
        for record in records:
            errors.append(RowError(record, None, f"Records {named} all have the date {day.isoformat()}. "
                                                 "Each date may appear once in the file."))
    return sorted(errors, key=lambda error: error.record)


def _classify(row: ParsedRow, existing: sqlite3.Row | None, policy: str) -> PlannedRow:
    if existing is None:
        return PlannedRow(row.record, row.date, "add", row.cents, row.note, None, None, row.note)
    old_cents, old_note = existing["amount_cents"], existing["note"]
    # A blank note in the file keeps the existing note, so it is never a difference; a note that differs is one.
    same = old_cents == row.cents and (row.note is None or row.note == old_note)
    outcome = "unchanged" if same else ("replace" if policy == "replace" else "skip")
    result_note = (old_note if row.note is None else row.note) if outcome == "replace" else old_note
    return PlannedRow(row.record, row.date, outcome, row.cents, row.note, old_cents, old_note, result_note)


def plan_import(conn: sqlite3.Connection, account_id: int, rows: list[ParsedRow], policy: str = "skip") -> ImportPlan:
    """What importing `rows` into this account would do. The account comes from the caller (the entry point the person
    started from), never from the file. A missing or deleted account is NotFoundError and a closed one is refused, as for any
    change to its balances; neither is a row error. Everything else wrong with the file is a RowError with its record number."""
    if policy not in POLICIES:
        raise ValidationError("Choose whether to skip or replace the dates that already have a balance.")
    balances.require_open(accounts.get_account(conn, account_id))
    existing = _existing(conn, account_id)
    planned = [_classify(row, existing.get(row.date.isoformat()), policy) for row in rows]
    return ImportPlan(account_id, policy, planned, _duplicate_errors(rows), _expectations(existing, (row.date for row in rows)))
