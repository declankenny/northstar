# Northstar v0.2: schema design

Nov 1, 2026 · Declan Kenny

This merges the earlier working notes, the change tracking proposal and the findings from three reviews.

## Status

The v0.2 schema direction is agreed in discussion, including change tracking. This is a work-in-progress design. It is not the spec or the decisions log, which change only with the code, and no code has changed. The order of the work is in [implementation-plan.md](implementation-plan.md).

- Agreed earlier: soft deletes for users and accounts, audit columns on every user-facing table, a system user, a rebuild-capable migration runner, a unique account name, the integer balance id and a version column.
- Agreed in the change tracking discussion: one operations table and one record-level change table with JSON diffs, a registry of audited fields, a single write chokepoint, a `sys_` prefix for tables the app writes for itself, no baseline rows, and balance undo in v0.2.
- Changed by the first review: the version is the id of the operation that wrote the balance, every non-`sys_` table gets `AUTOINCREMENT`, one transaction covers a whole operation, the `schema_migrations` rename happens after the backup, and migration A creates a full unique index that B later makes partial.
- Changed by the second review: at most one change per record per operation, a precise writer sequence, preview expectations that include absence, a savepoint around each undo inverse, undo skipping every closed or deleted account, a clearer claim about what the log records, and a rule for a stray empty old ledger after an app rollback.
- Changed by the third review: undo preview and commit share one evaluator and the confirmation is bound to the previewed plan, backup validation uses the same migration executor as upgrades, ledger cleanup is narrowly defined and ordered after the too-new check, the account name contract is `NOCASE` with application trimming, user reactivation is an explicit update, and several wording fixes.
- Still open: see "Deferred and open" at the end.
- Working rule: a large design like this one lives in its own folder in `docs/design`, and the issues link to it. The decisions log and the spec change only with the code.

## Context

Epic [#55](https://github.com/declankenny/northstar/issues/55) is v0.2, balance CSV import and export, and this schema work serves it. These features sit under it:

| Issue | Feature | State |
| --- | --- | --- |
| [#79](https://github.com/declankenny/northstar/issues/79) | CSV balance import into one account | Formats agreed; number format control to confirm |
| [#80](https://github.com/declankenny/northstar/issues/80) | Northstar CSV balance export | Stub, its own design |
| [#81](https://github.com/declankenny/northstar/issues/81) | Balance provenance and batch undo | Designed here; the issue links to this folder |
| [#82](https://github.com/declankenny/northstar/issues/82) | Unique account names | Updated to match this design |
| [#10](https://github.com/declankenny/northstar/issues/10) | Conflicting-edit detection | Uses the version column below |

Also in v0.2 with no schema change: #72, #78, #11, #12 and #13.

The order of the work is in [implementation-plan.md](implementation-plan.md).

## Decisions made

These are agreed in discussion. None is written into the spec or the decisions log yet; that happens with the code.

### Schema

| Topic | Decision | Why |
| --- | --- | --- |
| Unique account name | Unique among live accounts, case-insensitive and trimmed. The contract: comparison is SQLite `NOCASE` (ASCII case only, like `account_types.name` and `users.email`), trimming is what the application's `_clean_name` does (`strip()`), the index is on `name COLLATE NOCASE`, and application validation and future import matching compare the same way. The migration finds duplicates with the same SQLite comparison. Existing names were trimmed on write, so the migration asserts this and does not rewrite them. Names that differ only in non-ASCII case count as different. Migration A creates a full unique index, which is equivalent while nothing is soft-deleted. Migration B3 (account soft delete) swaps it for a partial index (`WHERE deleted = 0`) once `deleted` exists, with no rebuild. The migration renames later duplicates to "Name (2)" and so on: collect every existing normalized name first, go through duplicates in id order (the first keeps its name), give each later one the smallest `Name (n)` with n of 2 or more not in the set, and add it to the set. | Helps people, and the future multi-account import maps by name. Auto-rename so no one is stuck at startup. Deterministic and collision-free. |
| Soft delete, users | A `deleted` flag. Deleted users cannot sign in and are hidden from the list. Sessions are removed and the password hash made unusable. Re-adding the email reactivates the same row, as an explicit update through the writer: the id and creation metadata are kept, the password hash, display name and admin flag come from the create request (an explicit false stays false), the theme resets to the default, sessions stay revoked, the system user cannot be reactivated, and it is logged as one record update of the non-secret fields. Email stays globally unique. The admin rule counts live admins only. | History keeps pointing at a real person row, so the audit columns can be real foreign keys. |
| Soft delete, accounts | A `deleted` flag. The account and its balances leave every view, and net worth history changes as it does today. Restore is a v0.5 feature. | Removes the snapshot columns, the id-reuse problem and the cascade bypass. The spec rule that deleting permanently deletes balances changes. |
| Balances | Stay hard-deleted. The change log holds the old values. | A flag would touch every balance query on the money path. |
| Flag form | A bool with partial indexes, for example the unique name `WHERE deleted = 0`, not a leading index column. Reads go through views such as `live_accounts`. | A view stops a query forgetting the filter. At household scale speed is not the issue. |
| Audit columns | Every user-facing table gets `created_at`, `created_by`, `updated_at` and `updated_by`: accounts, account\_types, balances, users and account\_classes. Exempt: every `sys_` table (see below). A schema test enforces the rule. | One uniform rule. The log tables already carry their own author and time. |
| System user | A row in `users` flagged `is_system`, unique by a partial index. Reserved `.invalid` email, unusable hash, and an explicit refusal at sign-in with the same message and timing as an unknown email. Hidden from the interface, refused by the command line tools, found by the flag and never by id. It authors the seeded rows, the migration backfill and command line actions. | Gives `created_by` a value for existing rows without a real person. Any real system email belongs in a later System Properties table. |
| Stable ids | Every application-owned non-`sys_` table's integer key is `AUTOINCREMENT`, and so is `sys_operations`. A schema test enforces it. SQLite's own tables, such as `sqlite_sequence`, are excluded from all the schema rules. | An id is never reused, even after a hard delete (`balances`, `account_types`), so two unrelated histories can never share an id. Migration B1 rebuilds these tables anyway. |
| Balance key | Keep the integer id. | The natural key (account, date) already exists. Changing the key rebuilds the money table for little gain. |
| Date move | The app asks for confirmation before overwriting. One operation holds a `DELETE` of the balance it replaces (if any) and an `UPDATE` of the moving balance. The confirmation carries the moving balance's id and version, and the expected state of the target date: absent, or the id and version of the balance there. The commit refuses if anything differs. | Keeps the balance's id and history in one place. Nothing changed after the confirmation can be silently deleted or replaced. |
| Version | `balances.version` is the id of the operation that last wrote the balance. Existing balances get version 0, which is below every operation id. It is generated metadata: it never counts as a business change, and it has a registry entry with `is_logged` 0, because its value is already the operation id. | Operation ids only increase and are never reused, so a version is never reused, even when undo restores a deleted balance. It survives deletion and retention without a separate counter. `updated_at` has one-second resolution and could miss two edits in the same second. It is the conflict token for #10. |
| `sys_` prefix | A table written by the app for itself is prefixed `sys_`, carries no audit columns and is never logged. Every other table has the audit columns and a complete set of registry rows. | One rule for the schema test instead of exempt lists. Renaming is cheap before 1.0.0. |
| No renames from 1.0.0 | Database columns are not renamed from 1.0.0 onwards. Display names come from a Labels table, to be designed later. | Log rows keep the field names they were written with. |

### Change tracking

| Topic | Decision | Why |
| --- | --- | --- |
| Shape | One `sys_operations` row per user action and one `sys_record_changes` row per record changed, with the logged fields as JSON. Replaces the `operations`, `balance_changes` and `account_changes` draft. | Scales to transactions, budgets and loans without a change table per money table. One row per record keeps imports small and undo simple. |
| What the log claims | The change log records committed changes to fields marked as logged. Audit columns record row creation and the latest applicable update, including updates to unlogged fields. The log is authoritative for recorded changes, but is not a complete security-event log. | Password and theme changes are deliberately unlogged, so "everything that happened" overstated it. |
| Registry | `sys_audited_fields` lists every column of every non-`sys_` table with an `is_logged` flag, default 0. Seeded by migrations. A schema test fails if a column has no row. | A new table or field is an insert, not new code. A new column forces a decision, so a secret is never logged by accident. |
| Creation metadata | `created_at` and `created_by` are logged on every audited table. `updated_at` and `updated_by` are not. | Created fields never change after insert, so they only appear on INSERT and DELETE rows. A restored balance keeps its original creator, including a pre-upgrade balance. |
| Operation kinds | A lookup table `sys_operation_kinds` with a foreign key from `sys_operations.kind`. | SQLite cannot change a `CHECK` in place, so a new kind would mean rebuilding the table. |
| Write chokepoint | Every write to every table goes through a few database-layer functions. The first step is a registry lookup. | One place to enforce the log. Enforced by test, because SQLite cannot intercept writes globally. |
| Actor and operation | Each write takes the operation, which carries the actor. The operation is held in memory and its `sys_operations` row is inserted only when a logged change is about to be applied. `sys_` tables need no operation. | Plain functions, as in the existing decision. A theme change or password rehash updates the audit columns without leaving an empty operation behind. |
| One change per record | An operation makes at most one net change to a record, enforced by a unique constraint on `(operation_id, tablename, record_id)`. The final intended mutation is prepared before the writer is called. | Two changes to one balance would share a version, and reversing the later one would break the earlier one's version check. |
| One transaction | Creating the operation, the precondition checks, every write and the final counts run inside one `db.write_transaction` (`BEGIN IMMEDIATE`), joining an open one. | The existing rule: a check and the write that depends on it must not be separate statements. |
| Preview checks | A preview captures the expected state of each relevant `(account_id, as_of_date)` as absent, or the balance's id and version. The commit compares these inside `BEGIN IMMEDIATE` before any write, rechecks account eligibility, and rejects the whole import or move if anything differs, asking for a fresh preview. A previewed insert is never silently turned into a replacement. Expectations come from server state and are bound to the submitted import or move. | A version identifies an operation, not a record, and it cannot detect a date that was empty at preview and filled before commit. |
| No triggers for the log | A trigger cannot know the signed-in user or the operation without hidden connection state, and a static trigger would have to be regenerated whenever an audited column is added. | Separate from the existing decision that rejects triggers for invariants. |
| Baseline | Not written. Existing balances get version 0. | Undo restores from the old values on the later change rows. The creator and creation time come from the backfilled audit columns. |
| Undo | Ships in v0.2 for balance changes only. It runs through the normal write functions, so their rules apply. An undo operation cannot itself be undone. An operation is undone at most once, and the skipped list says what to fix by hand. Account changes are recorded, and restore is v0.5. | The scope valve is not used. Undo and restore are different features on different timelines. |
| Undo is atomic per record | Each inverse, with its data and change-log writes, runs inside a savepoint. An expected failure (a failed precondition or a business rule) rolls back to the savepoint and records a skip. An unexpected database or programming failure aborts the whole undo. | A caught exception in the middle of a multi-write inverse could otherwise leave part of it committed. |
| Undo outcome | The `undo` header is created inside the write transaction, outside the per-record savepoints, before the first inverse. If no row was reverted, the transaction rolls back, nothing persists and the attempt does not count, so the user can fix the cause and retry. If at least one row was reverted, the undo commits and is final. The detail JSON holds the reverted count and the skipped record ids with stable reason codes. | A header with no effect would use up the only undo for nothing. A partial undo is final, so the preview shows what would be skipped before the user confirms. |
| Undo preview | Preview and commit use one evaluator that processes the inverses in reverse order, each evaluated against the state left by the preceding successful inverse. Preview runs the real inverse logic in a write transaction and always rolls it back, so it leaves no rows, header or marker, and the transaction is not held open while the user decides. | A preview that checked each row against the starting state would wrongly skip the replaced balance in a date move, whose old date is only free after the moving balance goes back. |
| Undo confirmation | The confirmation is bound to the target operation and a server-derived plan: record identities, versions or absence, account eligibility and the predicted reverted and skipped sets. The commit recomputes the plan inside `BEGIN IMMEDIATE` and rejects any difference, whether more or fewer rows became eligible, and asks for a fresh confirmation. A partial undo commits only if the user confirmed that partial plan. | Rechecking each inverse protects later work, but could turn a previewed full undo into a final partial one the user never confirmed. |
| Closed and deleted accounts | The balance functions reject every change on a closed account, so undo skips every inverse on a closed or deleted account. Reason codes differ, and the preview tells the user to reopen a closed account before confirming. | Preserves today's rule. Restoring a deleted account is v0.5. |
| Retention | Waits for #58 (v0.5), with the System Properties table. Operation header rows are kept when change rows are purged. | v0.2 only needs to record. The design must not block a later purge. |

## Migration runner

Decided: build a runner that can rebuild tables safely, as its own feature before the schema work that needs it.

Why. SQLite's `ALTER TABLE ... ADD COLUMN` cannot add a `NOT NULL` foreign-key column while foreign keys are on, because a new foreign-key column must default to `NULL`. Enforcing `created_by` and `updated_by` in the schema therefore means rebuilding the tables. The same rebuild is needed for any later change beyond adding a column: tightening a constraint, changing a foreign key, adding `AUTOINCREMENT`, or making a unique rule partial on an existing column such as the users email. Currency (v0.3), transactions and budgets are likely to need it.

Today. The runner (`migrate` in `db.py`) runs each file with `executescript` inside one `BEGIN`/`COMMIT`, with foreign keys on. `PRAGMA foreign_keys = OFF` has no effect inside a transaction, so a table cannot be dropped and recreated safely there.

What it needs (an outline, not a design):

- Foreign keys off around a rebuild migration, set before the transaction begins.
- `PRAGMA foreign_key_check` and row-count checks before commit, rolling back on any failure.
- The pre-migration backup stays, and the backup check keeps deriving the required tables from the migrations.
- An explicit per-migration opt-in, so ordinary migrations keep today's behaviour.
- The `schema_migrations` rename, in this order: read the recorded versions from either name without changing anything, classify the database (a read of the new name alone would call an existing database "empty" and skip the backup), create and validate the backup, then rename inside the migration transaction. The backup check accepts either name, so a backup made before the rename still restores.
- When both ledgers exist, classification is one read-only phase, and a database that is too new is refused before anything is dropped. The new ledger is authoritative only if it has the expected structure and a valid recorded history, and the old ledger is accepted for cleanup only if it has the expected legacy shape and zero rows (the empty ledger an older app leaves behind, so nothing is lost). Any other combination is refused with a clear message and nothing deleted: two empty ledgers, a malformed ledger, a populated old ledger. Accepted cleanup is transactional. With migrations pending it follows the validated backup. If the database is already current it is its own recovery transaction.
- One migration executor, taking a connection and an ordered set of migrations, used for real upgrades and for the scratch replay that `backup._tables_for` does to derive the required tables. It handles ledger initialization, the rename and any Python steps, and replays only the migrations in the backup's recorded history, as today. Backup creation, filesystem work and startup recovery stay outside it. Today the scratch replay runs the SQL files directly with no ledger, so it would not reproduce a rename done in runner code.
- After every rebuild, successful or failed, restore and verify `PRAGMA foreign_keys`, run `foreign_key_check` and the integrity check before commit, preserve the required indexes and views, and test failures while copying and validating. Row counts alone are not enough.
- Possibly Python steps for data backfills that need logic. To decide.

To verify on a copy of a database before relying on it: the SQLite limit above, and how a rebuild behaves under the app's real foreign keys.

## Schema, table by table

Today is migration 0001 (plus 0002 for `login_attempts`). Every non-`sys_` table also moves to `AUTOINCREMENT`.

| Table | Today | Proposed |
| --- | --- | --- |
| account\_classes | id, name. Two fixed rows. | `AUTOINCREMENT`, four audit columns, owned by the system user. |
| account\_types | id, name (unique, nocase), class\_id, stale\_after\_days, created\_at. Hard-deletable when unused. | `AUTOINCREMENT`, four audit columns. Stays hard-deletable. |
| accounts | id, name, class\_id, type\_id, is\_open, notes, created\_at. Composite foreign key to account\_types. | `AUTOINCREMENT`. Unique name (full index in A, partial among live accounts in B3), `deleted`, four audit columns. |
| balances | `id INTEGER PRIMARY KEY`, account\_id, as\_of\_date, amount\_cents, note, source, created\_at, updated\_at. Unique per account and date. | `AUTOINCREMENT` and four audit columns (rebuilt in migration B), then `version` (added in migration C). Stays hard-deleted. |
| users | id, email (unique), display\_name, password\_hash, is\_admin, theme, created\_at | `AUTOINCREMENT`, `deleted`, `is_system`, four audit columns. |
| sessions | token\_hash, user\_id, created\_at, expires\_at | Renamed `sys_sessions`. |
| login\_attempts | Added by migration 0002 | Renamed `sys_login_attempts`. Its columns were not reviewed for this note. |
| schema\_migrations | version, applied\_at | Renamed `sys_schema_migrations`. Needs the runner steps above. |
| sys\_operations | New | See change tracking. |
| sys\_operation\_kinds | New | See change tracking. |
| sys\_record\_changes | New | See change tracking. |
| sys\_audited\_fields | New | See change tracking. |

Because neither accounts nor users is ever hard-deleted, the audit columns and the change log can carry real foreign keys to them, with no name snapshots.

## Change tracking

### What the log is for

| Feature | What it needs |
| --- | --- |
| Import, #79 | An import recorded as one batch, with the value of every balance it replaced. |
| Provenance and batch undo, #81 | Who, when, which operation, what was replaced. Undo of a whole batch that never overwrites later work. |
| Conflicting edits, #10 | `balances.version`, the id of the operation that last wrote the balance. |
| History and recovery, #58 (v0.5) | History screens, restore of earlier values and deleted accounts, and retention, all built on this record. |

The change log records committed changes to fields marked as logged. The audit columns on each row record row creation and the latest applicable update, including updates to unlogged fields such as a theme change. The log is authoritative for recorded changes, but it is not a complete security-event log. For a logged mutation, the audit columns and the log are written by the same function from the same operation, and a test checks that they agree. The test does not require the current row's updater to equal the most recent logged actor, because an unlogged update can come after.

### The `sys_` prefix

A `sys_` table is written by the app for itself. It has no audit columns and is never logged. Every other table has the four audit columns and a full set of registry rows. The schema test checks exactly that.

| Today | Becomes |
| --- | --- |
| `sessions` | `sys_sessions` |
| `login_attempts` | `sys_login_attempts` |
| `schema_migrations` | `sys_schema_migrations` |
| new | `sys_operations`, `sys_record_changes`, `sys_operation_kinds`, `sys_audited_fields` |

A future System Properties table is decided when it is designed: if users can change its settings and those should be audited, it should not carry the prefix.

### `sys_operations`

One row per user action that writes a logged change.

| Column | Type | Notes |
| --- | --- | --- |
| id | integer, primary key, `AUTOINCREMENT` | Also the version written onto the records the operation changes. |
| kind | text, not null | References `sys_operation_kinds`. The origin of the action. |
| user_id | integer, not null | References `users`. The system user for command line actions. |
| created_at | text, not null | Same timestamp format as other rows. Indexed, so a later purge by age is cheap. |
| undoes_operation_id | integer, null | References `sys_operations`. Set only on an `undo`. A partial unique index enforces one committed undo per target. Application validation inside the transaction rejects a target whose kind is `undo`; the index does not establish that. |
| detail | text, null | JSON. For an import: file name, mapping summary, conflict policy, counts of added, replaced, skipped and unchanged. For a bulk update: the date. For an undo: the reverted count and the skipped record ids with reason codes. Never the contents of an uploaded file. |

### `sys_operation_kinds`

A lookup table, seeded by migrations, in the same way as `account_classes`. A foreign key from `sys_operations.kind` replaces a `CHECK`. Adding a kind is a one-row insert. A schema test asserts that every kind the code uses is in the table.

Proposed kinds, origin-based because the verb is on the change row: `ui_edit`, `bulk_update`, `import`, `undo`, `cli`. `integration` joins later for SimpleFIN. A label such as "Deleted account" is worked out from the change rows, not stored.

### `sys_record_changes`

One row per record inserted, updated or deleted.

| Column | Type | Notes |
| --- | --- | --- |
| id | integer, primary key | Orders changes within an operation. |
| operation_id | integer, not null | References `sys_operations` |
| tablename | text, not null | |
| record_id | integer, not null | The record's `id`. No foreign key: the table is polymorphic. |
| change | text, not null | `INSERT`, `UPDATE` or `DELETE` |
| old_json | text, null | The logged fields before. Null for `INSERT`. For `UPDATE`, only the fields that changed. For `DELETE`, all logged fields, including `created_at` and `created_by`. |
| new_json | text, null | The logged fields after. Null for `DELETE`. For `UPDATE`, only the fields that changed. For `INSERT`, all logged fields. |

Indexes: `(tablename, record_id, id)` for the history of one record, `(operation_id)`, and a unique constraint on `(operation_id, tablename, record_id)`.

The version a record has after a change is the id of the operation, so no separate column is needed. A `DELETE` leaves no record to carry a version.

Rules:

- Values in the JSON keep their types, so integer cents stay integers.
- At most one row per record per operation. A second mutation of the same record in one operation makes the writer roll the whole operation back. A date move is valid because it changes two different records.
- A change only to unlogged business fields updates the row and its audit columns without a change-log row. If no business field changes, nothing is written.
- Rows are appended and never updated or deleted by the app. Purging is the retention question for v0.5 (#58). Nothing in the design may block it: no foreign key points into this table, `created_at` on the operation is indexed, and operation rows are kept when change rows are purged, so ids and versions are never reused.

### `sys_audited_fields`

The registry. One row for every column of every non-`sys_` table.

| Column | Type | Notes |
| --- | --- | --- |
| tablename | text, not null | |
| fieldname | text, not null | |
| is_logged | integer, not null, default 0 | 1 to record changes to the field, 0 (the default) to ignore it. Declared as `INTEGER NOT NULL DEFAULT 0 CHECK (is_logged IN (0, 1))`, like `is_open` and `is_admin`. |

Primary key `(tablename, fieldname)`. The rows are seeded by the migrations, as plain inserts.

- `is_logged` 0 is for secrets, noise and generated metadata: `users.password_hash`, `users.theme`, `updated_at`, `updated_by` and `balances.version`. `created_at` and `created_by` are logged, so a restore keeps them.
- A schema test fails if any column of any non-`sys_` table has no row, so a new column forces a decision. A forgotten secret cannot be logged by accident, and a money column cannot be silently unlogged.
- The registry is loaded into memory at startup, so the lookup on every write costs nothing.

### The write chokepoint

All writes go through a small set of database-layer functions: insert, update and delete, plus a batch form for imports so 20,000 rows run in one transaction. Each takes the operation that the write belongs to. Inside the operation's write transaction, the sequence is:

1. Read the existing state, validate preconditions, and calculate the diff of the business fields. The final intended mutation of each record is prepared before the writer is called.
2. If no field changed at all, return "unchanged" and touch nothing: no version, no audit columns, no header.
3. If only unlogged fields changed (a theme change, a password rehash), update the audit columns from the in-memory actor, and allocate no header.
4. If a logged change is needed, insert the `sys_operations` row if it has not been allocated yet.
5. Apply the record mutation and the audit columns, and set `version` to the operation's id where the table has one.
6. Append the `sys_record_changes` row, and finalize the operation's counts before commit.

The operation is created first and passed to each write. It carries the actor, so there is no separate actor argument and no hidden connection state. The system user is the actor for command line tools. Writes to `sys_` tables (sessions, failed-login tracking) need no operation.

The whole operation is one write transaction: creating the operation, the precondition checks, every write and the final counts run inside `db.write_transaction`, which joins a transaction that is already open.

Enforcement is by test, because SQLite cannot intercept writes globally: a test drives every write path and asserts the log row appears, and a second test fails on any SQL that writes to any table outside the chokepoint. Migrations are the exception.

### How it works together

**A three-row import with one replacement.** One `sys_operations` row (`import`, detail has the file name and counts). Three `sys_record_changes` rows: two `INSERT` and one `UPDATE` carrying the old amount, note and source and the new ones. Each balance's `version` is the operation's id. The dry run rejects duplicate normalized dates within the selected account and names the source CSV rows, so one balance is never changed twice in an operation. It also captures the expected state of every date it will touch: absent, or the balance's id and version. The commit compares these inside `BEGIN IMMEDIATE` before any write, and rejects the whole import if anything differs. Where the preview is stored, how it expires and how a conflict is shown are left to #79.

**A date move.** The app asks for confirmation before overwriting. The confirmation carries the moving balance's id and version and the expected state of the target date. If anything differs at commit, nothing is written and the user is asked to confirm again. If another balance sits on the target date, the operation has two rows: a `DELETE` of the balance it replaces, then an `UPDATE` of the moving balance with the new `as_of_date`. The delete comes first because of the unique `(account_id, as_of_date)`.

**Deleting an account with 200 balances.** One operation and one `UPDATE` row on `accounts` (`deleted` 0 to 1). The balances stay in place and drop out of every view with the account. Restore is the reverse, in v0.5.

**Undo of a balance operation.** The user first sees a preview of which rows would be reverted and which would be skipped, with the reasons, and is told that a partial undo is final. The preview comes from the same evaluator the commit uses: inside a write transaction it runs the real inverses in reverse order, each against the state the earlier ones left, collects the result and always rolls back, so it leaves no rows, header or marker. The confirmation is bound to the target operation and that plan. On confirm, inside `BEGIN IMMEDIATE`, the app recomputes the plan and rejects any difference (more or fewer rows eligible, a changed version, an account closed or reopened), asking for a fresh confirmation. Then, in the same transaction, the app validates that the target is a non-undo operation that has not been undone, creates the `undo` header outside the per-record savepoints, and walks the operation's balance rows in reverse. Each inverse runs inside its own savepoint. A row is reverted only if the balance still matches what the operation left:

| Original change | Precondition | Inverse |
| --- | --- | --- |
| `INSERT` | The balance exists and its version is this operation's id | Delete it |
| `UPDATE` | The balance exists and its version is this operation's id, and for a date change the old date is still empty | Restore the old values |
| `DELETE` | No balance exists at that id or at that account and date | Reinsert it with its original id, `created_at` and `created_by` |

A restored balance takes the undo operation's id as its version, which is higher than anything before it. So undoing the original import afterwards finds a version that no longer matches and leaves it alone.

Undo runs through the normal write functions, so their rules apply. An inverse is skipped, with a stable reason code, if its precondition fails, if its account is closed or deleted, or if the write would break a rule. Expected failures roll back to the savepoint and record the skip. An unexpected database or programming failure aborts the whole undo. Later work is never overwritten silently.

Outcome. If no row was reverted, the transaction rolls back, nothing persists and the attempt does not count: the user is told why and can fix the cause (for example, reopen a closed account) and retry. If at least one row was reverted, the undo commits with its detail JSON and is final: an operation is undone at most once, skipped rows cannot be retried, and an `undo` operation cannot itself be undone, so redoing means entering the data again.

Reversing the order matters for a date move: the moving balance goes back first, which empties the new date, and then the replaced balance is reinserted. v0.2 undoes balance changes only. If an operation holds both account and balance changes, the balance rows are undone and the account rows are listed as not reverted. Account changes are recorded, and restore is v0.5.

### Prerequisites in the schema

- **`AUTOINCREMENT` on every non-`sys_` table and on `sys_operations`.** Today these are plain `INTEGER PRIMARY KEY`s (migration 0001), so deleting the highest id lets SQLite reuse it. `balances` and `account_types` are hard-deleted, so a reused id would join two unrelated histories. Undo of a delete reinserts the original id. SQLite cannot add `AUTOINCREMENT` to an existing table, so the tables are rebuilt. This fits migration B and the rebuild runner.
- **`balances.version`**, the id of the operation that last wrote the balance, with 0 for balances that existed before the upgrade. It is added in migration C with a plain `ADD COLUMN ... DEFAULT 0`, because it needs `sys_operations` to exist and needs no rebuild.
- **The audit columns, system user and soft deletes**, as above.
- **The baseline is dropped.** The #55 wording that the upgrade "records" existing balances should be reworded.

### Risks and things to verify

- **Renaming `schema_migrations`.** The runner creates the table by name with `CREATE TABLE IF NOT EXISTS`, outside the migration transaction, and writes the version row with the name hardcoded in the script. The ordering described under the runner (read either name, classify, back up, then rename) is what keeps the backup before any change. `backup.py` and the tests also read the name.
- **Rolling back the app.** An older app on a renamed database cannot see the recorded versions, so it creates an empty `schema_migrations` and then fails at migration 0001. The failure is expected to roll back, but the empty ledger stays, so it does not fail "before any write". v0.2 handles that under the classification rules in the runner section: only an empty old ledger of the legacy shape beside a valid populated new one is dropped, and only after the too-new check; every other combination is refused. A backport guard to the 0.1 branch is optional and cannot help people on the original releases. The documented recovery is still to restore the pre-migration backup. Needs a test: upgrade a v0.1 database, start the original v0.1 code, then restart v0.2. Verify the old app refuses or fails clearly, changes nothing else in the database, and does not stop v0.2 reopening it. Also test: a database from a future version with a stray empty old ledger is refused without mutation; two empty ledgers, a malformed ledger and two populated ledgers are refused without deletion; and a failure during cleanup or upgrade leaves no partial recovery.
- **Volume.** A large import is one record-change row per record, not per field. Retention (v0.5) can bound record-change storage. Operation headers and their detail JSON, including file names and skipped-id lists, are kept indefinitely, and pruning them is deferred to #58.
- **No foreign keys on `tablename` and `record_id`.** Tests cover this instead.
- **JSON in SQLite.** Confirm `json_extract` is available in the SQLite build the container ships. TODO: not checked.
- **Duplicate names.** Tests cover case variants, leading and trailing whitespace, an existing `Name (2)` and representative non-ASCII names, and check that the migration's collision detection and the final index give the same answer. `accounts._clean_name` has no length limit, so a suffix cannot exceed one. The table definition itself was not checked.

### Test coverage the design requires

- Duplicate import dates fail before any write. A repeated mutation through the writer rolls the whole operation back. A date move with replacement still produces two changes for distinct record ids and undoes correctly.
- The first changed balance receives the allocated operation id and later ones share it. A no-op save creates no operation and changes neither version nor timestamps. A theme-only update changes audit metadata without a header. A logged edit followed by a theme change leaves history with only the edit and the audit columns showing the later update.
- Preview checks: an empty date becoming occupied, an expected record deleted or replaced, a version changing, and several records sharing an operation id. Each mismatch causes no writes and asks for a fresh preview.
- Undo: all-skipped (nothing persists, retry allowed), partly successful and fully successful (each blocks a second attempt), and an unexpected failure rolling back the header and every inverse. An expected failure injected after an inverse's first write leaves no part of that inverse while other eligible inverses commit. All inverse kinds against open, closed and deleted accounts.
- Undo preview and confirmation: a date move with replacement previews and commits both inverses when nothing intervenes; if moving the first balance back is blocked, the replaced balance's restore is evaluated against the resulting state; preview leaves no rows, headers or logs; preview and commit classify the same when state is unchanged; an intervening edit that turns a full undo into a partial one commits nothing; closing or reopening an account after preview requests a fresh confirmation; an unchanged, explicitly confirmed partial plan commits and becomes final; two concurrent confirmations cannot both commit.
- Backup validation: a pre-upgrade backup validates and restores with the new app; backups validate after each migration boundary (B and C); a rename done through the executor is exercised; a backup missing a table required by its recorded migrations is still rejected.
- User reactivation: a formerly admin user re-added without an admin request is a regular user; old passwords and sessions stay unusable; the system user cannot be reactivated or modified this way; creation metadata is unchanged.
- Rebuilds: foreign-key enforcement is restored after success and failure; failures while copying and validating roll back cleanly.

### Alternatives considered

- **Typed change tables per money table** (`balance_changes`, `account_changes`, later `transaction_changes`). Typed columns, but a new table and new undo logic for each money table.
- **One row per changed field.** Simple, but a large import makes several rows per record, and undo has to regroup them.
- **A snapshot of the whole row on each change.** Wasteful, awkward for diffs, and risks copying secrets from `users`.
- **`updated_at` as the conflict token.** One-second resolution can miss two edits in the same second.
- **A per-balance version counter.** A restored balance would need a version above every earlier one, so the counter would need its own home that survives deletion and retention. Using the operation id removes the problem.
- **Persisting an undo header even when every row is skipped.** It would use up the only undo for an attempt that did nothing. An all-skipped attempt commits nothing instead.
- **Keeping `schema_migrations` as an exception to the `sys_` rule.** It would avoid the rollback case entirely, but leaves a permanent exception. Renaming is cheap before 1.0.0, and the stray empty ledger is handled.
- **Triggers to write the log.** See the decision table above.
- **Connection-scoped actor.** Hidden state, and a write without it is logged with no author.

### Decisions to record with the code

- Changes are recorded per record with the changed fields as JSON, in `sys_operations` and `sys_record_changes`. The log records committed changes to logged fields and is not a complete security-event log.
- Every write goes through the database-layer functions. The registry (`sys_audited_fields`) and the operation kinds are tables.
- A balance's version is the id of the operation that last wrote it. An operation makes at most one net change to a record.
- Every non-`sys_` table, and `sys_operations`, uses `AUTOINCREMENT`.
- A commit rejects an import or date move whose previewed state (absent, or id and version) has changed.
- Triggers were considered for the log and rejected, for the reasons above. This is separate from the existing decision that rejects triggers for invariants.
- The `sys_` prefix marks tables written by the app for itself.
- Database columns are not renamed from 1.0.0 onwards. Display names come from a Labels table, to be designed later.
- Baseline rows are not written.
- Undo is atomic per record, an undo that reverts nothing does not count, a partial undo is final, an undo cannot be undone, and v0.2 undoes balance changes only. Restore is v0.5.
- Undo preview and commit use one evaluator, and the undo confirmation is bound to the previewed plan.
- Account names compare with SQLite `NOCASE` and are trimmed as the application trims them.
- Reactivating a user is an explicit update: the request sets the password, name and admin flag, and the theme resets.

## What changes elsewhere

- The issues link to this folder instead of carrying copies of the design.
- #81 covers provenance and batch undo of balance changes, with no baseline.
- #82 (unique account names) stays migration A, with a full unique index, the name contract and the deterministic rename. B3 makes the index partial.
- #79 gains the duplicate-date rejection and the preview expectations as acceptance criteria. Preview storage, expiry, transport and conflict presentation stay with #79.
- The user soft-delete issue gets the reactivation rules as acceptance criteria.
- The #55 "done when" no longer needs baseline rows on upgrade.
- The retention setting and the System Properties table wait for #58.

## Deferred and open

Open from change tracking:

- Confirm `json_extract` is available in the container's SQLite.
- Run the rollback test described under the risks, with the original v0.1 code.

Deferred:

- The statement-checkpoint decision from #55.
- The wording of the delete confirmation, now that deletes are soft. Purging and retention are #58, including pruning operation header detail.
- The migration split, now in the implementation plan: A the unique name; B1 the system user, audit columns, `AUTOINCREMENT` and the `sys_` renames, then B2 user soft delete and B3 account soft delete with the partial name index; C `sys_operations`, `sys_operation_kinds`, `sys_record_changes`, `sys_audited_fields` and `balances.version`. The runner, including the `schema_migrations` steps, is its own feature before B1.
- The number format control on #79, and the preview storage and conflict presentation.
- A System Properties table for settings such as a system email and the log retention period (#58).
- The Labels table that supplies display names.

New issues likely once this is approved: user soft delete with the system user, account soft delete, the runner, the audit columns, the `sys_` renames, and the change log with the write chokepoint.
