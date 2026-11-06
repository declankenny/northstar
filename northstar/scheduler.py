"""The in-app scheduler: runs registered jobs once a day at an admin-chosen time. See docs/design/scheduler/design.md.

A job is code in `REGISTRY`; the database holds only what changes at run time, in two tables of the application's own,
`sys_jobs` (one row per job, its lock) and `sys_job_runs` (the record of every run). A daemon thread calls `run_due`
about once a minute. `run_due` is a plain function that takes everything it needs in an `Env`, so tests give it a fake
clock and never sleep.

What the lock guarantees is that a stale owner cannot commit. A lease cannot promise two executions never overlap: a
paused process can outlast it. So the lock has a fresh token for each acquisition and a lease, every commit a job makes
starts with a statement that checks the token and the unexpired lease in the same transaction (`hold`), and a holder
that finds it has lost the lock stops. Expired locks are cleared, and their running rows marked abandoned, by
`reconcile`, the first step of every tick.

Nothing here logs or stores the text of an exception, because an exception can carry a request URL with a credential
in it. A job fails with a `JobError` whose message is written in our own code, and any other exception is recorded as
its class name and the place it was raised.

The numbers below are constants on purpose, not system properties: the lease, the pauses, the slices and the margin
depend on each other, and a wrong value gives overlapping or abandoned runs and not a slower scheduler. A per-job
value (the deadline, the retry pauses) belongs to the job in the registry.
"""

import logging
import os
import re
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

from northstar import clock, db, system_properties, writer

log = logging.getLogger(__name__)

TICK_SECONDS = 60                       # how often the loop wakes
LEASE_SECONDS = 300                     # how long a lock lasts without a renewal
RENEW_SLICE_SECONDS = LEASE_SECONDS // 3    # a long pause is cut into slices this long, renewing after each
CALL_MARGIN_SECONDS = 30                # an outside call's timeout leaves this much of the lease unused
JOB_DEADLINE_SECONDS = 600              # a job's default overall deadline
RETRY_PAUSES = (30, 120, 300)           # a job's default pauses before each retry: three retries after the first try
BACKOFF_CAP_SECONDS = 300               # the longest the loop waits after a failed tick
RECORD_ATTEMPTS = 3                     # tries to write a run's outcome before leaving it to reconciliation
RECORD_PAUSE_SECONDS = 1
RETENTION_DAYS = 90                     # finished runs older than this are deleted by the loop
SHUTDOWN_JOIN_SECONDS = 10              # how long stopping the application waits for the thread
DETAIL_MAX = 200                        # the longest message kept from a job

_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://\S+")


class JobError(Exception):
    """A failure a job reports. The message is written in our own code for a person to read, never taken from another
    exception's text, and it is checked once more before it is kept (see `safe_text`)."""
    label = "Failed"

    def __init__(self, message: str = ""):
        super().__init__(message)
        self.message = message


class Retryable(JobError):
    """A failure that may clear on its own: a network error, a timeout, a 429 or a 5xx. Only the job knows."""
    label = "Could not complete"


class InvalidResponse(JobError):
    """What came back failed validation. It is not retried."""
    label = "Invalid response"


class LostLease(JobError):
    """The lock is no longer this run's: it expired and was cleared or taken. The run stops and writes nothing more."""
    label = "Lost its lock"


class TimedOut(JobError):
    label = "Timed out"


class Stopped(JobError):
    label = "Stopped"


@dataclass(frozen=True)
class Job:
    name: str                                   # such as currency.rates.fetch
    run: Callable[["JobContext"], None]
    time_property: str                          # the Time system property that holds its start time
    deadline_seconds: int = JOB_DEADLINE_SECONDS
    retry_pauses: tuple[int, ...] = RETRY_PAUSES


# The catalog: a job exists because code says so. The rate fetch (#131) is the first.
REGISTRY: tuple[Job, ...] = ()


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_text(text: str) -> str:
    """A message fit to keep: any link removed, whitespace collapsed, and cut short."""
    text = " ".join(_URL.sub("[link removed]", text).split())
    return text if len(text) <= DETAIL_MAX else text[:DETAIL_MAX - 1] + "…"


def describe(exc: BaseException) -> str:
    """What is kept of an exception that is not a JobError: its class and where it was raised, never its text."""
    trace = exc.__traceback__
    while trace is not None and trace.tb_next is not None:
        trace = trace.tb_next
    place = "" if trace is None else f" at {os.path.basename(trace.tb_frame.f_code.co_filename)}:{trace.tb_lineno}"
    return f"Unexpected {type(exc).__name__}{place}"


class ErrorLog:
    """Logs the first failure of each kind with its category and place, counts the repeats, and says once when the
    failures have stopped."""

    def __init__(self):
        self.seen: dict[str, int] = {}

    def report(self, exc: BaseException, doing: str) -> None:
        what = exc.message if isinstance(exc, JobError) and exc.message else describe(exc)
        kind = f"{doing}: {safe_text(what)}"
        self.seen[kind] = self.seen.get(kind, 0) + 1
        if self.seen[kind] == 1:
            log.error("The scheduler failed while %s", kind)

    def recovered(self) -> None:
        if self.seen:
            log.warning("The scheduler is working again after %d failure(s) of %d kind(s).",
                        sum(self.seen.values()), len(self.seen))
            self.seen.clear()


@dataclass
class Env:
    """Everything `run_due` needs. `now` is the injected source of the current UTC moment, read again before every
    decision. `wait(seconds)` sleeps and returns True when the scheduler is stopping: in production it waits on the stop
    event, and a test's version advances its fake clock."""
    conn: object
    registry: tuple[Job, ...]
    now: Callable[[], datetime] = lambda: clock.now()
    stop: threading.Event = field(default_factory=threading.Event)
    wait: Callable[[float], bool] | None = None
    errors: ErrorLog = field(default_factory=ErrorLog)

    def __post_init__(self):
        if self.wait is None:
            self.wait = self.stop.wait


# -- the lock --

def seed(conn, registry: tuple[Job, ...]) -> None:
    """A row in sys_jobs for every registered job. A row whose job is no longer registered is left alone."""
    for job in registry:
        writer.sys_insert_ignore(conn, "sys_jobs", {"job": job.name})


def reconcile(conn, now: datetime) -> list[str]:
    """Clear every lock whose lease has passed, registered job or not, and mark that job's running rows abandoned. It
    is this step that records abandonment, so it is recorded at the first reconciliation after the lease expires."""
    stamped = stamp(now)
    cleared = []
    with db.write_transaction(conn):
        for row in conn.execute("SELECT job, owner FROM sys_jobs WHERE owner IS NOT NULL AND lease_until < ?",
                                (stamped,)).fetchall():
            if writer.sys_update(conn, "sys_jobs", {"owner": None, "lease_until": None},
                                 [("job", "=", row["job"]), ("owner", "=", row["owner"])]):
                writer.sys_update(conn, "sys_job_runs", {
                    "outcome": "abandoned", "finished_at": stamped,
                    "detail": "Abandoned: its lock expired before it finished."},
                                  [("job", "=", row["job"]), ("outcome", "=", "running")])
                cleared.append(row["job"])
    return cleared


def claim(conn, job: str, run_date: str, started_by: str, now: datetime) -> tuple[str, int, datetime] | None:
    """Take the job's lock and add its run row, in one transaction. Returns (token, run id, lease end), or None when the
    lock is held or, for a scheduled run, the date already has one. A manual run is not limited to one a date."""
    token = secrets.token_hex(16)
    lease = now + timedelta(seconds=LEASE_SECONDS)
    with db.write_transaction(conn):
        if not writer.sys_update(conn, "sys_jobs", {"owner": token, "lease_until": stamp(lease)},
                                 [("job", "=", job), ("owner", "IS", None)]):
            return None
        run_id = writer.sys_insert_ignore(conn, "sys_job_runs", {
            "job": job, "run_date": run_date, "started_by": started_by, "started_at": stamp(now), "outcome": "running"})
        if run_id is None:
            writer.sys_update(conn, "sys_jobs", {"owner": None, "lease_until": None},
                              [("job", "=", job), ("owner", "=", token)])
            return None
    return token, run_id, lease


def hold(conn, job: str, token: str, now: datetime) -> datetime:
    """The ownership check, and the renewal: one statement that changes the row only while this token still owns the job
    and its lease has not passed. Every commit a job makes starts with it, in the same transaction, so a stale owner's
    work is rolled back. Returns the new end of the lease."""
    lease = now + timedelta(seconds=LEASE_SECONDS)
    if not writer.sys_update(conn, "sys_jobs", {"lease_until": stamp(lease)},
                             [("job", "=", job), ("owner", "=", token), ("lease_until", ">=", stamp(now))]):
        raise LostLease("The lock was lost before the work was saved.")
    return lease


def finish(conn, job: str, token: str, run_id: int, outcome: str, detail: str, now: datetime) -> None:
    """Write a run's outcome and free the lock, as one transaction that first checks the lock is still this run's."""
    with db.write_transaction(conn):
        hold(conn, job, token, now)
        if not writer.sys_update(conn, "sys_job_runs", {"outcome": outcome, "finished_at": stamp(now), "detail": detail},
                                 [("id", "=", run_id), ("outcome", "=", "running")]):
            raise LostLease("The run was already closed.")
        writer.sys_update(conn, "sys_jobs", {"owner": None, "lease_until": None},
                          [("job", "=", job), ("owner", "=", token)])


def prune(conn, now: datetime) -> int:
    with db.write_transaction(conn):
        return writer.sys_delete(conn, "sys_job_runs", [
            ("started_at", "<=", stamp(now - timedelta(days=RETENTION_DAYS))), ("outcome", "!=", "running")])


# -- what a job is given --

class JobContext:
    """What a running job uses: the checks it makes between steps, its pauses, the timeout for an outside call and the
    way it commits. Every one keeps the lease alive and stops the job when the lock is lost, the deadline has come or
    the application is stopping."""

    def __init__(self, env: Env, job: Job, token: str, run_id: int, lease: datetime):
        self.env, self.job, self.token, self.run_id = env, job, token, run_id
        self.conn = env.conn
        self.lease_until = lease
        self.deadline = env.now() + timedelta(seconds=job.deadline_seconds)

    def now(self) -> datetime:
        return self.env.now()

    def renew(self) -> None:
        with db.write_transaction(self.conn):
            self.lease_until = hold(self.conn, self.job.name, self.token, self.now())

    def check(self) -> None:
        """Between steps and before each retry: stop if told to or out of time, and renew the lease."""
        if self.env.stop.is_set():
            raise Stopped("Stopped because the application is shutting down.")
        if self.now() >= self.deadline:
            raise TimedOut(f"Did not finish within {self.job.deadline_seconds} seconds.")
        self.renew()

    def call_timeout(self, configured: float) -> float:
        """The timeout for one outside call: its own, but never more than the lease and the deadline have left, less a
        margin. Renews first when the lease is nearly gone, so an ordinary slow call does not abandon a healthy run."""
        if (self.lease_until - self.now()).total_seconds() < CALL_MARGIN_SECONDS * 2:
            self.renew()
        lease_left = (self.lease_until - self.now()).total_seconds() - CALL_MARGIN_SECONDS
        deadline_left = (self.deadline - self.now()).total_seconds()
        return max(1.0, min(configured, lease_left, deadline_left))

    def pause(self, seconds: float) -> None:
        """Wait, in slices of about a third of the lease with a renewal after each. A stop ends it at once, and a wait that
        would pass the deadline is cut there and ends the job as timed out."""
        end = min(self.now() + timedelta(seconds=seconds), self.deadline)
        while self.now() < end:
            if self.env.wait(min((end - self.now()).total_seconds(), RENEW_SLICE_SECONDS)):
                raise Stopped("Stopped because the application is shutting down.")
            self.renew()
        if self.now() >= self.deadline:
            raise TimedOut(f"Did not finish within {self.job.deadline_seconds} seconds.")

    def commit(self, work: Callable[[object], object]):
        """Run `work(conn)` as one transaction that first checks the lock. If the lock was lost nothing is written."""
        with db.write_transaction(self.conn):
            self.lease_until = hold(self.conn, self.job.name, self.token, self.now())
            return work(self.conn)


# -- running --

def zone_of(conn) -> tzinfo:
    """The installation's zone from its setting, or UTC when it is empty or not readable on this machine."""
    name = system_properties.get_value(conn, system_properties.SYSTEM_TIMEZONE)
    try:
        return clock.zone_for(name) if name else timezone.utc
    except ValueError:
        return timezone.utc


def due_date(conn, job: Job, now: datetime) -> str | None:
    """The run date if the job is due, else None. Due is once per calendar date, at or after the start time, when there
    is no scheduled run for that date, so a daylight-saving day that skips or repeats the time runs the job once. A job
    whose start time is unset is not scheduled. The zone and the start time are read together, for this decision only."""
    start = system_properties.get_value(conn, job.time_property)
    if not start:
        return None
    local = now.astimezone(zone_of(conn))
    if local.strftime("%H:%M") < start:
        return None
    run_date = local.date().isoformat()
    if conn.execute("SELECT 1 FROM sys_job_runs WHERE job = ? AND run_date = ? AND started_by = 'scheduled'",
                    (job.name, run_date)).fetchone():
        return None
    return run_date


def _record(env: Env, job: Job, token: str, run_id: int, outcome: str, detail: str) -> None:
    """Write the outcome, trying a few times. If it cannot be written the row stays running and the lock is kept, and
    reconciliation marks it abandoned once the lease runs out: safe, because a job can be run again."""
    for attempt in range(RECORD_ATTEMPTS):
        try:
            finish(env.conn, job.name, token, run_id, outcome, detail, env.now())
            return
        except LostLease:
            log.warning("%s lost its lock before its outcome was recorded.", job.name)
            return
        except Exception as exc:                # a database error: say what kind, never its text
            env.errors.report(exc, f"recording the outcome of {job.name}")
            if attempt + 1 < RECORD_ATTEMPTS and env.wait(RECORD_PAUSE_SECONDS):
                return
    log.error("The outcome of %s could not be recorded. Its lock will expire and the run will be marked abandoned.", job.name)


def execute(env: Env, job: Job, token: str, run_id: int, lease: datetime) -> str:
    """Run a claimed job with its retries, record the outcome and return it."""
    ctx = JobContext(env, job, token, run_id, lease)
    outcome, detail = "succeeded", "Completed."
    attempts = 0
    try:
        while True:
            ctx.check()
            attempts += 1
            try:
                job.run(ctx)
                break
            except Retryable as exc:
                if attempts > len(job.retry_pauses):
                    raise Retryable(f"Gave up after {attempts} tries: {exc.message}") from None
                ctx.pause(job.retry_pauses[attempts - 1])
    except LostLease:
        log.warning("%s lost its lock and stopped.", job.name)
        return "abandoned"
    except JobError as exc:
        outcome, detail = "failed", safe_text(f"{exc.label}: {exc.message}" if exc.message else exc.label)
    except Exception as exc:
        outcome, detail = "failed", describe(exc)
        log.error("%s failed: %s", job.name, detail)
    _record(env, job, token, run_id, outcome, detail)
    return outcome


def run_due(env: Env) -> list[tuple[str, str]]:
    """One tick: reconcile expired locks, then run each due job in turn, rereading the clock before each decision so a
    job that crosses midnight does not leave the next one judged on yesterday's date. Returns (job, outcome) for the
    jobs that ran. A failure judging or claiming one job is logged and does not stop the others."""
    with db.write_transaction(env.conn):
        seed(env.conn, env.registry)
        reconcile(env.conn, env.now())
    ran = []
    for job in env.registry:
        if env.stop.is_set():
            break
        try:
            now = env.now()
            run_date = due_date(env.conn, job, now)
            if run_date is None:
                continue
            claimed = claim(env.conn, job.name, run_date, "scheduled", now)
        except Exception as exc:
            env.errors.report(exc, f"deciding whether {job.name} is due")
            continue
        if claimed is not None:
            ran.append((job.name, execute(env, job, *claimed)))
    prune(env.conn, env.now())
    return ran


def run_now(env: Env, job: Job) -> str | None:
    """A manual run in the foreground, for the command line: reconcile, take the lock, run the job and return its outcome,
    or None when the job's lock is held. It is recorded as manual and does not count as the date's scheduled run."""
    with db.write_transaction(env.conn):
        seed(env.conn, env.registry)
        reconcile(env.conn, env.now())
    now = env.now()
    claimed = claim(env.conn, job.name, now.astimezone(zone_of(env.conn)).date().isoformat(), "manual", now)
    return None if claimed is None else execute(env, job, *claimed)


class Scheduler:
    """The thread that calls `run_due` about once a minute. It opens its own connection, survives any failure of a tick
    (logging it, then waiting longer, up to a cap), and stops promptly: a stop interrupts its sleep and every pause."""

    def __init__(self, db_path: str | Path, registry: tuple[Job, ...] | None = None):
        self.db_path = db_path
        self.registry = REGISTRY if registry is None else registry
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.errors = ErrorLog()

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop, name="northstar-scheduler", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Tell the loop to stop and wait a little for it. The thread is a daemon, so a job stuck in a call that ignores
        its timeout cannot hold the process open; its lease expires and the next start marks the run abandoned."""
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(SHUTDOWN_JOIN_SECONDS)

    def _loop(self) -> None:
        conn = None
        failures = 0
        while not self.stop_event.is_set():
            pause = TICK_SECONDS
            try:
                if conn is None:
                    conn = db.connect(self.db_path)
                reported = sum(self.errors.seen.values())
                run_due(Env(conn, self.registry, stop=self.stop_event, errors=self.errors))
                failures = 0
                if sum(self.errors.seen.values()) == reported:
                    self.errors.recovered()         # a tick with nothing to report ends a run of failures
            except Exception as exc:
                failures += 1
                self.errors.report(exc, "running a tick")
                pause = min(BACKOFF_CAP_SECONDS, TICK_SECONDS * 2 ** failures)
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = None
            self.stop_event.wait(pause)
        if conn is not None:
            conn.close()
