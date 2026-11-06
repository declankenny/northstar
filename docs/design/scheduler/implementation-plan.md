# In-app scheduler: implementation plan

Three steps, each its own branch and pull request into `main`.

| Step | What | Issue |
|---|---|---|
| 1 | The installation's time zone: `system.timezone`, the startup copy of `TZ`, `today()` in that zone with `now()` unchanged | [#152](https://github.com/declankenny/northstar/issues/152) |
| 2 | The scheduler: the Time data type, `sys_jobs` and `sys_job_runs`, the registry, `run_due`, the lock, the loop and its failure and shutdown handling, with test jobs and no real one | [#138](https://github.com/declankenny/northstar/issues/138) |
| 3 | The rate fetch: the job, its start-time property, the command line, the last fetch on the currency page and the staleness warning | [#131](https://github.com/declankenny/northstar/issues/131) |

Not planned for v0.3: a manual run from a screen ([#154](https://github.com/declankenny/northstar/issues/154)) and a Jobs screen ([#155](https://github.com/declankenny/northstar/issues/155)).

## Step 2 (#138)

- **Scope:** migration `0015_scheduler`; the writer's `sys_update` and `sys_insert_ignore`; `northstar/scheduler.py`; the lifespan in `northstar/web/app.py`; the Time type in the setting service and the editor.
- **Tests:** as listed in `design.md`, on a fake clock, with mutation checks on the lock statements.
- **Docs:** the spec rule, a decisions entry, `docs/schema.md`, the changelog and the operator guide's backup wording.

## Step 3 (#131)

- **Scope:** the rate fetch as the first job in `REGISTRY`, the `currency.rate.fetch_time` property with a default chosen from the provider's publishing time, `python -m northstar.rates fetch` using `run_now`, the last fetch and its outcome on the currency page, and the staleness warning. The "Daily run" paragraph of `docs/design/currency/design.md` changes from the host's cron to the scheduler, and the rate cron example in `docs/operating.md` is dropped.
- **Open before it starts:** the provider's publishing time and the Frankfurter checks.
