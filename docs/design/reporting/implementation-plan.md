# Reporting framework: implementation plan

An order of work for [design.md](design.md). Each step is one feature branch and one pull request into `main`, with its own issue under the epic [#57](https://github.com/declankenny/northstar/issues/57). A step is done when its issue is closed, so this plan keeps no status. Pull requests are sequential: one is merged before the next starts, and none are stacked.

Every step follows the working rules: the spec and `docs/decisions.md` change in the same pull request as the code, a mockup comes before any new screen, tests use synthetic data, and each new dependency states its reason.

The framework (steps 1 to 6) is built before any report, so that a report is only a definition and a calculation. The first report, Assets & Liabilities (step 7), is the proof of concept: it adds a definition, a calculation and a presentation and edits no shell file. Other date shapes and result sections are covered by small synthetic report definitions in the tests, not by further reports.

## Order and dependencies

| Step | What | Depends on | Issue |
| --- | --- | --- | --- |
| 1 | The report definition and request contracts | none | [#234](https://github.com/declankenny/northstar/issues/234) |
| 2 | The shared account-values calculation | none | [#235](https://github.com/declankenny/northstar/issues/235) |
| 3 | Extract the shared filter editor | none | [#236](https://github.com/declankenny/northstar/issues/236) |
| 4 | Filter capabilities on the server | 1 | [#237](https://github.com/declankenny/northstar/issues/237) |
| 5 | ECharts and the shared chart wrapper | none | [#238](https://github.com/declankenny/northstar/issues/238) |
| 6 | The report shell | 1, 3, 4, 5 | [#239](https://github.com/declankenny/northstar/issues/239) |
| 7 | Assets & Liabilities | 2, 5, 6 | [#240](https://github.com/declankenny/northstar/issues/240) |

Steps with no dependency can be taken in any order. The suggested order is the table's, since 1 is needed by 4 and 6, and 2 only by 7, so 2 can also move earlier or later without affecting the others.

## Steps

### 1. The report definition and request contracts

- Scope: the report definition (identity, population, parameters, allowed filters, calculation, result, presentation), the shared date vocabulary (none, one as-of date, or an ordered pair or range, with the same rules for future dates, defaults and cross-parameter validation), typed result sections (summary, series, hierarchy, rows, and flows reserved), the calculation request (`parameters` and `filters` in a POST body) and result schemas, with money as exact minor units and currency metadata.
- Tests: synthetic definitions with different date shapes and result sections validate and calculate; a new report using supported capabilities needs no shell change; an unknown parameter or section kind is refused.
- Docs: a decisions entry for the contracts; the spec when a rule changes.
- Dependencies: none.

### 2. The shared account-values calculation

- Scope: one calculation of each account's signed system-currency value at one or many dates for an authorized, filtered account population, built on the existing rules in `northstar/networth.py`, returning the native amount and currency and the actual balance and rate dates beside the valuation date. The rate date reports use is settled here (the Accounts list converts at the balance's own date and the Dashboard at today's rate).
- Tests: results match a hand calculation on synthetic data as well as `net_worth_on` for the same date and population; carry-forward of balances and rates, rounding boundaries, negative balances, zero balances, accounts with no balance by the date, closed and deleted accounts, current classification, and a missing required rate that prevents the whole result.
- Docs: a decisions entry for the rate date; the spec if the Accounts list or Dashboard behavior changes.
- Dependencies: none.

### 3. Extract the shared filter editor

- Scope: split the filter drawer and chips (`FilterDrawer.tsx`, `listFilters.ts`, `FieldPicker.tsx`) into a reusable core, with saved filters and the Columns tab as capabilities that lists keep and reports turn off. Reports do not fetch or write saved filters, and the drawer is not copied.
- Tests: reports can disable saved filters and Columns without any saved-filter request; the existing list tests pass unchanged and cover the extraction.
- Docs: none for users; the extraction is recorded in the pull request description.
- Dependencies: none.

### 4. Filter capabilities on the server

- Scope: allowed field sets resolved through the shared field registry (named, shareable presets such as "account fields, no dates"), which limit related-field paths as well as direct fields. The same declaration governs the drawer's fields and operators, declared defaults, draft conditions, calculation requests and server scope.
- Tests: declared defaults and related-field paths are validated as well as explicit requests; unsupported conditions are rejected with a field-specific error and never silently applied or discarded; a date condition cannot reach a report that prohibits it by any path; existing list behavior is unchanged.
- Docs: a decisions entry for filter capabilities; the spec for the report filter rules.
- Dependencies: 1.

### 5. ECharts and the shared chart wrapper

- Scope: Apache ECharts imported through `echarts/core` with only the charts and components used, the SVG renderer, and a shared wrapper with a tooltip formatter that uses class names only (the app's CSP blocks the style attributes ECharts' default tooltip writes), theming from the app's CSS variables with re-theming, and an aria description. Keyboard alternatives for the data are part of the wrapper's contract.
- Tests: a small compatibility probe for each chart type to be used (treemap first), not a complete production adapter. It checks zero CSP violations on load, hover and re-theming, automatically, treemap drill-down, and the keyboard alternative. A unit-test approach for chart code is chosen and documented.
- Docs: the decisions entry for ECharts and the rejected options (hand-written SVG, D3 modules, Nivo, Recharts, Chart.js, Observable Plot), with the dependency's reason, exact pin and bundle cost.
- Dependencies: none.

### 6. The report shell

- Scope: the Reports navigation entry, a searchable report selector, the parameter renderer for the shared date shapes, default initialization, the common request lifecycle (stale requests cancelled or superseded) and the shared states (loading, invalid parameters, incompatible filters, empty, unavailable data, error). Parameters, filters and presentation state live only in the current view and are never restored.
- Tests: reload restores the declared defaults and nothing persists in URLs, local storage or preferences; invalid inputs cannot leave stale results shown as current; a slow response never replaces a newer one; the synthetic definitions run through the shell with no changes to it.
- Docs: a mockup is agreed first, outside the repo using the app's real CSS; the spec and a decisions entry for the Reports area.
- Dependencies: 1, 3, 4, 5.

### 7. Assets & Liabilities

- Scope: an as-at date (defaulting to today, never in the future), summary tiles for assets, liabilities and net worth, two treemaps (assets and liabilities, each by account type then account, colored by account type, drilling from type to accounts and on to the account page), and a supporting table with the balance date and a link per row. Negative balances are left out of the treemap, kept in the table, and named in a note under the chart with their count and total so everything reconciles to the summary tile. Freshness is not part of this report.
- Tests: assets, liabilities and net worth equal `net_worth_on` for the same date and population and match a hand calculation; all sections use the same population and exact server-calculated values; negative and zero balances, an empty population, no assets or no liabilities, accounts with no balance by the date, closed and deleted accounts, and a missing required rate each have their state and no partial totals; type colors are consistent across both treemaps and the table; the table is the keyboard route to every number and link.
- Docs: a mockup is agreed first (the throwaway treemap prototype is a starting point); the spec and decisions entry for the report.
- Dependencies: 2, 5, 6.

## Later

The Net Worth Bridge, Freshness, net worth over time, currency exposure and the transaction-level reports are added as definitions on this framework in later releases. Each gets its own issue when it is planned.
