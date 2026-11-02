# Undo

Status: the v0.2 part is agreed in discussion and not implemented. The rest is deferred, not scheduled. Nothing in this folder is the spec or the decisions log. Those change only with the code, in the pull request that implements each step.

This folder holds the design for undoing changes to balances. It has two parts:

- **v0.2:** an admin-only register of past imports, with an all-or-nothing Undo on each import. Single edits, Update saves and account changes are fixed by hand.
- **Deferred:** the fuller design, with partial undo, a preview that runs the real inverses, a confirmation bound to the previewed plan, and undo of other operations. It was written for v0.2, moved here from the schema design, and waits for the history screens in v0.5 (#58).

| File | What it holds |
| --- | --- |
| [design.md](design.md) | The v0.2 design, then the deferred design as it was written. |
| [implementation-plan.md](implementation-plan.md) | The v0.2 steps as pull requests, then the deferred work, with a status box for each. |

Related issues: [#81](https://github.com/declankenny/northstar/issues/81) (provenance, delivered, and the v0.2 undo), [#55](https://github.com/declankenny/northstar/issues/55) (the v0.2 epic), [#58](https://github.com/declankenny/northstar/issues/58) (history screens and restore, v0.5), and the v0.5 issue for the deferred undo.

The change log this builds on is designed in [../v0.2-db-schema/design.md](../v0.2-db-schema/design.md) and shipped.

## Lifecycle

This folder is deleted only when Declan says so. Shipping the v0.2 steps does not delete it, because the deferred design is still to come. What lasts from each step goes into `docs/decisions.md` and `docs/spec.md` in that step's pull request.
