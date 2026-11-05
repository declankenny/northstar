"""The import dry run: what an import would do, and what the account looked like when it said so. Synthetic data only."""

from datetime import date

import pytest

from northstar import accounts, balance_import, balances, writer
from northstar.balance_import import Expectation, plan_import, expectations_for
from northstar.csvparse import ParsedRow
from northstar.errors import NotFoundError, ValidationError

from conftest import add_account, add_balance, op

ASSET, LIABILITY = 1, 2


def row(record, day, cents, note=None):
    return ParsedRow(record, date.fromisoformat(day), cents, note)


@pytest.fixture
def account(conn):
    return add_account(conn, "Test account", ASSET, "Checking")


def save(conn, account_id, day, cents, note=None):
    """A balance made the normal way, so it carries a version."""
    balances.record_balance(op(conn), account_id, date.fromisoformat(day), cents, note)


# -- what each row would do --

def test_a_date_with_no_balance_is_an_add(conn, account):
    plan = plan_import(conn, account, [row(2, "2026-01-31", 10000, "first")])
    [planned] = plan.rows
    assert (planned.outcome, planned.cents, planned.note, planned.old_cents, planned.old_note, planned.result_note) == (
        "add", 10000, "first", None, None, "first")
    assert plan.counts == {"add": 1, "replace": 0, "unchanged": 0, "skip": 0} and plan.can_commit and plan.errors == []


@pytest.mark.parametrize("policy, outcome", [("skip", "skip"), ("replace", "replace")])
def test_a_date_with_a_different_amount_is_skipped_or_replaced_by_the_policy(conn, account, policy, outcome):
    save(conn, account, "2026-01-31", 10000, "keep me")
    [planned] = plan_import(conn, account, [row(2, "2026-01-31", 15000)], policy).rows
    assert planned.outcome == outcome and (planned.old_cents, planned.old_note, planned.cents) == (10000, "keep me", 15000)


def test_skip_is_the_default_policy(conn, account):
    save(conn, account, "2026-01-31", 10000)
    assert plan_import(conn, account, [row(2, "2026-01-31", 15000)]).policy == "skip"
    assert plan_import(conn, account, [row(2, "2026-01-31", 15000)]).rows[0].outcome == "skip"


@pytest.mark.parametrize("policy", ["skip", "replace"])
def test_an_identical_row_is_unchanged_whatever_the_policy(conn, account, policy):
    save(conn, account, "2026-01-31", 10000, "same note")
    for file_note in (None, "same note"):            # a blank note keeps the existing one, so it is never a difference
        [planned] = plan_import(conn, account, [row(2, "2026-01-31", 10000, file_note)], policy).rows
        assert planned.outcome == "unchanged" and planned.result_note == "same note"


@pytest.mark.parametrize("policy, outcome", [("skip", "skip"), ("replace", "replace")])
def test_the_same_amount_with_a_different_note_is_a_difference(conn, account, policy, outcome):
    save(conn, account, "2026-01-31", 10000, "old note")
    [planned] = plan_import(conn, account, [row(2, "2026-01-31", 10000, "new note")], policy).rows
    assert planned.outcome == outcome
    assert planned.result_note == ("new note" if outcome == "replace" else "old note")


def test_a_replacement_with_a_blank_note_keeps_the_existing_note_and_one_with_a_note_changes_it(conn, account):
    save(conn, account, "2026-01-31", 10000, "old note")
    save(conn, account, "2026-02-28", 20000, "other note")
    plan = plan_import(conn, account, [row(2, "2026-01-31", 11111), row(3, "2026-02-28", 22222, "new")], "replace")
    assert [(r.outcome, r.result_note) for r in plan.rows] == [("replace", "old note"), ("replace", "new")]


def test_an_import_can_never_clear_a_note(conn, account):
    save(conn, account, "2026-01-31", 10000, "precious")
    assert plan_import(conn, account, [row(2, "2026-01-31", 99, None)], "replace").rows[0].result_note == "precious"


def test_a_zero_and_a_negative_amount_are_ordinary(conn, account):
    save(conn, account, "2026-01-31", -500)
    plan = plan_import(conn, account, [row(2, "2026-01-31", -500), row(3, "2026-02-28", 0), row(4, "2026-03-31", -1)])
    assert [r.outcome for r in plan.rows] == ["unchanged", "add", "add"]


def test_the_counts_add_up_to_the_number_of_rows(conn, account):
    save(conn, account, "2026-01-31", 100)
    save(conn, account, "2026-02-28", 200)
    save(conn, account, "2026-03-31", 300)
    plan = plan_import(conn, account, [row(2, "2026-01-31", 100), row(3, "2026-02-28", 999), row(4, "2026-03-31", 999),
                                       row(5, "2026-04-30", 400), row(6, "2026-05-31", 500)], "replace")
    assert plan.counts == {"add": 2, "replace": 2, "unchanged": 1, "skip": 0} and sum(plan.counts.values()) == len(plan.rows)


def test_an_unknown_policy_is_refused(conn, account):
    with pytest.raises(ValidationError, match="skip or replace"):
        plan_import(conn, account, [row(2, "2026-01-31", 1)], "overwrite")


# -- duplicate dates in the file --

def test_every_record_with_a_shared_date_is_an_error_naming_the_others(conn, account):
    plan = plan_import(conn, account, [row(2, "2026-01-31", 1), row(3, "2026-02-28", 2), row(4, "2026-01-31", 3)])
    assert [(e.record, e.message) for e in plan.errors] == [
        (2, "Records 2 and 4 all have the date Jan 31, 2026. Each date may appear once in the file."),
        (4, "Records 2 and 4 all have the date Jan 31, 2026. Each date may appear once in the file.")]
    assert not plan.can_commit and len(plan.rows) == 3                          # the rows are still classified for the screen


def test_identical_rows_are_duplicates_too(conn, account):
    plan = plan_import(conn, account, [row(2, "2026-01-31", 500), row(3, "2026-01-31", 500)])
    assert [e.record for e in plan.errors] == [2, 3]


def test_three_in_a_group_and_two_groups_are_each_named(conn, account):
    plan = plan_import(conn, account, [row(2, "2026-01-31", 1), row(3, "2026-01-31", 2), row(4, "2026-02-28", 3),
                                       row(5, "2026-01-31", 4), row(6, "2026-02-28", 5), row(7, "2026-03-31", 6)])
    assert [e.record for e in plan.errors] == [2, 3, 4, 5, 6]
    assert plan.errors[0].message.startswith("Records 2, 3 and 5 all have the date Jan 31, 2026")
    assert plan.errors[2].message.startswith("Records 4 and 6 all have the date Feb 28, 2026")


def test_distinct_dates_have_no_errors(conn, account):
    assert plan_import(conn, account, [row(2, "2026-01-31", 1), row(3, "2026-02-01", 1)]).errors == []


# -- the account --

def test_a_missing_deleted_or_closed_account_is_refused_before_anything_else(conn, account):
    with pytest.raises(NotFoundError):
        plan_import(conn, 9999, [row(2, "2026-01-31", 1)])
    accounts.close_account(op(conn), account)
    with pytest.raises(ValidationError, match="Test account is closed. Reopen it"):
        plan_import(conn, account, [row(2, "2026-01-31", 1)])
    accounts.reopen_account(op(conn), account)
    assert plan_import(conn, account, [row(2, "2026-01-31", 1)]).can_commit
    accounts.delete_account(op(conn), account)
    with pytest.raises(NotFoundError):
        plan_import(conn, account, [row(2, "2026-01-31", 1)])


def test_only_this_accounts_balances_are_compared(conn, account):
    other = add_account(conn, "Test other", LIABILITY, "Loan")
    save(conn, other, "2026-01-31", 7777)
    [planned] = plan_import(conn, account, [row(2, "2026-01-31", 100)]).rows
    assert planned.outcome == "add" and planned.old_cents is None


# -- the expected state of every date --

def test_a_date_with_no_balance_is_expected_absent_and_one_with_a_balance_by_its_id_and_version(conn, account):
    save(conn, account, "2026-02-28", 200)
    [existing_id, existing_version] = conn.execute("SELECT id, version FROM balances").fetchone()
    plan = plan_import(conn, account, [row(2, "2026-02-28", 999), row(3, "2026-01-31", 1)])
    assert plan.expectations == [Expectation("2026-01-31", None, None), Expectation("2026-02-28", existing_id, existing_version)]
    assert existing_version > 0


def test_a_balance_from_before_the_change_log_is_expected_at_version_zero(conn, account):
    add_balance(conn, account, "2026-01-31", 100)                  # written without the writer, as the upgrade left them
    [expected] = plan_import(conn, account, [row(2, "2026-01-31", 100)]).expectations
    assert expected.version == 0 and expected.balance_id is not None


def test_every_date_is_expected_not_only_the_ones_that_would_be_written(conn, account):
    save(conn, account, "2026-01-31", 100)           # unchanged
    save(conn, account, "2026-02-28", 200)           # skipped
    plan = plan_import(conn, account, [row(2, "2026-01-31", 100), row(3, "2026-02-28", 999), row(4, "2026-03-31", 300)])
    assert [r.outcome for r in plan.rows] == ["unchanged", "skip", "add"]
    assert [e.date for e in plan.expectations] == ["2026-01-31", "2026-02-28", "2026-03-31"]


def test_expectations_are_one_per_distinct_date_and_oldest_first(conn, account):
    plan = plan_import(conn, account, [row(2, "2026-03-31", 1), row(3, "2026-01-31", 2), row(4, "2026-03-31", 3)])
    assert [e.date for e in plan.expectations] == ["2026-01-31", "2026-03-31"]


def test_the_commit_uses_the_same_function_and_gets_the_same_answer(conn, account):
    save(conn, account, "2026-01-31", 100)
    rows = [row(2, "2026-01-31", 5), row(3, "2026-02-28", 6)]
    assert expectations_for(conn, account, [r.date for r in rows]) == plan_import(conn, account, rows).expectations


def test_any_change_to_a_date_in_the_file_changes_its_expectation(conn, account):
    save(conn, account, "2026-01-31", 100)
    save(conn, account, "2026-02-28", 200)
    rows = [row(2, "2026-01-31", 100), row(3, "2026-02-28", 999), row(4, "2026-03-31", 300)]
    before = plan_import(conn, account, rows).expectations
    days = [r.date for r in rows]
    assert expectations_for(conn, account, days) == before
    first = conn.execute("SELECT id FROM balances WHERE as_of_date = '2026-01-31'").fetchone()[0]
    changes = {
        "edited": lambda: save(conn, account, "2026-01-31", 101),                       # an unchanged date edited
        "skipped date deleted": lambda: balances.delete_balance(op(conn), conn.execute(
            "SELECT id FROM balances WHERE as_of_date = '2026-02-28'").fetchone()[0]),
        "empty date filled": lambda: save(conn, account, "2026-03-31", 5),
    }
    for name, change in changes.items():
        change()
        after = expectations_for(conn, account, days)
        assert after != before, name
        before = after
    assert first                                                                      # (the id was read before the edits)


def test_an_edit_that_changes_nothing_does_not_change_the_expectation(conn, account):
    save(conn, account, "2026-01-31", 100)
    before = expectations_for(conn, account, [date(2026, 1, 31)])
    save(conn, account, "2026-01-31", 100)                       # saving the same amount writes nothing
    assert expectations_for(conn, account, [date(2026, 1, 31)]) == before


# -- it only reads --

def test_the_dry_run_writes_nothing_at_all(conn, account, monkeypatch):
    save(conn, account, "2026-01-31", 100)

    def forbidden(*args, **kwargs):
        raise AssertionError("the dry run must not write")

    for name in ("insert", "update", "delete", "sys_insert", "sys_delete"):
        monkeypatch.setattr(writer, name, forbidden)
    snapshot = lambda: ([tuple(r) for r in conn.execute("SELECT * FROM balances")],
                        conn.execute("SELECT COUNT(*) FROM sys_operations").fetchone()[0])
    before = snapshot()
    plan_import(conn, account, [row(2, "2026-01-31", 999), row(3, "2026-02-28", 5)], "replace")
    assert snapshot() == before and not conn.in_transaction


def test_a_plan_for_the_largest_file_is_made_in_one_pass(conn, account):
    for month in range(1, 13):
        save(conn, account, f"2026-{month:02d}-28", month)
    days = [date.fromordinal(date(1960, 1, 1).toordinal() + n) for n in range(20_000)]
    plan = plan_import(conn, account, [ParsedRow(n + 2, day, n, None) for n, day in enumerate(days)])
    assert len(plan.rows) == len(plan.expectations) == 20_000 and plan.errors == []
    assert plan.counts["add"] == 20_000                          # none of those dates is one the account has
