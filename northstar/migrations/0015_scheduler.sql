-- The in-app scheduler (#138). `sys_jobs` has one row per registered job and holds its lock; `sys_job_runs` is the record of
-- every run. Both are the application's own tables: no audit columns, never in the change log. A job exists because code
-- registers it (northstar/scheduler.py), so the rows are seeded at startup and never by a migration. See
-- docs/design/scheduler/design.md.

-- A time of day is a kind of setting: HH:MM on a 24-hour clock, read in the installation's time zone.
INSERT INTO ref_property_data_types (name) VALUES ('Time');

-- The lock. `owner` is a fresh random token for each acquisition, and the holder may commit only while `lease_until` has not
-- passed. Both are empty when the job is free.
CREATE TABLE sys_jobs (
    job         TEXT PRIMARY KEY CHECK (length(job) BETWEEN 1 AND 100),
    owner       TEXT CHECK (owner IS NULL OR length(owner) >= 16),
    lease_until TEXT,
    CHECK ((owner IS NULL) = (lease_until IS NULL))
);

CREATE TABLE sys_job_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job         TEXT NOT NULL REFERENCES sys_jobs (job),
    -- The installation's calendar date the run is for, with no time zone.
    run_date    TEXT NOT NULL CHECK (run_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    started_by  TEXT NOT NULL CHECK (started_by IN ('scheduled', 'manual')),
    -- UTC timestamps. `finished_at` is empty exactly while the run is running.
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    outcome     TEXT NOT NULL CHECK (outcome IN ('running', 'succeeded', 'failed', 'abandoned')),
    -- A short status or error text written by our code: never a secret, never the text of an exception.
    detail      TEXT CHECK (detail IS NULL OR length(detail) <= 500),
    CHECK ((outcome = 'running') = (finished_at IS NULL))
);
-- At most one scheduled run for a job and date. A manual run is not covered.
CREATE UNIQUE INDEX sys_job_runs_one_scheduled ON sys_job_runs (job, run_date) WHERE started_by = 'scheduled';
CREATE INDEX sys_job_runs_started_at ON sys_job_runs (started_at);
