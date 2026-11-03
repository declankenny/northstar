# Multi-currency and locale-aware formatting

Status: proposed, not implemented. The design is a draft that Declan has reviewed in discussion but not signed off. Nothing in this folder is the spec or the decisions log. Those change only with the code, in the pull request that implements each step.

This folder holds the design for v0.3: accounts held in their own currency, household net worth in one permanent system currency, dated exchange rates, and numbers and dates shown and typed in each user's locale.

| File | What it holds |
| --- | --- |
| [design.md](design.md) | The design as drafted on November 3, 2026, with what is decided, what is proposed and what is still open. |
| [implementation-plan.md](implementation-plan.md) | A draft order of work for the whole v0.3 milestone as pull requests, with a status box for each. |

Related issues: [#56](https://github.com/declankenny/northstar/issues/56) (the epic).

## Where it came from

A requirements interview on November 1, 2026 produced a first proposal. It was then reviewed against `docs/spec.md`, `docs/roadmap.md` and #56 on November 3, which removed several moving parts (a multi-currency switch, changeable account currency, monthly rate history and a per-currency cutoff) and settled that the Northstar CSV stays locale-independent. This folder records the result.

## Separate features this depends on or leaves out

These are not part of this design. Each has its own design and issue.

- **System Properties** ([#124](https://github.com/declankenny/northstar/issues/124)): the admin-maintained settings (system currency, new-user locale, rate staleness threshold). Currency needs it.
- **First-run setup page** ([#64](https://github.com/declankenny/northstar/issues/64)): creates the first admin and can set the system currency and locale. It is a standalone v0.3 feature.
- **System Alerts** ([#133](https://github.com/declankenny/northstar/issues/133)): a backlog feature with no milestone. Currency does not depend on it.
- **Crypto**, **exchange-rate CSV import** and **exchange-rate effects in reporting** (v0.5): not in v0.3.

## Lifecycle

This folder is deleted only when Declan says so. Finishing the implementation plan does not delete it. What lasts from each step goes into `docs/decisions.md` and `docs/spec.md` in that step's pull request.
