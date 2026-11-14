# History and recovery

Status: scope agreed in discussion on November 14, 2026 for v0.7, not implemented. Nothing in this folder is the spec or the decisions log. Those change only with the code, in the pull request that implements each step.

This folder holds the design for balance history, restoring an earlier amount, and admin recovery of deleted accounts and balances, with a retention period and a nightly cleanup.

| File | What it holds |
| --- | --- |
| [design.md](design.md) | The scope, behaviour, retention rules, acceptance criteria and the decisions made while reviewing it. |
| [implementation-plan.md](implementation-plan.md) | The steps as pull requests, in order. |
| [row-actions-review.md](row-actions-review.md) | The review of the existing lists' row actions (#272), done before step 2. |

Related issues: [#58](https://github.com/declankenny/northstar/issues/58) (the v0.7 epic). The change log this builds on is designed in [../v0.2-db-schema/design.md](../v0.2-db-schema/design.md) and shipped. The broader deferred undo design in [../undo/design.md](../undo/design.md) is not a requirement here.

## Lifecycle

This folder is deleted only when Declan says so. Finishing the plan does not delete it. What lasts from each step goes into `docs/decisions.md` and `docs/spec.md` in that step's pull request.
