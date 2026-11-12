# Reporting framework: implementation plan

An order of work for [design.md](design.md). Each step is one feature branch and one pull request into `main`, with its own issue under the epic [#57](https://github.com/declankenny/northstar/issues/57). A step is done when its issue is closed, so this plan keeps no status. Pull requests are sequential: one is merged before the next starts, and none are stacked.

Every step follows the working rules: the spec and `docs/decisions.md` change in the same pull request as the code, a mockup comes before any new screen, tests use synthetic data, and each new dependency states its reason.

The framework (steps 1 to 6) is built before any report, so that a report is only a definition and a calculation. The first report, Assets & Liabilities (step 7), is the proof of concept: it adds a definition, a calculation and a presentation and edits no shell file. Other date shapes and result sections are covered by small synthetic report definitions in the tests, not by further reports.

## Order and dependencies

| Step | What | Depends on | Issue |
| --- | --- | --- | --- |
| 1 | The report definition and request contracts | none | [#234](https://github.com/declankenny/northstar/issues/234) |
| 2 | The shared account-positions calculation | none | [#235](https://github.com/declankenny/northstar/issues/235) |
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

### 2. The shared account-positions calculation

- Scope: migration 0028 extends the `account_days` view with `balance_id`, `balance_date` and `rate_date` (no new view), and `northstar/positions.py` returns each account's position for an authorized, filtered `Population` at one or many dates: the fact (the balance's id, amount and date), the native currency and its minor units, the rate used and its date, the value in the system currency and the signed contribution to net worth. The rate date reports use is the latest rate on or before the valuation date, independent of the balance's date, as the Dashboard already does. It reads inside `db.read_transaction`.
- Tests: positions match hand calculations with their provenance; the full population equals `net_worth_on` on every day of a matrix (subsets, whose `net_worth_on(account_id)` is in the account's own currency, are checked by hand); carry-forward of balances and rates, rounding half away from zero in both signs, negative and zero balances, an account with no balance (no rate needed) against a recorded zero (needs one), closed and deleted accounts, current classification, a missing required rate failing the whole call at the earliest day, and one read for many days; the migration on a populated copy leaves the view's rows and the Dashboard series unchanged.
- Docs: a decisions entry (facts and positions, the rate date, why the view was extended and not added to), the spec, and `docs/schema.md`. The Accounts list and Balances list columns that convert at the balance's own date are [#243](https://github.com/declankenny/northstar/issues/243).
- Dependencies: none.

### 3. Extract the shared filter editor

- Scope: split the filter drawer and chips (`FilterDrawer.tsx`, `listFilters.ts`, `FieldPicker.tsx`) into a reusable core, with saved filters and the Columns tab as capabilities that lists keep and reports turn off. Reports do not fetch or write saved filters, and the drawer is not copied.
- Tests: reports can disable saved filters and Columns without any saved-filter request; the existing list tests pass unchanged and cover the extraction.
- Docs: none for users; the extraction is recorded in the pull request description.
- Dependencies: none.

### 4. Filter capabilities on the server

- Scope: a report is filtered by everything the shared field registry offers from its population except what it explicitly excludes (all dates, by kind and on any path, and named fields, on whole path segments); there are no named presets. The same declaration governs the drawer's fields and operators, declared defaults, requests and server scope, and it is checked whichever endpoint is asked first. A request that omits `filters` means the report's defaults, `[]` means none, and explicit conditions replace the defaults. Filtering narrows the authorized population. The choices for a filter by a record are served through the same access, field and population checks. The report's GET returns the fields offered in the lists' shape, the defaults and nothing about the population.
- Tests: exclusions (dates on every path, named fields on whole segments) in the drawer's fields and in requests; a misspelled or obsolete exclusion and a bad default are report faults found by every endpoint without describing the report first; omitted, empty and explicit filters with non-empty defaults; unsupported conditions refused with the condition and the part, never applied or dropped; filtering narrows what was authorized; the choices endpoint's access, field and population checks, including an admin-only report; a field added to the registry is offered to a report that does not exclude it; the registry's declared dates checked against the schema's own evidence; existing list behavior unchanged.
- Docs: a decisions entry for filter capabilities (including the change from presets to exclusions); the spec for the report filter rules; the schema convention for date columns.
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
