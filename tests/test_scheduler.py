"""The in-app scheduler: when a job is due, the lock and its token, reconciliation, failures, leases, shutdown and the Time
property. Everything runs on a fake clock and a fake wait, so nothing sleeps. Synthetic data only.
See docs/design/scheduler/design.md."""

import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from northstar import db, scheduler, system_properties as sp, writer
from northstar.errors import ValidationError
from northstar.scheduler import (Env, InvalidResponse, Job, LostLease, Retryable, claim, finish, hold, reconcile, run_due,
                                 run_now, seed)
from northstar.web.app import create_app
from tests.conftest import op

UTC = timezone.utc
TIME_PROPERTY = "test.job.time"
SYSTEM_USER = "(SELECT id FROM users WHERE is_system = 1)"
DAY = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, at):
        self.at = at

    def __call__(self):
        return self.at

    def advance(self, seconds):
        self.at += timedelta(seconds=seconds)


def add_time(conn, value="04:00", name=TIME_PROPERTY):
    conn.execute(
        "INSERT INTO system_properties (name, data_type_id, value, allow_null, hint, created_by, updated_by) "
        f"VALUES (?, (SELECT id FROM ref_property_data_types WHERE name = 'Time'), ?, 1, 'A test time.', {SYSTEM_USER}, {SYSTEM_USER})",
        (name, value))


def job(name="test.job", **kw):
    return Job(name, Calls(), TIME_PROPERTY, **kw)


class Calls:
    """A job that records each time it ran."""
    def __init__(self):
        self.count = 0

    def __call__(self, ctx):
        self.count += 1


def make_env(conn, registry, clock, stop=None, on_wait=None):
    stop = stop or threading.Event()

    def wait(seconds):
        if on_wait:
            on_wait(seconds)
        clock.advance(seconds)
        return stop.is_set()
    return Env(conn, tuple(registry), now=clock, stop=stop, wait=wait)


def runs(conn, name="test.job"):
    return [dict(r) for r in conn.execute("SELECT * FROM sys_job_runs WHERE job = ? ORDER BY id", (name,))]


def lock(conn, name="test.job"):
    row = conn.execute("SELECT owner, lease_until FROM sys_jobs WHERE job = ?", (name,)).fetchone()
    return None if row is None else (row["owner"], row["lease_until"])


@pytest.fixture
def timed(conn):
    add_time(conn)
    return conn


def at(hour, minute=0, day=0):
    return DAY + timedelta(days=day, hours=hour, minutes=minute)


# -- when a job is due --

def test_a_job_is_not_due_before_its_time_and_is_due_at_it_and_after_it(timed):
    calls = Calls()
    clock = FakeClock(at(3, 59))
    env = make_env(timed, [Job("test.job", calls, TIME_PROPERTY)], clock)
    assert run_due(env) == [] and calls.count == 0
    clock.at = at(4, 0)
    assert run_due(env) == [("test.job", "succeeded")] and calls.count == 1


def test_a_job_runs_once_a_date_and_again_the_next_date(timed):
    calls = Calls()
    clock = FakeClock(at(4, 0))
    env = make_env(timed, [Job("test.job", calls, TIME_PROPERTY)], clock)
    run_due(env)
    clock.at = at(9, 0)
    assert run_due(env) == [] and calls.count == 1
    clock.at = at(4, 1, day=1)
    run_due(env)
    assert calls.count == 2
    assert [r["run_date"] for r in runs(timed)] == ["2026-06-01", "2026-06-02"]


def test_a_job_whose_time_is_not_set_is_not_scheduled(conn):
    add_time(conn, None)
    calls = Calls()
    assert run_due(make_env(conn, [Job("test.job", calls, TIME_PROPERTY)], FakeClock(at(12)))) == []
    assert calls.count == 0


def test_a_missed_time_is_made_up_once_at_the_next_tick(timed):
    calls = Calls()
    env = make_env(timed, [Job("test.job", calls, TIME_PROPERTY)], FakeClock(at(15, 30)))      # the app was down at 04:00
    run_due(env)
    run_due(env)
    assert calls.count == 1


def test_the_start_time_is_read_in_the_installation_zone_and_the_run_date_is_its_date(timed):
    sp.set_property(op(timed), "system.timezone", "America/Chicago")       # UTC-5 in June
    calls = Calls()
    clock = FakeClock(at(8, 59))             # 03:59 in Chicago
    env = make_env(timed, [Job("test.job", calls, TIME_PROPERTY)], clock)
    assert run_due(env) == []
    clock.at = at(9, 0)
    assert run_due(env) == [("test.job", "succeeded")]
    clock.at = at(2, 0, day=1)               # 21:00 on June 1 in Chicago, UTC date is already the 2nd
    assert run_due(env) == []
    assert runs(timed)[0]["run_date"] == "2026-06-01"


def test_a_start_time_that_does_not_exist_on_a_spring_forward_day_runs_once_when_the_clock_passes_it(timed):
    sp.set_property(op(timed), "system.timezone", "America/Chicago")
    timed.execute("UPDATE system_properties SET value = '02:30' WHERE name = ?", (TIME_PROPERTY,))
    calls = Calls()
    clock = FakeClock(datetime(2026, 3, 8, 7, 59, tzinfo=UTC))           # 01:59 CST, the next minute is 03:00 CDT
    env = make_env(timed, [Job("test.job", calls, TIME_PROPERTY)], clock)
    assert run_due(env) == [] and calls.count == 0
    clock.at = datetime(2026, 3, 8, 8, 0, tzinfo=UTC)
    run_due(env)
    clock.at = datetime(2026, 3, 8, 12, 0, tzinfo=UTC)
    run_due(env)
    assert calls.count == 1


def test_a_start_time_that_happens_twice_on_a_fall_back_day_runs_once(timed):
    sp.set_property(op(timed), "system.timezone", "America/Chicago")
    timed.execute("UPDATE system_properties SET value = '01:30' WHERE name = ?", (TIME_PROPERTY,))
    calls = Calls()
    clock = FakeClock(datetime(2026, 11, 1, 6, 30, tzinfo=UTC))          # 01:30 CDT, the first time
    env = make_env(timed, [Job("test.job", calls, TIME_PROPERTY)], clock)
    run_due(env)
    clock.at = datetime(2026, 11, 1, 7, 30, tzinfo=UTC)                  # 01:30 CST, the second time
    run_due(env)
    assert calls.count == 1


# -- the claim and the lock --

def test_the_unique_index_refuses_a_second_scheduled_run_for_a_date_and_frees_the_lock(timed):
    seed(timed, (job(),))
    first = claim(timed, "test.job", "2026-06-01", "scheduled", at(4))
    assert first is not None
    finish(timed, "test.job", first[0], first[1], "succeeded", "Done.", at(4, 1))
    assert claim(timed, "test.job", "2026-06-01", "scheduled", at(5)) is None
    assert lock(timed) == (None, None)
    assert claim(timed, "test.job", "2026-06-02", "scheduled", at(5)) is not None


def test_every_acquisition_gets_a_new_token(timed):
    seed(timed, (job(),))
    first = claim(timed, "test.job", "2026-06-01", "scheduled", at(4))
    finish(timed, "test.job", first[0], first[1], "succeeded", "Done.", at(4, 1))
    second = claim(timed, "test.job", "2026-06-02", "scheduled", at(4))
    assert first[0] != second[0] and len(second[0]) == 32


def test_simultaneous_scheduled_claims_give_one_run(timed, tmp_path):
    seed(timed, (job(),))
    results, barrier = [], threading.Barrier(6)

    def attempt():
        conn = db.connect(tmp_path / "test.db")
        try:
            barrier.wait()
            results.append(claim(conn, "test.job", "2026-06-01", "scheduled", at(4)))
        finally:
            conn.close()
    threads = [threading.Thread(target=attempt) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len([r for r in results if r is not None]) == 1
    assert len(runs(timed)) == 1


def test_a_manual_claim_and_a_scheduled_claim_at_the_same_moment_give_one_run_and_manual_does_not_count_as_scheduled(timed):
    seed(timed, (job(),))
    manual = claim(timed, "test.job", "2026-06-01", "manual", at(4))
    assert manual is not None
    assert claim(timed, "test.job", "2026-06-01", "scheduled", at(4)) is None          # the lock is held
    finish(timed, "test.job", manual[0], manual[1], "succeeded", "Done.", at(4, 1))
    assert claim(timed, "test.job", "2026-06-01", "scheduled", at(4, 2)) is not None   # the manual run did not use the date


def test_two_manual_claims_are_refused_while_one_is_running_and_allowed_after(timed):
    seed(timed, (job(),))
    first = claim(timed, "test.job", "2026-06-01", "manual", at(4))
    assert claim(timed, "test.job", "2026-06-01", "manual", at(4)) is None
    finish(timed, "test.job", first[0], first[1], "succeeded", "Done.", at(4, 1))
    assert claim(timed, "test.job", "2026-06-01", "manual", at(4, 2)) is not None


def test_a_live_run_that_crosses_midnight_blocks_the_next_date_until_it_ends(timed):
    timed.execute("UPDATE system_properties SET value = '00:00' WHERE name = ?", (TIME_PROPERTY,))
    j = job()
    calls = Calls()
    other = Job("test.job", calls, TIME_PROPERTY)
    seed(timed, (j,))
    live = claim(timed, "test.job", "2026-06-01", "scheduled", at(23, 58))
    clock = FakeClock(at(0, 2, day=1))
    env = make_env(timed, [other], clock)
    # the run is live: a worker renews its lease, so the lock is still held at 00:02
    hold(timed, "test.job", live[0], at(0, 1, day=1))
    assert run_due(env) == [] and calls.count == 0
    finish(timed, "test.job", live[0], live[1], "succeeded", "Done.", clock())
    clock.advance(60)
    assert run_due(env) == [("test.job", "succeeded")]
    assert [r["run_date"] for r in runs(timed)] == ["2026-06-01", "2026-06-02"]


def test_a_crashed_run_is_marked_abandoned_and_does_not_block_tomorrow_but_keeps_todays_claim(timed):
    calls = Calls()
    j = Job("test.job", calls, TIME_PROPERTY)
    seed(timed, (j,))
    claim(timed, "test.job", "2026-06-01", "scheduled", at(4))             # then the process died: no renewal, no finish
    clock = FakeClock(at(4, 4))
    env = make_env(timed, [j], clock)
    run_due(env)
    assert runs(timed)[0]["outcome"] == "running" and lock(timed)[0] is not None      # lease (5 minutes) not over yet
    clock.at = at(4, 6)
    assert run_due(env) == []                      # reconciled, but today's scheduled claim stays used
    assert runs(timed)[0]["outcome"] == "abandoned" and runs(timed)[0]["finished_at"] == "2026-06-01T04:06:00Z"
    assert lock(timed) == (None, None) and calls.count == 0
    clock.at = at(4, 0, day=1)
    assert run_due(env) == [("test.job", "succeeded")]


# -- ownership: a stale owner cannot commit --

def test_an_old_owner_that_resumes_after_takeover_cannot_commit_or_close_the_run_and_the_new_owners_rows_are_untouched(timed):
    j = job()
    seed(timed, (j,))
    old = claim(timed, "test.job", "2026-06-01", "scheduled", at(4))
    reconcile(timed, at(4, 6))                                                    # the lease ran out and was cleared
    new = claim(timed, "test.job", "2026-06-01", "manual", at(4, 7))
    assert new is not None and new[0] != old[0]
    with pytest.raises(LostLease):
        hold(timed, "test.job", old[0], at(4, 8))
    with pytest.raises(LostLease):
        finish(timed, "test.job", old[0], old[1], "succeeded", "Stale.", at(4, 8))
    # a batch of the old owner's is rolled back whole
    ctx = scheduler.JobContext(make_env(timed, [j], FakeClock(at(4, 8))), j, old[0], old[1], at(4, 10))
    with pytest.raises(LostLease):
        ctx.commit(lambda conn: writer.sys_insert(conn, "sys_login_attempts", {"email_hash": "x", "address_hash": None, "attempted_at": "2026-06-01T04:08:00Z"}))
    assert timed.execute("SELECT COUNT(*) FROM sys_login_attempts").fetchone()[0] == 0
    assert lock(timed)[0] == new[0]
    assert [r["outcome"] for r in runs(timed)] == ["abandoned", "running"]


def test_a_lease_that_has_passed_but_was_not_reconciled_still_refuses_the_commit(timed):
    seed(timed, (job(),))
    mine = claim(timed, "test.job", "2026-06-01", "scheduled", at(4))
    with pytest.raises(LostLease):
        finish(timed, "test.job", mine[0], mine[1], "succeeded", "Late.", at(4, 6))
    assert runs(timed)[0]["outcome"] == "running"


def test_closing_with_the_wrong_token_changes_nothing(timed):
    seed(timed, (job(),))
    mine = claim(timed, "test.job", "2026-06-01", "scheduled", at(4))
    with pytest.raises(LostLease):
        finish(timed, "test.job", "f" * 32, mine[1], "succeeded", "Wrong.", at(4, 1))
    assert runs(timed)[0]["outcome"] == "running" and lock(timed)[0] == mine[0]


def test_a_commit_made_while_the_lock_is_held_lands_and_renews_the_lease(timed):
    j = job()
    seed(timed, (j,))
    mine = claim(timed, "test.job", "2026-06-01", "scheduled", at(4))
    ctx = scheduler.JobContext(make_env(timed, [j], FakeClock(at(4, 3))), j, mine[0], mine[1], mine[2])
    ctx.commit(lambda conn: writer.sys_insert(conn, "sys_login_attempts", {"email_hash": "x", "address_hash": None, "attempted_at": "2026-06-01T04:03:00Z"}))
    assert timed.execute("SELECT COUNT(*) FROM sys_login_attempts").fetchone()[0] == 1
    assert lock(timed)[1] == "2026-06-01T04:08:00Z"


# -- reconciliation --

def test_reconciliation_clears_expired_locks_including_jobs_no_longer_registered_and_leaves_a_live_lease_alone(timed):
    seed(timed, (job(name="live.job"), job(name="dead.job"), job(name="gone.job")))
    live = claim(timed, "live.job", "2026-06-01", "scheduled", at(4, 4))
    claim(timed, "dead.job", "2026-06-01", "scheduled", at(4))
    claim(timed, "gone.job", "2026-06-01", "scheduled", at(4))
    assert sorted(reconcile(timed, at(4, 6))) == ["dead.job", "gone.job"]
    assert lock(timed, "live.job")[0] == live[0] and runs(timed, "live.job")[0]["outcome"] == "running"
    assert [runs(timed, n)[0]["outcome"] for n in ("dead.job", "gone.job")] == ["abandoned", "abandoned"]


def test_the_first_tick_after_a_restart_reconciles_what_the_dead_process_left(timed):
    j = job()
    seed(timed, (j,))
    claim(timed, "test.job", "2026-06-01", "scheduled", at(4))
    run_due(make_env(timed, [Job("other.job", Calls(), TIME_PROPERTY)], FakeClock(at(5))))      # a new process, a fresh Env
    assert runs(timed)[0]["outcome"] == "abandoned"


def test_seeding_adds_a_row_for_each_registered_job_and_keeps_the_rest(timed):
    seed(timed, (job(name="a.job"),))
    seed(timed, (job(name="a.job"), job(name="b.job")))
    assert [r[0] for r in timed.execute("SELECT job FROM sys_jobs ORDER BY job")] == ["a.job", "b.job"]
    seed(timed, ())
    assert timed.execute("SELECT COUNT(*) FROM sys_jobs").fetchone()[0] == 2


# -- two jobs in one tick --

def test_the_second_job_is_judged_on_the_new_date_when_the_first_crosses_midnight(conn):
    add_time(conn, "00:05")
    clock = FakeClock(at(23, 50))

    def slow(ctx):
        clock.advance(20 * 60)               # the first job runs past midnight
    second = Calls()
    env = make_env(conn, [Job("first.job", slow, TIME_PROPERTY), Job("second.job", second, TIME_PROPERTY)], clock)
    assert run_due(env) == [("first.job", "succeeded"), ("second.job", "succeeded")]
    assert runs(conn, "first.job")[0]["run_date"] == "2026-06-01"
    assert runs(conn, "second.job")[0]["run_date"] == "2026-06-02"


# -- failures --

def test_a_failing_job_is_recorded_and_the_next_job_still_runs(timed, caplog):
    def broken(ctx):
        raise InvalidResponse("The provider sent a rate that is not a number.")
    second = Calls()
    env = make_env(timed, [Job("first.job", broken, TIME_PROPERTY), Job("second.job", second, TIME_PROPERTY)], FakeClock(at(5)))
    assert run_due(env) == [("first.job", "failed"), ("second.job", "succeeded")]
    row = runs(timed, "first.job")[0]
    assert row["outcome"] == "failed" and row["detail"] == "Invalid response: The provider sent a rate that is not a number."
    assert row["finished_at"] and lock(timed, "first.job") == (None, None)


def test_a_retryable_failure_is_retried_with_growing_pauses_and_gives_up_after_the_limit(timed):
    tries, pauses = [], []

    def flaky(ctx):
        tries.append(ctx.now())
        raise Retryable("The provider did not answer.")
    clock = FakeClock(at(5))
    env = make_env(timed, [Job("test.job", flaky, TIME_PROPERTY)], clock, on_wait=pauses.append)
    assert run_due(env) == [("test.job", "failed")]
    assert len(tries) == 4 and sum(pauses) == 30 + 120 + 300
    assert runs(timed)[0]["detail"] == "Could not complete: Gave up after 4 tries: The provider did not answer."


def test_a_retryable_failure_that_clears_succeeds(timed):
    count = []

    def flaky(ctx):
        count.append(1)
        if len(count) < 3:
            raise Retryable("Busy.")
    assert run_due(make_env(timed, [Job("test.job", flaky, TIME_PROPERTY)], FakeClock(at(5)))) == [("test.job", "succeeded")]
    assert len(count) == 3


def test_a_failure_that_is_not_retryable_is_tried_once(timed):
    count = []

    def invalid(ctx):
        count.append(1)
        raise InvalidResponse("Bad.")
    run_due(make_env(timed, [Job("test.job", invalid, TIME_PROPERTY)], FakeClock(at(5))))
    assert count == [1]


def test_a_job_past_its_deadline_is_recorded_as_timed_out(timed):
    def slow(ctx):
        ctx.pause(1000)
    env = make_env(timed, [Job("test.job", slow, TIME_PROPERTY, deadline_seconds=100)], FakeClock(at(5)))
    run_due(env)
    assert runs(timed)[0]["outcome"] == "failed" and runs(timed)[0]["detail"].startswith("Timed out")


def test_an_unexpected_exception_is_recorded_by_class_and_place_never_by_its_text(timed, caplog):
    secret = "https://user:hunter2@feed.example.com/path?token=abc123"

    def explode(ctx):
        raise KeyError(f"cannot fetch {secret}")
    with caplog.at_level(logging.DEBUG):
        run_due(make_env(timed, [Job("test.job", explode, TIME_PROPERTY)], FakeClock(at(5))))
    detail = runs(timed)[0]["detail"]
    assert detail.startswith("Unexpected KeyError at test_scheduler.py:")
    for text in (detail, caplog.text):
        assert "hunter2" not in text and "abc123" not in text and "feed.example.com" not in text


def test_a_message_a_job_writes_loses_any_link_and_is_cut_short(timed):
    def noisy(ctx):
        raise Retryable("Failed at https://user:hunter2@feed.example.com/x " + "long " * 100)
    run_due(make_env(timed, [Job("test.job", noisy, TIME_PROPERTY, retry_pauses=())], FakeClock(at(5))))
    detail = runs(timed)[0]["detail"]
    assert "hunter2" not in detail and "[link removed]" in detail and len(detail) <= scheduler.DETAIL_MAX


def test_a_job_that_worked_but_whose_outcome_cannot_be_written_is_abandoned_once_its_lease_runs_out(timed, monkeypatch, caplog):
    attempts = []

    def broken_finish(*args, **kwargs):
        attempts.append(1)
        raise sqlite3.OperationalError("disk I/O error at /secret/path")
    monkeypatch.setattr(scheduler, "finish", broken_finish)
    j = Job("test.job", Calls(), TIME_PROPERTY)
    clock = FakeClock(at(5))
    env = make_env(timed, [j], clock)
    with caplog.at_level(logging.DEBUG):
        run_due(env)
    assert len(attempts) == scheduler.RECORD_ATTEMPTS
    assert runs(timed)[0]["outcome"] == "running" and lock(timed)[0] is not None
    assert "/secret/path" not in caplog.text
    monkeypatch.undo()
    clock.advance(scheduler.LEASE_SECONDS + 60)
    run_due(env)
    assert runs(timed)[0]["outcome"] == "abandoned" and lock(timed) == (None, None)


def test_a_failure_judging_one_job_does_not_stop_the_others(timed):
    second = Calls()
    missing = Job("first.job", Calls(), "test.no_such_property")
    env = make_env(timed, [missing, Job("second.job", second, TIME_PROPERTY)], FakeClock(at(5)))
    assert run_due(env) == [("second.job", "succeeded")]
    assert env.errors.seen


def test_old_finished_runs_are_deleted_and_a_running_one_is_kept(timed):
    seed(timed, (job(),))
    for stamp_, outcome in (("2026-01-01T00:00:00Z", "succeeded"), ("2026-02-15T00:00:00Z", "failed"),
                            ("2026-02-15T00:00:00Z", "running"), ("2026-05-30T00:00:00Z", "succeeded")):
        timed.execute("INSERT INTO sys_job_runs (job, run_date, started_by, started_at, finished_at, outcome) "
                      "VALUES ('test.job', ?, 'manual', ?, ?, ?)",
                      (stamp_[:10], stamp_, None if outcome == "running" else stamp_, outcome))
    assert scheduler.prune(timed, datetime(2026, 6, 1, tzinfo=UTC)) == 2
    assert [(r["started_at"], r["outcome"]) for r in runs(timed)] == [
        ("2026-02-15T00:00:00Z", "running"), ("2026-05-30T00:00:00Z", "succeeded")]


# -- leases during waits and calls --

def test_a_backoff_longer_than_the_lease_is_sliced_and_renewed_so_a_healthy_run_is_not_abandoned(timed):
    count = []

    def flaky(ctx):
        count.append(1)
        if len(count) == 1:
            raise Retryable("Busy.")
    j = Job("test.job", flaky, TIME_PROPERTY, retry_pauses=(500,), deadline_seconds=3000)
    assert run_due(make_env(timed, [j], FakeClock(at(5)))) == [("test.job", "succeeded")]
    assert runs(timed)[0]["outcome"] == "succeeded" and len(count) == 2


def make_ctx(conn, clock, **kw):
    j = Job("test.job", Calls(), TIME_PROPERTY, **kw)
    seed(conn, (j,))
    got = claim(conn, "test.job", "2026-06-01", "scheduled", clock())
    return scheduler.JobContext(make_env(conn, [j], clock), j, *got), clock


def test_an_outside_calls_timeout_is_cut_to_what_the_lease_and_the_deadline_have_left(timed):
    ctx, clock = make_ctx(timed, FakeClock(at(4)))
    assert ctx.call_timeout(120) == 120                     # plenty of lease left
    clock.advance(230)                                       # 70 seconds of lease left, 30 of them the margin
    assert ctx.call_timeout(120) == 40
    clock.advance(30)                                        # 40 left: below the margin's double, so it renews first
    assert ctx.call_timeout(120) == 120
    assert lock(timed)[1] == "2026-06-01T04:09:20Z"


def test_an_outside_calls_timeout_never_passes_the_deadline(conn):
    add_time(conn)
    ctx, clock = make_ctx(conn, FakeClock(at(4)), deadline_seconds=50)
    assert ctx.call_timeout(120) == 50


def test_a_renewal_that_fails_during_a_pause_ends_the_run_as_lost_without_touching_the_new_owner(timed):
    state = {}

    def takeover(seconds):
        if "new" not in state:
            state["clock"].advance(400)                 # the process stalled past its lease
            reconcile(timed, state["clock"]())
            state["new"] = claim(timed, "test.job", "2026-06-01", "manual", state["clock"]())

    def flaky(ctx):
        raise Retryable("Busy.")
    clock = FakeClock(at(5))
    state["clock"] = clock
    env = make_env(timed, [Job("test.job", flaky, TIME_PROPERTY)], clock, on_wait=takeover)
    assert run_due(env) == [("test.job", "abandoned")]
    assert lock(timed)[0] == state["new"][0]
    assert [r["outcome"] for r in runs(timed)] == ["abandoned", "running"]


# -- a manual run in the foreground --

def test_a_manual_run_is_recorded_as_manual_is_refused_while_the_lock_is_held_and_leaves_the_scheduled_run_alone(timed):
    calls = Calls()
    j = Job("test.job", calls, TIME_PROPERTY)
    clock = FakeClock(at(5))
    env = make_env(timed, [j], clock)
    assert run_now(env, j) == "succeeded"
    assert runs(timed)[0]["started_by"] == "manual"
    held = claim(timed, "test.job", "2026-06-01", "manual", clock())
    assert run_now(env, j) is None
    finish(timed, "test.job", held[0], held[1], "succeeded", "Done.", clock())
    run_due(env)                                            # the date's scheduled run was not used up by the manual ones
    assert [r["started_by"] for r in runs(timed)] == ["manual", "manual", "scheduled"] and calls.count == 2


# -- shutdown --

def test_a_stop_during_a_retry_pause_ends_it_at_once_and_the_run_is_recorded_as_stopped(timed):
    stop = threading.Event()

    def flaky(ctx):
        raise Retryable("Busy.")
    env = make_env(timed, [Job("test.job", flaky, TIME_PROPERTY)], FakeClock(at(5)), stop=stop, on_wait=lambda s: stop.set())
    assert run_due(env) == [("test.job", "failed")]
    assert runs(timed)[0]["detail"].startswith("Stopped")


def test_a_stop_before_a_step_is_noticed_at_the_next_check(timed):
    stop = threading.Event()

    def steps(ctx):
        stop.set()
        ctx.check()
    run_due(make_env(timed, [Job("test.job", steps, TIME_PROPERTY)], FakeClock(at(5)), stop=stop))
    assert runs(timed)[0]["outcome"] == "failed" and runs(timed)[0]["detail"].startswith("Stopped")


def test_the_loop_starts_with_the_scheduler_and_stops_when_told(tmp_path):
    path = tmp_path / "loop.db"
    create_app(path)
    runner = scheduler.Scheduler(path, ())
    runner.start()
    assert runner.thread.is_alive() and runner.thread.daemon
    started = time.monotonic()
    runner.stop()
    assert not runner.thread.is_alive() and time.monotonic() - started < 5


def test_the_loop_survives_a_failing_tick_and_waits_longer_each_time(tmp_path, monkeypatch, caplog):
    path = tmp_path / "loop.db"
    create_app(path)
    monkeypatch.setattr(scheduler, "TICK_SECONDS", 0.01)
    monkeypatch.setattr(scheduler, "BACKOFF_CAP_SECONDS", 0.05)
    calls = []

    def flaky(env):
        calls.append(1)
        if len(calls) <= 3:
            raise sqlite3.OperationalError("database is locked: C:/private/path.db")
        return []
    monkeypatch.setattr(scheduler, "run_due", flaky)
    runner = scheduler.Scheduler(path, ())
    with caplog.at_level(logging.DEBUG):
        runner.start()
        deadline = time.monotonic() + 5
        while len(calls) < 6 and time.monotonic() < deadline:
            time.sleep(0.01)
        alive = runner.thread.is_alive()
        runner.stop()
    assert len(calls) >= 6 and alive
    assert caplog.text.count("The scheduler failed") == 1               # the first of a kind is logged, repeats are counted
    assert "working again" in caplog.text and "private" not in caplog.text


def test_a_stuck_job_does_not_hold_up_stopping_the_application(tmp_path, monkeypatch):
    path = tmp_path / "loop.db"
    create_app(path)
    with db.connect(path) as conn:
        add_time(conn, "00:00")
    release = threading.Event()
    entered = threading.Event()

    def stuck(ctx):
        entered.set()
        release.wait(30)
    monkeypatch.setattr(scheduler, "SHUTDOWN_JOIN_SECONDS", 0.3)
    runner = scheduler.Scheduler(path, (Job("test.job", stuck, TIME_PROPERTY),))
    runner.start()
    assert entered.wait(5)
    started = time.monotonic()
    runner.stop()
    assert time.monotonic() - started < 3 and runner.thread.is_alive() and runner.thread.daemon
    release.set()
    runner.thread.join(5)
    assert not runner.thread.is_alive()


def test_the_app_runs_the_scheduler_for_as_long_as_the_server_does(tmp_path):
    app = create_app(tmp_path / "web.db")
    with TestClient(app):
        thread = app.state.scheduler.thread
        assert thread.is_alive()
    assert not thread.is_alive()


def test_a_test_client_used_without_a_context_starts_no_thread(tmp_path):
    app = create_app(tmp_path / "web.db")
    TestClient(app).get("/login")
    assert not hasattr(app.state, "scheduler")


# -- the tables and the Time property --

def test_a_run_row_is_open_exactly_while_it_is_running(timed):
    seed(timed, (job(),))
    row = "INSERT INTO sys_job_runs (job, run_date, started_by, started_at, finished_at, outcome) VALUES ('test.job', '2026-06-01', 'manual', 't', ?, ?)"
    with pytest.raises(sqlite3.IntegrityError):
        timed.execute(row, (None, "succeeded"))
    with pytest.raises(sqlite3.IntegrityError):
        timed.execute(row, ("t", "running"))
    with pytest.raises(sqlite3.IntegrityError):
        timed.execute("INSERT INTO sys_jobs (job, owner, lease_until) VALUES ('x.job', 'aaaaaaaaaaaaaaaa', NULL)")


@pytest.mark.parametrize("good", ["00:00", "04:30", "23:59"])
def test_a_time_is_saved_as_typed(conn, good):
    add_time(conn, None)
    assert sp.set_property(op(conn), TIME_PROPERTY, f" {good} ") == good


@pytest.mark.parametrize("bad", ["24:00", "4:30", "04:60", "04.30", "0430", "04:30:00", "noon", "4pm", "٠٤:٣٠"])
def test_a_time_that_is_not_hh_mm_is_refused(conn, bad):
    add_time(conn, "05:00")
    with pytest.raises(ValidationError, match="24-hour clock"):
        sp.set_property(op(conn), TIME_PROPERTY, bad)
    assert conn.execute("SELECT value FROM system_properties WHERE name = ?", (TIME_PROPERTY,)).fetchone()[0] == "05:00"


def test_a_time_property_lists_as_a_time_through_the_api(client):
    with db.connect(client.app.state.db_path) as conn:
        add_time(conn, "04:30")
    rows = {p["name"]: p for p in client.get("/api/system-properties").json()["properties"]}
    assert rows[TIME_PROPERTY]["type"] == "Time" and rows[TIME_PROPERTY]["value"] == "04:30"
    saved = client.put(f"/api/system-properties/{TIME_PROPERTY}", json={"value": "05:15"})
    assert saved.status_code == 200
    refused = client.put(f"/api/system-properties/{TIME_PROPERTY}", json={"value": "25:00"})
    assert refused.status_code == 422 and "24-hour clock" in refused.json()["detail"]


def test_the_registry_ships_empty_until_a_job_is_added():
    assert scheduler.REGISTRY == ()
