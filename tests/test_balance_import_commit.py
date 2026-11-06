"""The import commit: it writes what was reviewed, or refuses and writes nothing. Synthetic data only."""

import json
from datetime import date

import pytest

from northstar import accounts, balance_import, balances, networth, users, writer
from northstar.balance_import import (Expectation, ImportResult, Reviewed, StaleImport, commit_import, fingerprint_of,
                                      plan_import)
from northstar.csvparse import Mapping, ParsedRow
from northstar.errors import NotFoundError, ValidationError

from conftest import add_account, add_balance, op

TODAY = date(2026, 10, 30)
ASSET, LIABILITY = 1, 2


def row(record, day, cents, note=None):
    return ParsedRow(record, date.fromisoformat(day), cents, note)


def save(conn, account_id, day, cents, note=None):
    balances.record_balance(op(conn), account_id, date.fromisoformat(day), cents, note)


def state(conn):
    """Everything an import could touch, to show that a refused one touched nothing."""
    return ([tuple(r) for r in conn.execute("SELECT * FROM balances ORDER BY id")],
            [tuple(r) for r in conn.execute("SELECT * FROM sys_operations ORDER BY id")],
            [tuple(r) for r in conn.execute("SELECT * FROM sys_record_changes ORDER BY id")])


def review(conn, account, rows, policy="skip"):
    return plan_import(conn, account, rows, policy).reviewed


def go(conn, account, rows, policy="skip", reviewed=None, actor=None, **kw):
    return commit_import(conn, actor, account, rows, policy, reviewed or review(conn, account, rows, policy), **kw)


def header_and_changes(conn):
    """The import's one header and its change rows, leaving out whatever the test did to set up."""
    [header] = [dict(r) for r in conn.execute("SELECT * FROM sys_operations WHERE kind = 'import'")]
    changes = [dict(r) | {"old": json.loads(r["old_json"]) if r["old_json"] else None,
                          "new": json.loads(r["new_json"]) if r["new_json"] else None}
               for r in conn.execute("SELECT * FROM sys_record_changes WHERE operation_id = ? ORDER BY id", (header["id"],))]
    return header, changes


@pytest.fixture
def account(conn):
    return add_account(conn, "Test account", ASSET, "Checking")


@pytest.fixture
def mixed(conn, account):
    """An account with a balance to leave unchanged (Jan), one the file disagrees with (Feb), and a date with none (Mar)."""
    save(conn, account, "2026-01-31", 100, "jan note")
    save(conn, account, "2026-02-28", 200, "feb note")
    rows = [row(2, "2026-01-31", 100), row(3, "2026-02-28", 999), row(4, "2026-03-31", 300, "new note")]
    return account, rows


# -- what is written --

def test_new_dates_are_added_as_csv_balances_in_one_operation(conn, account):
    rows = [row(2, "2026-01-31", 100, "a"), row(3, "2026-02-28", 200), row(4, "2026-03-31", -50)]
    assert go(conn, account, rows, actor=None, file_name="march.csv") == ImportResult(3, 0, 0, 0)
    header, changes = header_and_changes(conn)
    stored = conn.execute("SELECT * FROM balances ORDER BY as_of_date").fetchall()
    assert [(b["as_of_date"], b["amount_cents"], b["note"], b["source"]) for b in stored] == [
        ("2026-01-31", 100, "a", "csv"), ("2026-02-28", 200, None, "csv"), ("2026-03-31", -50, None, "csv")]
    assert {b["version"] for b in stored} == {header["id"]}                   # every balance shares the operation's id
    assert [(c["tablename"], c["change"], c["operation_id"]) for c in changes] == [("balances", "INSERT", header["id"])] * 3
    assert header["kind"] == "import" and header["user_id"] == conn.execute("SELECT id FROM users WHERE is_system = 1").fetchone()[0]


def test_the_signed_in_user_is_the_author(conn, account):
    person = users.create_user(op(conn), "p@example.com", "P", "synthetic-pass-123")
    go(conn, account, [row(2, "2026-01-31", 100)], actor=person)
    assert header_and_changes(conn)[0]["user_id"] == person
    assert conn.execute("SELECT created_by, updated_by FROM balances").fetchone()[:] == (person, person)


def test_replace_changes_only_what_differs_and_logs_the_old_and_new_values_including_the_source(conn, mixed):
    account, rows = mixed
    before_jan = tuple(conn.execute("SELECT * FROM balances WHERE as_of_date = '2026-01-31'").fetchone())
    assert go(conn, account, rows, "replace") == ImportResult(added=1, updated=1, unchanged=1, skipped=0)
    assert tuple(conn.execute("SELECT * FROM balances WHERE as_of_date = '2026-01-31'").fetchone()) == before_jan   # untouched
    header, changes = header_and_changes(conn)
    update = next(c for c in changes if c["change"] == "UPDATE")
    assert update["old"] == {"amount_cents": 200, "source": "manual"} and update["new"] == {"amount_cents": 999, "source": "csv"}
    feb = conn.execute("SELECT * FROM balances WHERE as_of_date = '2026-02-28'").fetchone()
    assert (feb["amount_cents"], feb["note"], feb["source"], feb["version"]) == (999, "feb note", "csv", header["id"])   # note kept
    assert len(changes) == 2                                                    # the add and the update, not the unchanged row


def test_skip_leaves_a_different_balance_alone(conn, mixed):
    account, rows = mixed
    assert go(conn, account, rows, "skip") == ImportResult(added=1, updated=0, unchanged=1, skipped=1)
    feb = conn.execute("SELECT amount_cents, source FROM balances WHERE as_of_date = '2026-02-28'").fetchone()
    assert (feb[0], feb[1]) == (200, "manual")


def test_a_replacement_with_a_note_changes_the_note_and_one_with_a_blank_note_never_clears_it(conn, account):
    save(conn, account, "2026-01-31", 100, "old one")
    save(conn, account, "2026-02-28", 200, "old two")
    go(conn, account, [row(2, "2026-01-31", 111, "new one"), row(3, "2026-02-28", 222, None)], "replace")
    notes = {b["as_of_date"]: b["note"] for b in conn.execute("SELECT * FROM balances")}
    assert notes == {"2026-01-31": "new one", "2026-02-28": "old two"}


def test_the_header_records_the_file_the_settings_and_the_counts_and_nothing_from_inside_the_file(conn, mixed):
    account, rows = mixed
    go(conn, account, rows, "replace", file_name="statements/2026 q1.csv", mapping=Mapping(date=0, balance=2, note=1),
       date_format="YYYY-MM-DD")
    header, _ = header_and_changes(conn)
    assert json.loads(header["detail"]) == {
        "account_id": account, "file": "2026 q1.csv", "policy": "replace", "date_format": "YYYY-MM-DD", "number_format": None, "mapping": {"date": 0, "balance": 2, "note": 1},
        "counts": {"added": 1, "updated": 1, "unchanged": 1, "skipped": 0}}
    assert "new note" not in header["detail"]


@pytest.mark.parametrize("given, kept", [
    ("C:\\Users\\me\\Documents\\bank statement.csv", "bank statement.csv"), ("../../etc/passwd", "passwd"),
    ("a\x00b\x07c.csv", "abc.csv"), ("x" * 400 + ".csv", ("x" * 400 + ".csv")[:255]), ("  spaced.csv  ", "spaced.csv"),
    ("", None), (None, None), ("folder/", None), ("\x00\x01", None),
])
def test_the_file_name_is_reduced_to_a_plain_base_name(conn, account, given, kept):
    go(conn, account, [row(2, "2026-01-31", 1)], file_name=given)
    assert json.loads(header_and_changes(conn)[0]["detail"])["file"] == kept


def test_written_balances_show_in_the_views_and_in_net_worth(conn, account):
    go(conn, account, [row(2, "2026-01-31", 10000), row(3, "2026-02-28", 25000)])
    assert networth.net_worth_on(conn, TODAY)["net_worth"] == 25000
    assert [r["last_cents"] for r in accounts.account_rows(conn, TODAY)] == [25000]


def test_nothing_to_write_writes_nothing_not_even_a_header(conn, account):
    save(conn, account, "2026-01-31", 100, "n")
    before = state(conn)
    rows = [row(2, "2026-01-31", 100)]
    assert go(conn, account, rows) == ImportResult(0, 0, 1, 0)
    assert state(conn) == before
    skipped = [row(2, "2026-01-31", 999)]
    assert go(conn, account, skipped, "skip") == ImportResult(0, 0, 0, 1) and state(conn) == before


# -- refusing: the account changed since the review --

def one_of(conn, day):
    return conn.execute("SELECT id FROM balances WHERE as_of_date = ?", (day,)).fetchone()[0]


MUTATIONS = {
    "an empty date was filled": (lambda conn, a: save(conn, a, "2026-03-31", 5), ["2026-03-31"]),
    "a balance that would be skipped was edited": (lambda conn, a: save(conn, a, "2026-02-28", 201), ["2026-02-28"]),
    "a balance that was unchanged was edited": (lambda conn, a: save(conn, a, "2026-01-31", 150), ["2026-01-31"]),
    "a balance had only its note edited": (lambda conn, a: save(conn, a, "2026-01-31", 100, "other note"), ["2026-01-31"]),
    "a balance was deleted": (lambda conn, a: balances.delete_balance(op(conn), one_of(conn, "2026-02-28")), ["2026-02-28"]),
    "a balance was deleted and the same amount entered again": (
        lambda conn, a: (balances.delete_balance(op(conn), one_of(conn, "2026-01-31")), save(conn, a, "2026-01-31", 100, "jan note")),
        ["2026-01-31"]),
}


@pytest.mark.parametrize("name", MUTATIONS)
def test_a_change_to_any_date_in_the_file_after_the_review_refuses_the_import_and_writes_nothing(conn, mixed, name):
    account, rows = mixed
    reviewed = review(conn, account, rows, "replace")
    mutate, dates = MUTATIONS[name]
    mutate(conn, account)
    before = state(conn)
    with pytest.raises(StaleImport, match="Review it again") as refused:
        commit_import(conn, None, account, rows, "replace", reviewed)
    assert refused.value.dates == dates
    assert state(conn) == before and not conn.in_transaction


def test_a_change_to_a_date_that_is_not_in_the_file_does_not_matter(conn, mixed):
    account, rows = mixed
    reviewed = review(conn, account, rows)
    save(conn, account, "2026-04-30", 77)
    assert go(conn, account, rows, reviewed=reviewed).added == 1


def test_balances_that_share_a_version_are_told_apart(conn, account):
    """An import writes several balances under one operation id. Editing one of them changes only that date's expectation."""
    go(conn, account, [row(2, "2026-01-31", 1), row(3, "2026-02-28", 2), row(4, "2026-03-31", 3)])
    versions = {r[0] for r in conn.execute("SELECT version FROM balances")}
    assert len(versions) == 1                                                      # all three share it
    rows = [row(2, "2026-01-31", 1), row(3, "2026-02-28", 2), row(4, "2026-03-31", 3)]
    reviewed = review(conn, account, rows)
    save(conn, account, "2026-02-28", 99)
    with pytest.raises(StaleImport) as refused:
        commit_import(conn, None, account, rows, "skip", reviewed)
    assert refused.value.dates == ["2026-02-28"]


def test_a_forged_or_incomplete_review_can_only_make_the_commit_refuse(conn, mixed):
    account, rows = mixed
    good = review(conn, account, rows)
    forged = {
        "empty": Reviewed([], good.fingerprint),
        "a date missing": Reviewed(good.expectations[1:], good.fingerprint),
        "an extra date": Reviewed(good.expectations + [Expectation("2027-01-01", None, None)], good.fingerprint),
        "a wrong version": Reviewed([Expectation(e.date, e.balance_id, (e.version or 0) + 1) if e.balance_id else e
                                     for e in good.expectations], good.fingerprint),
        "pretending a date is empty": Reviewed([Expectation(e.date, None, None) for e in good.expectations], good.fingerprint),
    }
    before = state(conn)
    for name, reviewed in forged.items():
        with pytest.raises(StaleImport):
            commit_import(conn, None, account, rows, "skip", reviewed)
        assert state(conn) == before, name


def test_the_message_lists_at_most_ten_dates(conn, account):
    rows = [row(n + 2, f"2026-01-{n + 1:02d}", n) for n in range(15)]
    reviewed = review(conn, account, rows)
    for n in range(15):
        save(conn, account, f"2026-01-{n + 1:02d}", 999)
    with pytest.raises(StaleImport, match=r"and 5 more") as refused:
        commit_import(conn, None, account, rows, "skip", reviewed)
    assert len(refused.value.dates) == 15


# -- refusing: this is not what was reviewed --

@pytest.mark.parametrize("name, change", [
    ("an amount", lambda rows: [rows[0], row(3, "2026-02-28", 998), rows[2]]),
    ("a note", lambda rows: [rows[0], rows[1], row(4, "2026-03-31", 300, "different")]),
    ("an extra row", lambda rows: rows + [row(5, "2026-04-30", 1)]),
    ("a missing row", lambda rows: rows[:2]),
    ("the order", lambda rows: list(reversed(rows))),
    ("a record number", lambda rows: [row(9, "2026-01-31", 100), rows[1], rows[2]]),
])
def test_different_rows_than_the_ones_reviewed_are_refused_even_when_the_dates_are_the_same(conn, mixed, name, change):
    account, rows = mixed
    reviewed = review(conn, account, rows)
    before = state(conn)
    with pytest.raises(StaleImport, match="not the import that was reviewed") as refused:
        commit_import(conn, None, account, change(rows), "skip", reviewed)
    assert refused.value.dates == [] and state(conn) == before, name


def test_a_different_policy_or_account_than_the_one_reviewed_is_refused(conn, mixed):
    account, rows = mixed
    other = add_account(conn, "Test other", ASSET, "Savings")
    reviewed = review(conn, account, rows, "skip")
    before = state(conn)
    with pytest.raises(StaleImport, match="not the import that was reviewed"):
        commit_import(conn, None, account, rows, "replace", reviewed)
    with pytest.raises(StaleImport, match="not the import that was reviewed"):
        commit_import(conn, None, other, rows, "skip", reviewed)
    assert state(conn) == before


def test_the_fingerprint_depends_on_exactly_the_account_policy_and_rows():
    rows = [row(2, "2026-01-31", 100, "n"), row(3, "2026-02-28", 200)]
    base = fingerprint_of(1, "skip", rows)
    assert base == fingerprint_of(1, "skip", list(rows)) and len(base) == 64
    assert len({base, fingerprint_of(2, "skip", rows), fingerprint_of(1, "replace", rows), fingerprint_of(1, "skip", rows[:1])}) == 4


# -- refusing: the account or the file --

def test_closing_or_deleting_the_account_after_the_review_stops_the_import(conn, mixed):
    account, rows = mixed
    reviewed = review(conn, account, rows)
    balances_before = state(conn)
    conn.execute("UPDATE accounts SET is_open = 0 WHERE id = ?", (account,))
    with pytest.raises(ValidationError, match="is closed"):
        commit_import(conn, None, account, rows, "skip", reviewed)
    conn.execute("UPDATE accounts SET is_open = 1, deleted = 1 WHERE id = ?", (account,))
    with pytest.raises(NotFoundError):
        commit_import(conn, None, account, rows, "skip", reviewed)
    conn.execute("UPDATE accounts SET deleted = 0 WHERE id = ?", (account,))
    assert state(conn) == balances_before


def test_duplicate_dates_in_the_file_fail_before_any_write(conn, account):
    rows = [row(2, "2026-01-31", 1), row(3, "2026-02-28", 2), row(4, "2026-01-31", 3)]
    plan = plan_import(conn, account, rows)
    before = state(conn)
    with pytest.raises(ValidationError, match="2 problem"):
        commit_import(conn, None, account, rows, "skip", plan.reviewed)
    assert state(conn) == before


def test_an_unknown_policy_is_refused(conn, account):
    with pytest.raises(ValidationError, match="skip or replace"):
        commit_import(conn, None, account, [row(2, "2026-01-31", 1)], "overwrite", Reviewed([], ""))


def test_submitting_the_same_review_twice_cannot_import_twice(conn, account):
    rows = [row(2, "2026-01-31", 100), row(3, "2026-02-28", 200)]
    reviewed = review(conn, account, rows)
    assert go(conn, account, rows, reviewed=reviewed).added == 2
    after_first = state(conn)
    with pytest.raises(StaleImport):
        commit_import(conn, None, account, rows, "skip", reviewed)
    assert state(conn) == after_first and conn.execute("SELECT COUNT(*) FROM sys_operations").fetchone()[0] == 1


def test_submitting_twice_when_there_was_nothing_to_write_is_harmless(conn, account):
    save(conn, account, "2026-01-31", 100)
    rows = [row(2, "2026-01-31", 100)]
    reviewed = review(conn, account, rows)
    before = state(conn)
    assert go(conn, account, rows, reviewed=reviewed) == go(conn, account, rows, reviewed=reviewed)
    assert state(conn) == before


# -- all or nothing, and the lock --

def test_a_failure_part_way_saves_nothing(conn, account, monkeypatch):
    rows = [row(n + 2, f"2026-01-{n + 1:02d}", n) for n in range(5)]
    reviewed = review(conn, account, rows)
    before = state(conn)
    real, calls = writer.insert, []

    def fails_on_the_third(*args, **kwargs):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("the disk filled up")
        return real(*args, **kwargs)

    monkeypatch.setattr(writer, "insert", fails_on_the_third)
    with pytest.raises(RuntimeError, match="disk filled"):
        commit_import(conn, None, account, rows, "skip", reviewed)
    assert state(conn) == before and not conn.in_transaction and len(calls) == 3


def test_the_check_and_the_writes_share_one_transaction_taken_up_front(conn, account):
    statements = []

    class Recorder:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *args):
            statements.append(sql.strip())
            return self._inner.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    rows = [row(2, "2026-01-31", 100)]
    reviewed = review(conn, account, rows)
    commit_import(Recorder(conn), None, account, rows, "skip", reviewed)
    assert statements[0] == "BEGIN IMMEDIATE" and statements[-1] == "COMMIT"
    assert statements.count("BEGIN IMMEDIATE") == 1


def test_a_file_of_twenty_thousand_rows_is_imported_in_one_commit(conn, account):
    days = [date.fromordinal(date(1960, 1, 1).toordinal() + n) for n in range(20_000)]
    rows = [ParsedRow(n + 2, day, n, None) for n, day in enumerate(days)]
    result = go(conn, account, rows)
    assert result.added == 20_000
    assert conn.execute("SELECT COUNT(*) FROM balances").fetchone()[0] == 20_000
    assert conn.execute("SELECT COUNT(*) FROM sys_operations").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sys_record_changes").fetchone()[0] == 20_000
