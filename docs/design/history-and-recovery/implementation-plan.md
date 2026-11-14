# History and recovery: implementation plan

Five steps after a preparation step, each its own branch and pull request into `main`, one merged before the next starts. A step is done when its issue is closed. The step issues are under the v0.7 milestone and part of #58.

| Step | What | Issue |
|---|---|---|
| 0 | Reconcile #58 with the agreed scope (no code) | [#58](https://github.com/declankenny/northstar/issues/58) |
| 1 | History list on the balance screen, read only | [#267](https://github.com/declankenny/northstar/issues/267) |
| 2 | Restore this value | [#268](https://github.com/declankenny/northstar/issues/268) |
| 3 | Retention properties and the cleanup job | [#269](https://github.com/declankenny/northstar/issues/269) |
| 4 | Deleted accounts | [#270](https://github.com/declankenny/northstar/issues/270) |
| 5 | Deleted balances | [#271](https://github.com/declankenny/northstar/issues/271) |

The order puts the cleanup job before the two recovery screens, so nothing ships that holds recoverable data without a way to purge it.

## Step 0: #58

- Remove "Undoing an earlier operation preserves later work" and the references to the deferred undo design.
- Change the "Done when" line on a deleted account to cover its balances, and add deleted balances.
- Link this folder and the new step issues.

## Step 1: history list

- **Scope:** the server function that reads a balance's changes from the log (actor, time, resulting amount, operation kind, import file name, whether the note changed), the History list on the balance screen with its When, By, Amount, Current and How columns, the synthesized earliest row, and note-only changes shown with an unchanged amount. It starts with the spike on listing a view over `sys_record_changes` (see `design.md`).
- **Tests:** a balance never edited, edited, replaced by an import, restored later; a balance from before the log (`version` 0); a balance of a closed account; permissions.
- **Docs:** the spec's "Change log" sentence that nothing reads the log, a decisions entry.

## Step 2: restore this value

- **Before it starts:** the review of the existing lists' row actions (see `design.md`, "Review of the existing lists"), a table in this folder. TODO: its own issue.
- **Scope:** the row actions declaration for `ListConfig` (a fixed array, one action drawn as a button), then the `restore` operation kind, the amount-only restore with the confirmation text, the stale check by version in the same transaction, the record of the historical reference as provenance, and the refusal on a closed account.
- **Tests:** current note kept, other dates and accounts unchanged, a stale confirmation refused with the new value shown, the current value offers no restore.
- **Docs:** the spec rule, a decisions entry, the changelog.

## Step 3: retention and cleanup

- **Scope:** migration for `data.deleted.retention_days` and `data.deleted.cleanup_time` and their validators, the `purge` operation kind, the writer function for removing log rows of one record, the cleanup job in `northstar/jobs.py`, the recheck of eligibility and deletion state inside each purge transaction, and the shorter-retention warning.
- **Open before it starts:** where the warning lives (see `design.md`), and how operations that touched several records are recorded and kept.
- **Tests:** an account and its balances purged together on the account's clock, an independently deleted balance on its own clock, a restored record not purged from a stale selection, unrelated and live history untouched, cleanup disabled, a missed run.
- **Docs:** the spec rules, `docs/schema.md` if the schema changes, the operator guide's backup wording, a decisions entry, the changelog.

## Step 4: deleted accounts

- **Scope:** the admin Deleted accounts screen and its server actions, the scheduled-deletion date or the disabled-cleanup text, restore with a name check at save time, the open or closed state kept, and opening the restored account.
- **Tests:** a reused name, a closed account stays closed, balances deleted before the account are not revived, admin-only on direct requests, a test that nothing writes to a deleted account's row.
- **Docs:** the spec's "Deleting" rule, a decisions entry, the changelog.

## Step 5: deleted balances

- **Scope:** the admin Deleted balances screen with an account filter, restore from the log under the original id, the date-conflict refusal with a link to the existing balance, and exclusion of `undo` deletions and of deleted accounts' balances.
- **Open before it starts:** that the writer accepts an explicit `id`, and the defaults for fields added after a balance was deleted.
- **Tests:** a conflict on the same date, restore into a closed account refused, a balance of a restored account appearing in the list, backup and restore, and upgrade from the preceding release with a balance deleted under it.
- **Docs:** the spec rule, a decisions entry, the changelog.
