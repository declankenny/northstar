# In-app scheduler: design

Status: third revision, November 6, 2026, for issue #138. Step 1 (the time zone, #152) is built and merged. Step 2 (the scheduler) is built in the pull request that adds this folder. Step 3 (the rate fetch, #131) is not started. This is not the spec or the decisions log: the rules are in `docs/spec.md` and the reasons in `docs/decisions.md`.

Each item is labelled. **Decided** means Declan agreed it. **Proposed** means it is the recommendation and has not been challenged or confirmed. **Open** means it is unresolved: do not guess it.

## Outcome

Northstar can run a job at an admin-chosen time of day with nothing set up on the host. The first job is the daily exchange-rate fetch (#131). A bank feed (SimpleFIN) will add more jobs later, so the scheduler is built for several jobs from the start and has no knowledge of rates.

Backups stay a host cron job. This is the first background work in the application.

## Scope

In: a job registry, a loop that runs due jobs, a lock per job, a record of each run, the installation time zone as a system property, a Time system property for a job's start time, a clock that tests can fix, and the first job's wiring (the fetch itself is #131).

Out for v0.3: a manual run from a screen (#154), a Jobs screen (#155), cron expressions, running jobs on a schedule other than once a day, jobs defined by admins, and any job that is not the rate fetch.

## Decisions

- **No library** (decided in conversation). The loop, the registry and the tables are small and standard, and a library's own job store would duplicate the tables we need for the lock and history. The dependency rule needs a stated reason and there is none. Reconsider if schedules become cron expressions or the job count passes about five.
- **Job-agnostic from the start** (decided). A registry, a schedule property and a lock per job, so SimpleFIN is an addition and not a rewrite.
- **Backups stay on the host** (decided).
- **The start time is a system property, not a column** (decided). The System properties page already edits, validates and audits properties; a `sys_` table column would need its own screen and would sit outside the change log. It stays a property unless admins ever define jobs or give one job several schedules.
- **The numbers are constants, not system properties** (decided). See The numbers.
- **Manual runs and the Jobs screen are deferred** (decided), to #154 and #155.

## The time zone

Built in #152 and #153. **`system.timezone`** is a String system property holding an IANA name such as `America/Chicago`, validated against the zone database, and empty means UTC. While it is empty at startup and `TZ` names a zone, `TZ` is copied into it once by the system user and then ignored. `clock.now()` is an absolute UTC instant and never changes with the zone, because sign-in throttling subtracts durations from it. `clock.today()` is the date of `now()` in the installation's zone, which is held in the clock module, set at startup and when the property is saved. Changing the zone moves where "today" begins by at most a day and changes no stored date.

## The schedule

**A Time data type.** `HH:MM` on a 24-hour clock with a leading zero, validated, edited with a time box. Added by the migration that creates the scheduler's tables.

**The registry.** A list in code, `REGISTRY`, empty until the rate fetch is added. Each entry has the job's name (`currency.rates.fetch`), the function to call, the name of the Time property that holds its start time, an overall deadline (default 10 minutes) and its retry pauses (default 30 seconds, 2 minutes and 5 minutes). The registry is the catalog: a job exists because code says so. The database holds only what changes at run time.

**One property per job.** The rate fetch's will be `currency.rate.fetch_time` (#131), default to be chosen there. A job whose property is unset is not scheduled.

**The rule for "due".** A job is due once per calendar date, at or after its start time, if there is no scheduled run for that date. It is not "at exactly 04:00", so a daylight-saving day on which 04:00 does not exist, or happens twice, runs the job once, as soon as the clock is at or after that time. The date is the installation's date at the moment the run is claimed.

## The loop

**Where it runs.** A daemon thread started and stopped with the server (the FastAPI lifespan) that wakes once a minute and calls one function, `run_due(env)`. That function first seeds and reconciles (see The lock), then walks the registry, decides which jobs are due and runs each in turn, then prunes old runs. It is a plain function with no thread in it: everything it needs is in an `Env` (the connection, the registry, the injected clock, the stop event and the wait function), so tests pass a fake clock and a fake wait and never sleep. The test client starts the thread only when it is used as a context manager.

**One snapshot per decision.** Jobs run one after another, so time can pass between them. Before each job's claim the function reads the clock again, and reads the zone and that job's start time together, and decides due, the run date and the claim from that snapshot only. If the first job crosses midnight, the second is judged on the new date.

**One job at a time.** Jobs run one after another in the scheduler's thread, never in the web server's. A slow job delays the jobs after it, and a change to a start time takes effect at the next tick after the running job finishes, not always within a minute.

**Catch-up.** A job whose time has passed today and has no scheduled run for today runs at the next tick, which includes the first one after startup, so a container that was down at the scheduled time makes the run up once.

**What a run guarantees.** There is at most one scheduled claim per job per date. It is not a guarantee that the job completes each day: if the process dies after the claim, that date's scheduled attempt is gone, and the run is marked abandoned. This is accepted. The next date runs normally, and the command line (#131) is the manual repair.

**The command line.** `run_now` is a manual run in the foreground for #131's `python -m northstar.rates fetch`: it reconciles, takes the lock, runs the job and returns its outcome, or says the lock is held. It is recorded as manual and does not count as the date's scheduled run. There is no queue and no button.

## The lock

**`sys_jobs`.** One row per registered job, seeded from the registry at startup so every job has a row before the first tick. A row whose job is no longer registered is ignored and not deleted. No audit columns and never in the change log, like the other `sys_` tables.

| Column | Meaning |
|---|---|
| `job` | the registry name, the key |
| `owner` | a fresh random token made for each acquisition, empty when free. It is not a process id: the same process gets a new token every time |
| `lease_until` | UTC timestamp until which the token holder may commit, empty when free |

**What the lock guarantees.** A lease cannot promise that two executions never overlap: a paused process, a slow computation or a long wait can outlast it, and another caller can then take the lock before the first one resumes. What the design guarantees is that **a stale owner cannot commit**. Work outside the database, such as the fetch, may overlap for a while, which is harmless because it only reads. Everything that changes the database is checked against the token and the lease.

**Taking the lock.** One statement: `UPDATE sys_jobs SET owner = ?, lease_until = ? WHERE job = ? AND owner IS NULL`, with a new token. One row changed means this caller holds the lock, zero means someone else does. The scheduled tick and the command line take it the same way. An expired lock is not taken directly, it is first cleared by reconciliation.

**Ownership checked at every commit.** Each batch the job commits, and the final write of its outcome, starts with one statement in the same transaction: `UPDATE sys_jobs SET lease_until = ? WHERE job = ? AND owner = ? AND lease_until >= ?`. That statement is also the renewal. If it changes no row the transaction is rolled back and the job stops with a lost-lease error, so a stale owner's batch never lands. The outcome write also requires the run row to still be `running`, and release clears the owner only where the token matches. A job that is paused past its lease, resumes after takeover and tries to commit therefore fails, and the new owner's work is untouched.

**Reconciliation.** The first step of every tick, and of a command-line run before it takes the lock, is one transaction over every `sys_jobs` row, registered or not: where `owner` is set and `lease_until` has passed, clear the owner and the lease and mark that job's `running` rows `abandoned` with a finish time. It is this step that records abandonment, so abandonment is recorded at the first reconciliation after the lease has expired, which is the next tick after expiry and not necessarily the next tick after the crash. A removed job's rows are cleaned too, and the first tick after startup covers a crash of the previous process. Until a reconciliation happens after expiry, a crashed run still shows `running`, and the scheduled claim for that date stays used.

**Midnight.** A run that crosses midnight keeps its lock. The next date's scheduled run finds the lock held, does nothing, and tries again at the next tick.

**More than one process.** The image runs one process and that is the supported shape. The lock and the unique index are single atomic statements in the database, so they do not depend on that, but this design does not promise more than concurrent connections in tests.

## Runs

**`sys_job_runs`.** One row per run, in a `sys_` table.

| Column | Meaning |
|---|---|
| `id` | integer key |
| `job` | the registry name, a foreign key to `sys_jobs` |
| `run_date` | the installation's calendar date the run is for, `YYYY-MM-DD` |
| `started_by` | `scheduled` or `manual`. Not called `trigger`, which is an SQL keyword |
| `started_at`, `finished_at` | UTC timestamps. `finished_at` is empty exactly while the run is running |
| `outcome` | `running`, `succeeded`, `failed` or `abandoned`. A `queued` outcome arrives with #154 |
| `detail` | a short status or error text, at most 500 characters, never a secret and never the text of an exception |

A unique index on (`job`, `run_date`) where `started_by = 'scheduled'`.

**The claim.** In one transaction the caller takes the job's lock and inserts its run row. For a scheduled run the insert is `INSERT OR IGNORE`, and if it is ignored the date already has a scheduled run, the lock is released and the job is skipped. A manual run is not covered by the index. So the index guarantees once per date and the lock guarantees that only the current holder can commit.

**Retention.** Finished runs older than 90 days are deleted by the loop at the end of each tick. A running row is never deleted.

## Failures

**A job fails.** The run is recorded `failed` with a short message and the loop goes on. A job signals a retryable error by raising `Retryable`, and only the job knows: a network failure, a timeout, a 429 or a 5xx from a provider are retryable, a response that fails validation (`InvalidResponse`) is not. A retryable failure is tried again up to three times with the job's pauses, which stop at the job's deadline, then left until the next date. Jobs must be safe to run again, because a retry, an abandoned run and a manual run can all repeat work: a job commits validated batches atomically through `JobContext.commit` and never leaves a partial result that a rerun would misread.

**The scheduler fails.** Claiming a run, reading a property, recording the outcome and pruning history can fail as well as the job. A failure judging or claiming one job is logged and does not stop the others. Each tick runs inside one outer boundary that catches any exception, logs it, closes the connection and sleeps with a growing pause (2, 4, then 5 minutes at most). The thread never ends because of a tick. The first failure of a kind is logged with its category and place, repeats are counted, and recovery is logged once. The web server and its health check are unaffected.

**The job works but the outcome is not recorded.** Recording is tried three times. If it still fails the row stays `running` and the lock is not released, and the lease runs out. The next reconciliation then marks the row `abandoned`. The row then says abandoned for a job that did its work, which is safe because jobs can be run again.

## Timeouts and shutdown

- The scheduler owns a stop event, set when the application shuts down.
- Its sleep between ticks, and every pause, is a wait on that event with a timeout, so a stop interrupts it at once.
- A long pause is broken into slices of about a third of the lease, and the lease is renewed after each slice, so a backoff never outlasts the lease. A wait that would pass the job's deadline is cut there and ends the job as timed out. A renewal that fails during a pause ends the job as lost-lease.
- A job's context checks the stop event, the deadline and the lease between its steps and before each retry. A job that outlasts its deadline stops and is recorded `failed`. A job that sees the stop event stops and is recorded `failed` with a detail saying it was stopped.
- A job asks the context for the timeout of each outside call: the smaller of its own timeout and what the lease and the deadline have left, less a margin of 30 seconds. If the lease is nearly gone the context renews it first. This keeps a healthy run's lock, and it is a courtesy, not the safety: a lapse that happens anyway is caught by the ownership check at the next commit.
- At shutdown the application sets the event and joins the thread for up to ten seconds. The thread is a daemon, so a job stuck in a call that ignores its timeout cannot hold the process open. The lease then expires and the next start marks the run abandoned.

**Safety** (decided, from the rate design). The job fetches outside write transactions and commits validated batches through the shared writer. Background writes are authored by the system user.

## Credentials

The scheduler never logs, records or returns a secret. SimpleFIN's access URL is a credential: it stays where the setting or secret storage keeps it, and a job gets it from there when it runs. `detail` holds only a short status and a message written for a person.

**Safe errors at the logging boundary.** An exception can carry a request URL or another sensitive value in its text, so the text of an exception is never logged or stored. A job fails with one of a fixed set of categories (retryable, invalid response, lost lease, timed out, stopped), each with a message written in our own code, and the message is checked once more: a link is removed, whitespace collapsed and the text cut to 200 characters. For any other exception the scheduler records and logs only its class name and the file and line where it was raised. Tests raise an exception whose message holds a URL with a credential in it and check that neither the log nor `detail` contains any part of it.

## The numbers

All are constants in `northstar/scheduler.py`, named and commented, and not system properties (decided). The lease, the pauses, the slices and the margin depend on each other, and a wrong value gives overlapping or abandoned runs and not a slower scheduler. A system property needs a migration, a validator, a hint, docs and tests. A job's own values, its deadline and its retry pauses, belong to the job in the registry.

| Constant | Value |
|---|---|
| Tick | 60 seconds |
| Lease | 5 minutes, renewed in slices of a third of it |
| Margin left unused by an outside call's timeout | 30 seconds |
| Job deadline (default) | 10 minutes |
| Retry pauses (default) | 30 seconds, 2 minutes, 5 minutes |
| Backoff after a failed tick | doubles from 2 minutes, at most 5 minutes |
| Tries to record an outcome | 3, one second apart |
| Retention of finished runs | 90 days. Revisit it with the Jobs screen (#155) |
| Join at shutdown | 10 seconds |

## Admin visibility

For #131: the currency page shows the last fetch and its outcome, because that is where an admin looks when rates are stale. A manual run from a screen is #154 and a Jobs screen is #155, worth building once a second job exists.

## Implementation plan

Three steps, each its own branch and pull request into `main`, each ending with its issue closed. See `implementation-plan.md`.

## Tests

`run_due` with a fixed clock and a fake wait:
- Due: not due before the time, due at it and after it, once per date, a job with no time not scheduled, a daylight-saving date that skips and repeats the start time, catch-up after downtime, the start time and the run date read in the installation's zone.
- The claim and lock: the unique index refusing a second scheduled run for a date, simultaneous claims from several connections giving one run, a manual and a scheduled claim at the same moment giving one run and the manual run not using the date, two manual claims refused while one is running, a live run that crosses midnight blocking the next date until it ends, and a crashed run not blocking tomorrow.
- Ownership: an old owner that resumes after its lease expired and the lock was reconciled and taken by a new owner, whose batch commit and outcome write both fail and leave the new owner's rows untouched. A new token for every acquisition. A close with the wrong token changing nothing. A commit rolled back whole when the lease check fails. A commit that lands renewing the lease.
- Reconciliation: an expired lock cleared and its `running` rows marked `abandoned`, including for a job no longer registered and on the first tick after startup, and a live lease left alone.
- Two jobs in one call to `run_due`, where the first crosses midnight on the fake clock: the second is judged on the new date.
- Failures: a failing job recorded and the loop going on, retries and their limit, a retryable error that clears, a non-retryable error not retried, a job past its deadline recorded timed out, a failure judging one job not stopping the others, a database error inside a tick caught and the thread alive on the next with the first failure logged once, and a job that works but whose outcome cannot be written ending abandoned.
- Leases: a backoff pause longer than the lease sliced and renewed with the run staying healthy, an outside call's timeout cut to what the lease and the deadline have left, and a renewal failing during a pause ending the run as lost without touching the new owner.
- Credentials: an exception whose message holds a URL with a credential, and a database error whose message holds a path, reach neither the log nor `detail`.
- The command line: recorded as manual, refused while the lock is held, and the scheduled run still made.
- Shutdown: a stop ending a retry pause at once, a stop noticed at the next check, the thread starting and stopping with the scheduler and with the app's lifespan, and a stuck job not holding stopping past its limit.
- The Time property: accepted as typed, refused when it is not `HH:MM`, listed and saved through the API, and edited in a time box.
- The tables: a run is open exactly while it is running, and the writer's `sys_update` and `sys_insert_ignore`.

## Open

- The default start time of the rate fetch, which depends on when the provider publishes (to verify in #131).
- Whether SimpleFIN's limits (how often it may be polled) need a per-job minimum interval. TODO: look them up before designing that job.
- Whether retention should become a system property once the Jobs screen exists (#155).
