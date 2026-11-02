"""Balance import, steps two and three: the dry run and the commit. See issues 101, 103 and 79.

`plan_import` takes the rows the parser read and says exactly what an import into one account would do, and it records what the
account's balances looked like when it said so (an `Expectation` for every date in the file). It only reads. The commit, which
is the next step, recomputes the plan from the database as it is then and refuses the whole import if any expectation no longer
holds, so what is written is always what the person reviewed. Nothing is stored between the two: the server keeps no preview.

The same function, `expectations_for`, builds the expectations in both places.

`commit_import` is the write. It recomputes the plan inside one write transaction, refuses (writing nothing) unless the account
still looks the way the review recorded and the rows and policy are the ones reviewed, and otherwise writes every add and
replacement as one operation of kind `import`.
"""

import hashlib
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from northstar import accounts, balances, db, writer
from northstar.csvparse import Mapping, ParsedRow, RowError
from northstar.errors import ValidationError
from northstar.writer import Operation

POLICIES = ("skip", "replace")
# What an import does with one row: add a balance, replace a different one (policy replace), leave an identical one alone,
# or leave a different one alone (policy skip).
OUTCOMES = ("add", "replace", "unchanged", "skip")
# The `source` of every balance an import writes.
SOURCE = "csv"
MAX_FILE_NAME = 255


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
    balance_id: int | None = None      # the balance already on that date, which a replacement changes


@dataclass(frozen=True)
class ImportPlan:
    account_id: int
    policy: str
    rows: list[PlannedRow]
    errors: list[RowError]
    expectations: list[Expectation]    # one per distinct date in the file, oldest first
    fingerprint: str                   # a checksum of the account, the policy and the rows this plan is for

    @property
    def can_commit(self) -> bool:
        return not self.errors

    @property
    def reviewed(self) -> "Reviewed":
        """What the Review screen hands back with the import, for the commit to check."""
        return Reviewed(self.expectations, self.fingerprint)

    @property
    def counts(self) -> dict[str, int]:
        found = {outcome: 0 for outcome in OUTCOMES}
        for row in self.rows:
            found[row.outcome] += 1
        return found


@dataclass(frozen=True)
class Reviewed:
    """What was true when the person reviewed the import: the state of every date, and which rows and policy it was for."""
    expectations: list[Expectation]
    fingerprint: str


def fingerprint_of(account_id: int, policy: str, rows: list[ParsedRow]) -> str:
    """A checksum of exactly what is to be imported. The expectations only describe the account; this says the rows and the
    policy at commit are the ones that were reviewed, even if the person went back and chose another file or setting."""
    body = [account_id, policy, [[row.record, row.date.isoformat(), row.cents, row.note] for row in rows]]
    return hashlib.sha256(json.dumps(body, separators=(",", ":")).encode()).hexdigest()


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
        return PlannedRow(row.record, row.date, "add", row.cents, row.note, None, None, row.note, None)
    old_cents, old_note = existing["amount_cents"], existing["note"]
    # A blank note in the file keeps the existing note, so it is never a difference; a note that differs is one.
    same = old_cents == row.cents and (row.note is None or row.note == old_note)
    outcome = "unchanged" if same else ("replace" if policy == "replace" else "skip")
    result_note = (old_note if row.note is None else row.note) if outcome == "replace" else old_note
    return PlannedRow(row.record, row.date, outcome, row.cents, row.note, old_cents, old_note, result_note, existing["id"])


def plan_import(conn: sqlite3.Connection, account_id: int, rows: list[ParsedRow], policy: str = "skip") -> ImportPlan:
    """What importing `rows` into this account would do. The account comes from the caller (the entry point the person
    started from), never from the file. A missing or deleted account is NotFoundError and a closed one is refused, as for any
    change to its balances; neither is a row error. Everything else wrong with the file is a RowError with its record number."""
    if policy not in POLICIES:
        raise ValidationError("Choose whether to skip or replace the dates that already have a balance.")
    balances.require_open(accounts.get_account(conn, account_id))
    existing = _existing(conn, account_id)
    planned = [_classify(row, existing.get(row.date.isoformat()), policy) for row in rows]
    return ImportPlan(account_id, policy, planned, _duplicate_errors(rows),
                      _expectations(existing, (row.date for row in rows)), fingerprint_of(account_id, policy, rows))


class StaleImport(ValidationError):
    """The review no longer describes what the commit was given. Nothing was written; the person should review again.
    `dates` are the dates whose balance changed, and is empty when the rows or the policy are not the ones reviewed."""

    def __init__(self, message: str, dates: list[str] | None = None):
        super().__init__(message)
        self.dates = dates or []

    @property
    def details(self) -> dict:
        return {"dates": self.dates}


@dataclass(frozen=True)
class ImportResult:
    added: int
    updated: int
    unchanged: int
    skipped: int


def _differing_dates(reviewed: list[Expectation], now: list[Expectation]) -> list[str]:
    """Every date whose expectation is not the same now, including a date that is in only one of the two."""
    then = {expectation.date: expectation for expectation in reviewed}
    current = {expectation.date: expectation for expectation in now}
    return sorted(day for day in then.keys() | current.keys() if then.get(day) != current.get(day))


def _file_name(name: str | None) -> str | None:
    """The base name only (no folders), without control characters, at most MAX_FILE_NAME characters, or None."""
    if not name:
        return None
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    clean = "".join(char for char in base if char.isprintable()).strip()[:MAX_FILE_NAME]
    return clean or None


def commit_import(conn: sqlite3.Connection, actor_id: int | None, account_id: int, rows: list[ParsedRow], policy: str,
                  reviewed: Reviewed, file_name: str | None = None, mapping: Mapping | None = None,
                  date_format: str | None = None) -> ImportResult:
    """Write the import, or refuse and write nothing.

    All of it runs in one write transaction, so the plan is recomputed from the balances as they are while the write lock is
    held. The import is refused with StaleImport unless the rows and policy are the ones that were reviewed and every date in
    the file is still as the review recorded it. A closed or deleted account, or a duplicate date, is refused too. Whatever
    goes wrong part-way, nothing is saved. The header of the operation says which file, which settings and how many of each
    outcome, and never what was in the file."""
    with db.write_transaction(conn):
        plan = plan_import(conn, account_id, rows, policy)
        if plan.errors:
            raise ValidationError(f"The file has {len(plan.errors)} problem(s) that must be fixed first, starting at "
                                  f"record {plan.errors[0].record}.")
        if reviewed.fingerprint != plan.fingerprint:
            raise StaleImport("This is not the import that was reviewed: the file, the settings or the account changed. "
                              "Review it again before importing.")
        differing = _differing_dates(reviewed.expectations, plan.expectations)
        if differing:
            shown = ", ".join(differing[:10]) + (f" and {len(differing) - 10} more" if len(differing) > 10 else "")
            raise StaleImport(f"Balances changed since you reviewed this import ({shown}). Nothing was imported. "
                              "Review it again before importing.", differing)
        counts = plan.counts
        result = ImportResult(counts["add"], counts["replace"], counts["unchanged"], counts["skip"])
        written = [row for row in plan.rows if row.outcome in ("add", "replace")]
        if written:
            operation = Operation(conn, actor_id, "import", {
                "account_id": account_id, "file": _file_name(file_name), "policy": policy, "date_format": date_format,
                "mapping": None if mapping is None else mapping.used(),
                "counts": {"added": result.added, "updated": result.updated, "unchanged": result.unchanged,
                           "skipped": result.skipped}})
            for row in written:
                if row.outcome == "add":
                    writer.insert(operation, "balances", {
                        "account_id": account_id, "as_of_date": row.date.isoformat(), "amount_cents": row.cents,
                        "note": row.note, "source": SOURCE})
                else:
                    writer.update(operation, "balances", row.balance_id, {
                        "amount_cents": row.cents, "note": row.result_note, "source": SOURCE})
        return result
