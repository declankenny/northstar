# v0.2 database schema

Status: design agreed in discussion, not implemented. Nothing in this folder is the spec or the decisions log. Those change only with the code, in the pull request that implements each step.

This folder holds the design for the database work behind v0.2's balance CSV import and export: soft deletes, audit columns, a system user, a rebuild-capable migration runner, and a record-level change log with undo of balance changes.

| File | What it holds |
| --- | --- |
| [design.md](design.md) | The design: decisions and their reasons, the tables, how the pieces work together, risks, and the tests the design requires. |
| [implementation-plan.md](implementation-plan.md) | The order of the work as pull requests, with dependencies, scope, tests and a status box for each. |

Related issues: [#55](https://github.com/declankenny/northstar/issues/55) (the epic), [#79](https://github.com/declankenny/northstar/issues/79), [#80](https://github.com/declankenny/northstar/issues/80), [#81](https://github.com/declankenny/northstar/issues/81), [#82](https://github.com/declankenny/northstar/issues/82) and [#10](https://github.com/declankenny/northstar/issues/10).

## Open

See "Deferred and open" at the end of the design, and "Decide first" in the plan.

## Lifecycle

Small design topics are discussed on their issue. A large one gets a folder like this one in `docs/design`, and the issues link to it. When the last step of the plan is merged, what lasts goes into `docs/decisions.md` and `docs/spec.md` and this folder is deleted. Git history keeps it.
