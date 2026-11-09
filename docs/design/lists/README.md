# Managing lists

Status: the design is agreed (November 9, 2026) and not implemented. Nothing in this folder is the spec or the decisions log. Those change only with the code, in the pull request that implements each step.

This folder holds the design for giving Northstar's lists the same sorting, grouping, filtering, configurable columns, pagination and CSV export, processed on the server and tailored per user.

| File | What it holds |
| --- | --- |
| [design.md](design.md) | The agreed design. |
| [implementation-plan.md](implementation-plan.md) | The order of work as pull requests. |

Related issues: [#120](https://github.com/declankenny/northstar/issues/120) (the epic), [#68](https://github.com/declankenny/northstar/issues/68) (page state in the address, delivered by this), [#66](https://github.com/declankenny/northstar/issues/66) (phone layout for balance entry, not part of this) and [#117](https://github.com/declankenny/northstar/issues/117) (export and re-import across accounts, not part of this).

## Where it slots in

Its own release, v0.5, after v0.4 (OIDC sign-in), before household reporting (v0.6) and data history (v0.7).

- **After v0.3.** Money columns and the list CSV format depend on what an amount means once it has a currency.
- **Before reporting and history.** Reports and history screens are lists, so a shared list built once means they use it.
- **A release of its own.** The epic is large enough that sharing a release would delay both.

The framework is built before any list, so that a list is only data, and Balances is the first list. Which existing pages move onto the framework beyond that is decided after the design, list by list.

## Lifecycle

This folder is deleted only when Declan says so. Finishing the implementation plan does not delete it. What lasts from each step goes into `docs/decisions.md` and `docs/spec.md` in that step's pull request.
