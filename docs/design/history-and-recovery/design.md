# Balance history and deleted data recovery proposal

Status: scope agreed in discussion on November 14, 2026 for [issue #58](https://github.com/declankenny/northstar/issues/58). This is a design, not an implementation or a change to the current specification. See the [README](README.md) and the [implementation plan](implementation-plan.md).

## Decisions made in review

These were settled on November 14, 2026 and are written into the sections below.

1. **Deleted balances are recovered from the change log, with no soft-delete column.** Deleting a balance removes its row, and the `DELETE` entry in `sys_record_changes` holds every logged field. Restoring inserts a row from that entry through the writer. A `deleted` flag on `balances` would touch every balance query and view for no gain.
2. **A deleted account's retention clock is its `updated_at`** while `deleted = 1`. Deleting goes through the writer, which stamps it, and `deleted` is a logged field, so the log carries the same moment as a cross-check. No `deleted_at` column. This holds only while nothing writes to a deleted account's row, so a test must assert that, and any migration that rebuilds `accounts` must preserve `updated_at`.
3. **An individually deleted balance's clock is the operation time of its latest `DELETE` entry.**
4. **A balance is currently deleted** when the latest log entry for its record id is a `DELETE`. A restore writes a new `INSERT` under the original id, which `AUTOINCREMENT` guarantees is still free. This keeps the restored balance joined to its earlier history.
5. **Balances removed by an import undo are not listed in Deleted balances.** They were removed on purpose and as a group, and the existing rule (import the file again) covers putting them back. The list therefore excludes `DELETE` entries whose operation kind is `undo`.
6. **Restore needs new operation kinds**, `restore` and `purge` (a row each in `sys_operation_kinds`, as the lookup table allows), so the log says what was recovered and what was removed.
7. **Anything deleted before the log existed (before v0.2) is not recoverable.** This is part of what "restorable while retained" means.

## Purpose

Help household members understand how a balance changed and restore an earlier amount. Give admins a predictable place to recover accidentally deleted accounts and balances within a defined retention period.

The feature has three entry points: a history list on the existing balance screen, and **Deleted accounts** and **Deleted balances** beside each other in the admin left-hand navigation. Household members retain the existing permissions for live balance history and amount restoration; recovery of deleted records is admin-only.

## Balance history

Add a History list to the screen for an individual balance. This is the edit history of one account's balance on one date, distinct from the account's list of balances across dates.

Show the most recent change first. Each row shows:

- When the change happened.
- Who made it.
- The previous and resulting amounts, in the account's currency.
- The operation responsible, such as manual edit, CSV import or restoration, with the recorded import batch identifiable where applicable.
- A **Restore this value** row action for a historical amount different from the current amount.

The action targets the resulting amount shown in that row. Mark the current value clearly and do not offer a redundant restoration. Show the recorded baseline as the earliest known value; do not imply that changes before recording began are available. Note-only changes can remain visible as changes with an unchanged amount.

### Restoring a value

Selecting **Restore this value** shows the account, balance date, current amount and proposed amount before confirmation. For example: “Replace $1,250.00 with $1,100.00 for this balance?”

Confirmation records a new change by the person restoring the value. It does not remove or rewrite any history, or reverse the import or other operation that originally produced that value. Other dates and accounts are unaffected.

Restore the amount only, keeping the current note. The confirmation must make this clear. Record the restoration and its historical reference as provenance rather than presenting it as a new CSV import.

Apply the existing balance editing permissions and account restrictions. If the balance changes after the confirmation is opened, refuse the stale restoration, show the new current value and let the person review again. This follows the existing conflicting-edit rule rather than introducing selective undo.

## Deleted accounts

Add **Deleted accounts** to the admin navigation. Both the screen and its server actions are restricted to admins.

The list shows account name, account type, deletion date, scheduled permanent-deletion date and a **Restore account** row action. Show newest deletions first and a plain empty state when there are none.

Selecting **Restore account** asks the admin to confirm that the account and its retained balances will become available again. Restoration keeps the account's identity, currency, type and retained data, and records who restored it and when.

If another live account now uses the name, ask for a new name before restoring. Check the name again when saving and apply the same uniqueness rules as other account changes. Do not rename, merge with or replace the other account.

Preserve the account's previous open or closed state. Restoring a closed account does not reopen it. After success, remove it from Deleted accounts and open its account screen so the admin can inspect the result, even if the default Accounts filter would hide it.

Account recovery must not resurrect balances that were separately deleted before the account was deleted. It restores the account and the balances hidden by that account's deletion.

## Deleted balances

Add **Deleted balances** beside **Deleted accounts** in the admin left-hand navigation, rather than adding a secondary view to individual account screens. Both the screen and its server actions are restricted to admins.

List individually deleted balances across non-deleted accounts, with filtering by account. Show account name, balance date, amount in the account's currency, who deleted it, deletion date, scheduled permanent-deletion date and a **Restore balance** row action. Show newest deletions first and a plain empty state when there are none.

After confirmation, restore the deleted record, including its amount and note, and record who restored it and when in its history. Unlike restoring an earlier amount on a live balance, this recovers the deleted record as a whole.

If a live balance already exists for that account and date, refuse restoration without overwriting it. Show a link to the existing balance and keep the deleted entry available for inspection while retained. Recheck the account, date conflict and retained record when saving; a failure leaves everything unchanged.

Do not show balances belonging to a deleted account. Balances hidden by account deletion return through **Restore account**. Independently deleted balances remain deleted and become visible in **Deleted balances** after their account is restored, provided they are still retained.

For example, a household member mistakes January's savings balance for a duplicate and deletes it. An admin can find it by account and balance date here and restore it without needing the original statement. If someone has already entered a replacement for January, the admin can inspect both amounts rather than silently replacing the new entry.

## Scope boundaries

Included:

- Inspecting recorded changes to an individual balance.
- Explicitly restoring a historical amount as a new change.
- Admin recovery of a deleted account and its retained balances.
- Admin recovery of individually deleted balances.
- Configurable retention and scheduled permanent deletion of deleted data.

Excluded:

- Undoing arbitrary earlier operations while preserving or replaying later work.
- Partial batch undo, dependency resolution or operation rollback plans.
- A separate household-wide audit dashboard.
- Bulk restoration or a manual permanent-deletion interface.
- Automatic expiry of history for live balances.

The existing guarded import undo remains separate and unchanged. The broader deferred design in [undo/design.md](../undo/design.md) is not a requirement for this proposal. In-app recovery complements database backups and does not replace them.

## Retention and nightly cleanup

Use two admin-managed system properties in the `data` domain:

| Property | Type | Default | Meaning |
| --- | --- | --- | --- |
| `data.deleted.retention_days` | Positive whole number | 90 | Retention period for deleted accounts and individually deleted balances. |
| `data.deleted.cleanup_time` | Time, nullable | 03:00 | Daily cleanup start time in the installation's time zone. Unset disables automatic deletion. |

The retention clock starts at deletion. Restoring a record cancels its pending purge; deleting it again starts a new retention period. History for live balances has no automatic expiry.

An account and the balances hidden by its deletion remain recoverable throughout the account's recovery window. Their cleanup is governed by the account's deletion time, not an earlier balance change date. Balances individually deleted before the account was deleted retain their own deletion clock; hiding their account does not reset it.

Run cleanup through the existing daily scheduler, using its missed-run, locking and failure behavior. Each run permanently removes eligible deleted records. Purging an account also removes its retained balances and associated recovery history. Purging an individually deleted balance removes that record and its associated recovery history. Cleanup must remove recoverable values from the change log as well as the deleted rows, without removing history for unrelated records or live balances.

Recheck eligibility and deletion state in the same transaction as each purge so a restored record cannot be deleted based on a stale cleanup selection. A record remains restorable while retained; eligibility does not itself delete it before the cleanup job runs.

Show the scheduled permanent-deletion date in both deleted-data lists. With cleanup disabled, show that automatic deletion is disabled instead of promising a deletion date. A schedule is not a guarantee of execution if the app is stopped or a run fails.

Changing retention applies to already deleted data. Before saving a shorter retention period, explain that older deletions may become eligible at the next run. Re-enabling cleanup likewise makes already eligible data subject to the next scheduled run. Disabling cleanup does not reset deletion dates.

Existing backups keep their contents until they expire under their own retention policy; this job does not rewrite backups. Describe deleted records as **restorable while retained**, rather than always restorable.

## Acceptance criteria

- An individual balance screen lists all retained changes since its recorded baseline, with the actor, time, amounts and operation source where recorded.
- A historical amount can be restored after reviewing the current and proposed amounts, and appears as a new history entry without deleting intervening changes.
- A stale restoration cannot overwrite a change made after review.
- Amount restoration leaves the current note, other balances and unrelated records unchanged.
- Only admins can access either deleted-data list or restore its records, including through direct server requests.
- Restoring an account recovers its retained balances and preserves its identity and open or closed state, without reviving balances deleted independently beforehand.
- A reused account name requires a valid replacement name; a failed restoration leaves everything unchanged.
- Deleted balances can be filtered by account and restored with their notes and history; an existing balance on the same date prevents restoration without overwriting either record.
- Deleted balances belonging to deleted accounts are hidden from the list; restoring the account exposes any independently deleted balances that remain retained.
- Retention defaults to 90 days, cleanup defaults to 03:00 in the installation's time zone, and an unset cleanup time disables automatic deletion.
- Cleanup removes eligible deleted records and their recoverable history, preserves unrelated history, and never purges a restored record using a stale selection.
- Account balances remain recoverable for the account's full retention window; independently deleted balances keep their own deletion clock.
- Both deleted-data lists communicate scheduled permanent deletion or disabled cleanup, and shortening retention explains its effect before saving.
- History and recovery work after backup and restore and after upgrading from the supported preceding release, including the older-history baseline case.

## Implementation notes

The scope and defaults above are agreed. Do not expand this into general operation undo.

- **Restoring a balance from the log.** The row is rebuilt from the `DELETE` entry's `old_json` and written through `writer.insert`, so validation, the audit columns and the log apply. It needs the original id, so confirm that the writer accepts an explicit `id`. Unlogged fields (`updated_at`, `version`) are set fresh, and `version` becomes the restoring operation's id.
- **Schema drift.** The JSON holds the fields as logged at the time. If a later migration adds a required column to `balances`, an old entry lacks it, so the restore defines a default for each such field, and the upgrade tests include a balance deleted under the preceding release.
- **The Deleted balances query** looks up `DELETE` entries for `balances` with no later entry for the same record id, excluding the `undo` kind and balances of deleted accounts. The existing conflict check already scans with `json_extract` on `account_id`, which is fine at household volumes. Add an index on `sys_record_changes` only if a measurement says so.
- **The purge writes to the change log.** The writer refuses SQL writes outside it, so it needs a writer function for removing log rows of one record, not a raw `DELETE`. It removes every log entry for a purged record (its history as well as the `DELETE`), keeps the operation header of an import that touched several records until none remain, and never touches live balances or unrelated records. Check how existing operations that touched several records are recorded before writing it.
- **The shorter-retention warning.** Validators today only accept or refuse. The warning before saving is a new behaviour, so decide where it lives (in the property's editor, with the count computed by the server) before building step 3.
- **The cleanup job** is the second entry in `northstar/jobs.py`, with its own `sys_jobs` lock and the usual failure categories, and its start time in the Time property `data.deleted.cleanup_time`.
- **Closed accounts.** Restoring an amount on a closed account is refused, as for any balance change. Restoring a deleted balance into a closed account is refused for the same reason.
- **Baseline.** No baseline of earlier data is written, so the earliest known value of a balance that was never edited is synthesized from the live row, and a balance from before the log has `version` 0. The upgrade tests need a dataset for this case.
- **Spec and decisions.** The "Deleting" rule in the spec says restore is planned for v0.7 and that there is no way to bring an account back, and "Change log" says nothing reads the log. Both change in the pull requests that build them, with a decisions entry each.
