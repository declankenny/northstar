# Managing lists

Status: proposed, not scheduled and not implemented. The design is a draft that has not been reviewed. Nothing in this folder is the spec or the decisions log. Those change only with the code, in the pull request that implements each step.

This folder holds the design for giving every list in Northstar the same sorting, filtering, configurable columns, pagination and CSV export, processed on the server and tailored per user.

| File | What it holds |
| --- | --- |
| [design.md](design.md) | The proposal as drafted on November 2, 2026. |
| [implementation-plan.md](implementation-plan.md) | A draft order of work as pull requests, with a status box for each. |

Related issues: [#120](https://github.com/declankenny/northstar/issues/120) (the epic), [#68](https://github.com/declankenny/northstar/issues/68) (page state in the address, which overlaps), [#66](https://github.com/declankenny/northstar/issues/66) (phone layout) and [#117](https://github.com/declankenny/northstar/issues/117) (export and re-import across accounts).

## Where it slots in

Decided: its own release, v0.4, after v0.3 (multi-currency). Household reporting moved to v0.5 and data history and recovery to v0.6. It is not in v0.2, which is feature-complete.

- **After v0.3.** Money columns, money filters and the CSV money format change meaning once an amount has a currency. Building lists first means reworking them.
- **Before reporting and history.** Reports and history screens are lists. Building the shared list first means they use it, rather than being migrated onto it later.
- **A release of its own.** The epic is large enough that sharing a release with reporting would delay both.

## Lifecycle

This folder is deleted only when Declan says so. Finishing the implementation plan does not delete it. What lasts from each step goes into `docs/decisions.md` and `docs/spec.md` in that step's pull request.
