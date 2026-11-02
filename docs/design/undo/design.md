# Undo: design

Nov 2, 2026 · Declan Kenny

## Status

Part 1 is the design for v0.2, agreed in discussion. Part 2 is the fuller design that was written for v0.2 inside [the schema design](../v0.2-db-schema/design.md) and then deferred. It is kept here as it was written, so the work to come starts from it. This is not the spec or the decisions log, which change only with the code. The order of the work is in [implementation-plan.md](implementation-plan.md).

## Part 1: an import register, and undo for imports (v0.2)

### In brief

Admins get an **Imports** page listing every past import. Each import that has not been undone has an **Undo** button. Undo is **all or nothing**: it reverts the import only if every balance the import wrote is still exactly as the import left it. If any is not, it refuses, names the dates, and the admin fixes those by hand. Nothing else can be undone in v0.2: single edits, Update saves and account changes are fixed by hand.

### Decisions

1. **No new table.** The register reads `sys_operations` (`kind = 'import'`). One field is added to the import's `detail` JSON: `account_id`.
2. **Imports only.** No undo of single edits, Update saves or account changes. Fixing those by hand is as quick as undoing them would be.
3. **All or nothing.** No partial undo, no skip list, no "a partial undo is final" rule.
4. **Admin only**, for viewing the register and for undoing. Any admin can undo any import.
5. **Where it lives:** an Imports link in the sidebar's Admin group, under Account types and Users, at `/imports`.
6. **Two pull requests:** the register, then undo.

### The register

A table, newest first, the newest 25 with a line saying so if there are more. Columns:

| Column | Source |
| --- | --- |
| Import Date | `sys_operations.created_at`, shown as a date only (the UTC date, until the app's timezone work) |
| Import By | the user's display name (a deleted user still shows) |
| Account | `detail.account_id`, shown as the account's current name and linked to it; "(deleted)" if the account was deleted |
| File Name | `detail.file` (the base name only; never folders or contents) |
| Added | `detail.counts.added` |
| Replaced | `detail.counts.updated` |
| Status | "Reverted on *date*" with no button, or an **Undo…** button |

Only imports that wrote something appear: an import with nothing to write creates no operation. There is no detail page. The page shows no balance amounts. An import whose rows were all deleted by hand stays in the register, and undoing it is refused ("deleted since"); this is accepted as an extreme edge case.

### Undo

**What it does.** For the import's changes (found through `sys_record_changes` for that operation, table `balances`):

| The import did | Undo does |
| --- | --- |
| Added a balance (INSERT) | deletes it |
| Replaced a balance's amount, note and source (UPDATE) | puts the old amount, note and source back |

An import never moves a date and never deletes, so the date-move and re-insert cases in Part 2 do not arise.

**When it is allowed.** Every one of the import's balances must pass all of these, or nothing happens:

- It still exists.
- Its `version` is still this import's operation id (nothing has written it since: no edit, no later import, no Update save).
- Its account is open (the balance functions refuse changes on a closed account). A deleted account is refused too.
- The import has not been undone already (the unique index on `undoes_operation_id` enforces one undo per import).

**When it is refused.** A 409 lists up to 10 dates with a reason each ("edited since", "deleted since", "changed by a later import", "account is closed: reopen it first"), then "and N more". Nothing is written. The admin fixes those balances by hand and tries again. This is the same pattern as the import commit's refusal.

**Two steps, so the person sees the effect before confirming.**

1. `GET /api/imports/{id}/undo` answers what undoing would do ("delete 297 balances, restore 3, in Demo Savings") or why it cannot. It writes nothing.
2. `POST /api/imports/{id}/undo` does it. Inside `BEGIN IMMEDIATE` it repeats every check, so a change between the two steps is a refusal, never an overwrite. One transaction, all or nothing.

The confirmation states the counts, that an undo cannot be undone, and that an import is undone only once.

**What it records.** One `sys_operations` row of kind `undo`, with `undoes_operation_id` set to the import and `detail` holding the counts. Every delete and restore goes through the normal write functions, so it is in the change log like any other change. Restored balances take the undo's id as their version. An undo cannot be undone: redoing means importing the file again.

### Access

- Server: the register routes and the undo routes use the same `require_admin` check as the import routes (403 otherwise).
- Interface: the Imports link is shown only to admins, and the page shows "Only admins can see imports." to anyone else, as Account types and Users do.
- An ordinary user's edit to an imported balance blocks an undo of that import. The rule is about the data, not the person.

### Changes to the code

- `balance_import.py`: add `account_id` to the import operation's `detail`. No migration (the column is JSON). No import has run outside throwaway test containers, so no older record lacks it; the register shows "unknown" for a row without it, defensively.
- A new plain module for the register and the undo, with no web code, and a new routes module. A new error for a refused undo carries the blocked dates in its details and maps to 409 through the existing error translation.
- Frontend: the Imports page, the sidebar link, the route, and removing the "cannot be undone yet" line from the review screen.

### Tests

- Register: lists only imports; newest first, at most 25; shows account, file, counts and who; a deleted account and a deleted user still show; a reverted import shows "Reverted on <date>" and no button; non-admin and signed-out are refused.
- Undo, success: an import that added rows; one that replaced rows (amount, note and source restored); a mix. The change log records the undo with the right counts. Net worth history matches what it was before the import.
- Undo, refused, with nothing written in each case: a balance edited since; deleted since; replaced by a later import; the account closed; the account deleted. The reasons and dates are in the response, capped at 10.
- Undo twice: the second is refused. An undo cannot be undone.
- The commit repeats the preview's checks: a balance edited between the two steps refuses.

### What Part 1 leaves out of the Part 2 design

Partial undo, per-record savepoints, reason codes as a stable list, a preview that runs the real inverses and rolls back, a confirmation bound to a plan, "a partial undo is final", and undo of kinds other than `import`. All of these can be added later without changing what is stored, because the change log is unchanged.

## Part 2: the deferred design

This is the design that was written for v0.2 and then deferred, moved here from [the schema design](../v0.2-db-schema/design.md) on Nov 2, 2026 with its wording unchanged. It describes a more general undo than Part 1: undo of any balance operation, with partial undo. Where it says v0.2, it means the release it was first written for.

### Decisions (from the decision table)

| Topic | Decision | Why |
| --- | --- | --- |
| Undo | Ships in v0.2 for balance changes only. It runs through the normal write functions, so their rules apply. An undo operation cannot itself be undone. An operation is undone at most once, and the skipped list says what to fix by hand. Account changes are recorded, and restore is v0.5. | The scope valve is not used. Undo and restore are different features on different timelines. |
| Undo is atomic per record | Each inverse, with its data and change-log writes, runs inside a savepoint. An expected failure (a failed precondition or a business rule) rolls back to the savepoint and records a skip. An unexpected database or programming failure aborts the whole undo. | A caught exception in the middle of a multi-write inverse could otherwise leave part of it committed. |
| Undo outcome | The `undo` header is created inside the write transaction, outside the per-record savepoints, before the first inverse. If no row was reverted, the transaction rolls back, nothing persists and the attempt does not count, so the user can fix the cause and retry. If at least one row was reverted, the undo commits and is final. The detail JSON holds the reverted count and the skipped record ids with stable reason codes. | A header with no effect would use up the only undo for nothing. A partial undo is final, so the preview shows what would be skipped before the user confirms. |
| Undo preview | Preview and commit use one evaluator that processes the inverses in reverse order, each evaluated against the state left by the preceding successful inverse. Preview runs the real inverse logic in a write transaction and always rolls it back, so it leaves no rows, header or marker, and the transaction is not held open while the user decides. | A preview that checked each row against the starting state would wrongly skip the replaced balance in a date move, whose old date is only free after the moving balance goes back. |
| Undo confirmation | The confirmation is bound to the target operation and a server-derived plan: record identities, versions or absence, account eligibility and the predicted reverted and skipped sets. The commit recomputes the plan inside `BEGIN IMMEDIATE` and rejects any difference, whether more or fewer rows became eligible, and asks for a fresh confirmation. A partial undo commits only if the user confirmed that partial plan. | Rechecking each inverse protects later work, but could turn a previewed full undo into a final partial one the user never confirmed. |
| Closed and deleted accounts | The balance functions reject every change on a closed account, so undo skips every inverse on a closed or deleted account. Reason codes differ, and the preview tells the user to reopen a closed account before confirming. | Preserves today's rule. Restoring a deleted account is v0.5. |

### Undo of a balance operation

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

### Tests the design required

- Undo: all-skipped (nothing persists, retry allowed), partly successful and fully successful (each blocks a second attempt), and an unexpected failure rolling back the header and every inverse. An expected failure injected after an inverse's first write leaves no part of that inverse while other eligible inverses commit. All inverse kinds against open, closed and deleted accounts.
- Undo preview and confirmation: a date move with replacement previews and commits both inverses when nothing intervenes; if moving the first balance back is blocked, the replaced balance's restore is evaluated against the resulting state; preview leaves no rows, headers or logs; preview and commit classify the same when state is unchanged; an intervening edit that turns a full undo into a partial one commits nothing; closing or reopening an account after preview requests a fresh confirmation; an unchanged, explicitly confirmed partial plan commits and becomes final; two concurrent confirmations cannot both commit.

### Alternative considered

- **Persisting an undo header even when every row is skipped.** It would use up the only undo for an attempt that did nothing. An all-skipped attempt commits nothing instead.

### Decisions to record with the code

- Undo is atomic per record, an undo that reverts nothing does not count, a partial undo is final, an undo cannot be undone, and v0.2 undoes balance changes only. Restore is v0.5.
- Undo preview and commit use one evaluator, and the undo confirmation is bound to the previewed plan.
