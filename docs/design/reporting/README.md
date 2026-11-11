# Reporting framework

Status: the design was agreed on November 11, 2026 and is not yet built (v0.6). Nothing in this folder is the spec or the decisions log. Those change only with the code, in the pull request that implements each step.

This folder holds the design for a reporting framework: a Reports area where each report is a definition in code (parameters, allowed filters, calculation, typed results, presentation) and the framework supplies navigation, the report selector, parameters, the shared filter drawer, request handling, data states and charts. The framework is the goal of v0.6. Its proof of concept is one report, Assets & Liabilities, an as-at date with two treemaps.

| File | What it holds |
| --- | --- |
| [design.md](design.md) | The agreed design, including the Net Worth Bridge design kept for a later release. |
| [implementation-plan.md](implementation-plan.md) | The order of work as pull requests. |

Related issues: [#57](https://github.com/declankenny/northstar/issues/57) (the epic) and its steps [#234](https://github.com/declankenny/northstar/issues/234) to [#240](https://github.com/declankenny/northstar/issues/240), listed in the plan.

## Where it slots in

Its own release, v0.6, after the lists framework (v0.5) and before data history (v0.7).

- **After v0.5.** Reports reuse the lists filter drawer, field registry and request conventions, so the filter editor is extracted from the lists code, not copied.
- **After v0.3.** Valuation uses the system currency and the existing exchange-rate rules.
- **Before history.** Later reports (net worth over time, currency exposure, and transaction-level reports once transactions exist) are added as definitions on this framework.

## Not in v0.6

The Net Worth Bridge (two dates, reconciliation, waterfall), Freshness, net worth over time, currency exposure and income and expenditure flows. The design uses them to test the contracts, and the bridge's design is kept in `design.md` for its release.

## Lifecycle

This folder is deleted only when Declan says so. Finishing the implementation plan does not delete it. What lasts from each step goes into `docs/decisions.md` and `docs/spec.md` in that step's pull request.
