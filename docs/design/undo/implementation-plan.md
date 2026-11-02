# Undo: implementation plan

The order of the work for [design.md](design.md). Each step is one feature branch and one pull request into `main`. Tick a step when its pull request is merged.

Every step follows the working rules: the spec and `docs/decisions.md` change in the same pull request as the code, a mockup comes before any new screen, and tests use synthetic data.

## Order and dependencies

| Step | What | Depends on | Issue |
| --- | --- | --- | --- |
| 1 | Import register | the change log (shipped) | [#81](https://github.com/declankenny/northstar/issues/81) |
| 2 | Undo an import | 1 | [#81](https://github.com/declankenny/northstar/issues/81) |
| 3 | Undo of other operations, and partial undo | 2, and the history screens | v0.5, to create |

Steps 1 and 2 are in v0.2 and are inside the epic [#55](https://github.com/declankenny/northstar/issues/55). Step 3 is not scheduled.

## Steps

### 1. Import register

- Scope: `account_id` added to the import operation's detail. A read-only admin page, Imports, in the sidebar's Admin group, listing imports newest first (25): Import Date, Import By, Account, File Name, Added, Replaced and a Status column that is empty until step 2. The routes are admin only.
- Tests: only imports are listed; order and the cap of 25; a deleted account and a deleted user still show; non-admins and signed-out users are refused.
- Docs: a spec rule for the register and a decisions entry.
- [x] Merged

### 2. Undo an import

- Scope: `GET` and `POST /api/imports/{id}/undo`. All or nothing, imports only, admin only, an import undone at most once. The review screen's "cannot be undone yet" line is removed and the Status column shows Undo or "Reverted on <date>".
- Tests: an import that added, one that replaced and a mix; a refusal for each of a balance edited since, deleted since, changed by a later import, and a closed or deleted account, with nothing written in each; a second undo refused; the commit repeats the preview's checks; the change log records the undo.
- Docs: the spec rule, a decisions entry saying why this differs from the deferred design, and the changelog.
- [ ] Merged

### 3. Deferred: other operations and partial undo

- Scope: the "Deferred design" in the design file, to be reviewed against what the history screens need before it is built.
- Not scheduled.
- [ ] Merged
