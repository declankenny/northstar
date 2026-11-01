# v0.2 database schema: implementation plan

The order of the work for [design.md](design.md). Each step is one feature branch and one pull request into `main`. Tick a step when its pull request is merged. Where a step has no issue yet, "to create" means one is opened when the step starts.

Every step follows the working rules: the spec and `docs/decisions.md` change in the same pull request as the code, every migration is tested on a copy of a v0.1 database first, and tests use synthetic data.

## Order and dependencies

| Step | What | Depends on | Issue |
| --- | --- | --- | --- |
| 1 | Migration runner | none | to create |
| 2 | Migration A: unique account names | the rename question under "Decide first", and step 1 if Python steps are adopted | [#82](https://github.com/declankenny/northstar/issues/82) |
| 3 | Write chokepoint refactor | none (can run beside 1 and 2) | to create |
| 4 | Migration B1: system user, audit columns, `AUTOINCREMENT`, `sys_` renames | 1, 3 | to create |
| 5 | Migration B2: user soft delete | 4 | to create |
| 6 | Migration B3: account soft delete and the partial name index | 2, 4 | to create |
| 7 | Migration C: the change log, registry and `balances.version` | 4 | to create |
| 8 | Import commit | 7, and the import dry run | [#79](https://github.com/declankenny/northstar/issues/79) |
| 9 | Export | none from the schema work | [#80](https://github.com/declankenny/northstar/issues/80) |
| 10 | Undo | 7, 8 | [#81](https://github.com/declankenny/northstar/issues/81) |
| 11 | Epic closing | all | [#55](https://github.com/declankenny/northstar/issues/55) |

Beside the schema work, with no dependency on it: #72, #78, the format parser, the import dry run, and then #11, #12 and #13 landing just before the import wizard. Conflicting-edit detection ([#10](https://github.com/declankenny/northstar/issues/10)) rides on step 7, because `balances.version` is the id of the operation that wrote the balance.

Steps 5 and 6 can run in parallel once step 4 has merged. Recording (steps 4 to 7) must land before import can write.

## Decide first

- **The duplicate-name rename in step 2.** The rename needs the smallest unused suffix, which is awkward in SQL-only migrations. Either SQL that ranks duplicates and puts the id in the suffix when "Name (n)" is taken, or a Python step in the runner. Decide with step 1, since a Python step makes step 2 wait for it.
- **Confirm `json_extract` is available** in the SQLite build the container ships. Step 7 depends on it.

## Steps

### 1. Migration runner

- Scope: rebuild migrations with foreign keys off around the transaction, one migration executor shared by real upgrades and by the scratch replay in `backup._tables_for`, the `schema_migrations` to `sys_schema_migrations` rename done after the validated backup, and recovery from a stray empty old ledger. No schema change beyond the ledger name.
- Tests: rebuild failures while copying and validating; `foreign_keys` restored after success and failure; indexes and views preserved; backup validation of a pre-upgrade backup, after each migration boundary, and a backup missing a required table still rejected; the rollback scenario with the original v0.1 code; a future-version database with a stray empty old ledger refused without mutation; two empty, malformed and two populated ledgers refused without deletion; failure during cleanup leaves no partial recovery.
- [x] Merged

### 2. Migration A: unique account names

- Scope: a full unique index on `name COLLATE NOCASE`, the deterministic duplicate rename, application validation that compares the same way, and the clear message that names a closed holder.
- Tests: add and rename to a taken name, case and whitespace variants, a closed account holding the name, non-ASCII names; a copy of a database with `Name`, `name` and an existing "Name (2)" together; the migration's collision detection and the final index agree.
- [ ] Merged

### 3. Write chokepoint refactor

- Scope: every write to every table goes through a few database-layer functions that take an actor. No schema change, so the actor is passed but nothing uses it yet. Writes to a table with no logged fields behave exactly as today.
- Tests: no SQL writes to any table outside the chokepoint (migrations excepted); every existing write path still behaves as before.
- [ ] Merged

### 4. Migration B1: system user, audit columns, `AUTOINCREMENT`, `sys_` renames

- Scope: the system user; the four audit columns on `accounts`, `account_types`, `balances`, `users` and `account_classes`, backfilled to the system user; `AUTOINCREMENT` on every application-owned table; `sessions` and `login_attempts` renamed to `sys_` names. The chokepoint fills the audit columns.
- Tests: the schema tests for audit columns, `AUTOINCREMENT` and the `sys_` rule (SQLite's own tables excluded); the system user is refused at sign-in with the same message and timing as an unknown email, hidden from the interface and refused by the command line tools; the upgrade of a v0.1 copy.
- [ ] Merged

### 5. Migration B2: user soft delete

- Scope: the `deleted` flag on users, sessions removed and the hash made unusable, hidden from the list, the admin rule counting live admins, and reactivation as an explicit update (the request sets the password, name and admin flag, the theme resets, the id and creation metadata are kept, the system user cannot be reactivated).
- Tests: a formerly admin user re-added without an admin request is a regular user; old passwords and sessions stay unusable; the system user cannot be reactivated or modified this way; creation metadata is unchanged.
- [ ] Merged

### 6. Migration B3: account soft delete and the partial name index

- Scope: the `deleted` flag on accounts, the account and its balances leaving every view (including `live_accounts`), net worth history changing as it does today, the unique name index becoming partial (`WHERE deleted = 0`), and the delete confirmation wording. The spec rule that deleting an account permanently deletes its balances changes in the same pull request. Restore is v0.5.
- Tests: deleting an account frees its name; every balance query excludes deleted accounts; the spec and decisions entries are in the pull request.
- [ ] Merged

### 7. Migration C: change log, registry and `balances.version`

- Scope: `sys_operations`, `sys_operation_kinds`, `sys_record_changes` and `sys_audited_fields`, seeded by the migration; `balances.version` added with a plain `ADD COLUMN ... DEFAULT 0`; the chokepoint writing the log, with the writer sequence in the design; the registry loaded at startup.
- Tests: every write path produces its log row and the audit columns agree with the logged mutation; the first changed balance receives the allocated operation id and later ones share it; a no-op save creates no operation; a theme-only update changes audit metadata without a header; one change per record per operation (a repeat rolls the whole operation back); the schema test that every column of every non-`sys_` table has a registry row; every operation kind used by the code exists in the table.
- [ ] Merged

### 8. Import commit

- Scope: the wizard's final step. The dry run rejects duplicate normalized dates within the account and captures the expected state of each date it touches. The commit compares these inside `BEGIN IMMEDIATE` and rejects the whole import if anything differs.
- Tests: duplicate import dates fail before any write; an empty date becoming occupied, an expected record deleted or replaced, a version changing, and several records sharing an operation id each cause no writes and request a fresh preview.
- [ ] Merged

### 9. Export

- Scope: as in #80. Enables the round-trip test.
- [ ] Merged

### 10. Undo

- Scope: undo of balance changes. One evaluator for preview and commit; the confirmation bound to the previewed plan; a savepoint around each inverse; closed and deleted accounts skipped; an undo that reverts nothing does not count; a partial undo is final.
- Tests: the undo preview and confirmation, partial and failure cases, and account-state cases listed under "Test coverage the design requires" in the design.
- [ ] Merged

### 11. Epic closing

- Scope: the v0.1 to v0.2 upgrade across migrations A, B1 to B3 and C, backup and restore, the changelog's Breaking section (renamed duplicate accounts, deleting an account no longer deleting its balances, the renamed tables), and a release candidate rehearsal.
- [ ] Done
