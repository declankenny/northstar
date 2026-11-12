# Reporting framework

Status: design agreed on November 11, 2026 and not yet built (v0.6). Items marked *proposal* or *TODO* are open and are settled in the step that builds them. This is not the specification or the decisions log; those change only with the code.

## Purpose and scope

Northstar's Dashboard remains a spacious landing page showing the big picture. A separate Reports area provides deliberate financial analysis.

The goal of v0.6 is a **scalable reporting framework**, deployed and proved by its first reports. Many reports are expected over time (net worth over time, assets and liabilities, currency exposure, and later transaction-level reports such as income and expenditure flows). The framework therefore comes first and is designed against those reports, not only the first one. Individual reports declare their capabilities and provide their calculation; navigation, parameters, filtering, request handling, data states and presentation conventions belong to the framework.

Two rules guide every choice:

- **Framework first.** Shared behavior is built once, in the framework, before a report needs it.
- **Reusability first.** Where the lists already have a capability (filtering above all), extract and reuse it. Never copy it.

A configurable exploratory workspace, draggable widgets, user-authored reports and arbitrary chart building are future enhancements.

## v0.6 scope

- The framework: report definitions, request and result contracts, shell, parameters, filters, data states.
- Apache ECharts as the chart library for all future chart types, behind a shared chart wrapper.
- **First consumers**, curated full-page reports chosen to exercise different parts of the framework, not to answer any particular question:
  - **Assets & Liabilities**, the proof of concept: one as-at date, a hierarchy section, and two treemaps colored by account type. It proves the shell, the as-of date shape, the shared account-positions calculation, the filter drawer and the chart wrapper on the simplest calculation. Other date shapes and result sections are checked with small synthetic report definitions in tests.

The Net Worth Bridge is **not** in v0.6; its design below is kept for the next release. Other reports (Freshness, net worth over time, currency exposure) are expected later and are used now only to test the contracts. #57's original questions ("why did net worth change?", "how current is the information?") are not release requirements: the framework is.

## Agreed product direction

- One **Reports** entry in the main left-hand navigation.
- A searchable report selector in the Reports page header. Opening it shows all available reports; typing narrows the choices. The selected report is prominent.
- One report visible at a time, with its own address for direct linking and bookmarking.
- Report parameters appear in a common area beneath the report selector.
- All filters use the existing lists filtering experience in the right-side drawer. There are no special header controls for filters.
- Applied-filter chips remain visible above the report and support individual removal.
- Filters apply to the entire report: headline figures, visualization and supporting detail.
- Each report declares its available filters. Restrictions apply in the interface and on the server.
- Reports have no saved filters and reload with their default parameters and filters. Changes apply only to the current view.
- Reports value in the **system currency only**. There is no reporting-currency parameter or selector.

## Common report page

The page has five shared regions:

1. **Header:** report selector and a concise description of the selected report.
2. **Parameters:** typed, labeled controls declared by the report, plus the Filters entry point and active-filter count.
3. **Applied filters:** the same readable, removable conditions used by lists.
4. **Report body:** coordinated summary figures, visualization and supporting detail as the report declares.
5. **Filter drawer:** the existing condition-building, Apply, Cancel and Clear interaction, without saved-filter controls.

The selector replaces a permanent second navigation column, leaving room for charts and tables. At narrow widths the parameter controls wrap and the drawer uses the available width. Keyboard access, focus restoration, loading states and error presentation are shared behavior.

Each report's address identifies the report, not a persisted configuration. Opening or reloading a report initializes its declared parameter and filter defaults and resets presentation state. Do not restore prior parameters, filters or expansion state from URLs, local storage or user preferences. The Reports entry initially opens the first report in the list; there is no last-report restoration in the initial release.

## The report definition contract

Definitions live in code, consistent with the existing lists approach. A report declares:

| Capability | Responsibility |
| --- | --- |
| Identity | Stable key, title, description, authorization |
| Population | What the report counts: accounts today; transactions later. The framework never assumes accounts |
| Parameters | Types, defaults, allowed values, cross-parameter validation |
| Filters | What it excludes from the registry's fields (all dates, named fields), and initial default conditions |
| Calculation | Server-side evaluator over an authorized, filtered population |
| Result | Typed sections (below) plus coverage metadata |
| Presentation | Which visualization binds to which section, and transient interaction capabilities such as hierarchical expansion |

### Parameters and filters

Parameters define a report's calculation or presentation. Filters restrict its included population. Classification is declared by the report, not inferred from where a control is drawn or from its data type. This matters for later: a transaction report will legitimately allow date filters, while the account-population reports prohibit them.

Parameter metadata: stable key, label, type, allowed values where applicable, required/default behavior, validation. The framework renders standard controls; a report does not build a custom parameter toolbar.

**Date parameters use a shared vocabulary.** A report declares one of three shapes: none, one as-of date, or an ordered pair or range. Each carries the same rules in one place: no future dates, declared defaults, and cross-parameter validation (for example closing strictly after opening). Other parameters, such as an interval, are plain typed parameters.

A report that supports date filtering puts date conditions in the drawer, like every other filter. A report that takes dates as parameters prohibits date filters, so the two mechanisms never both control dates.

Parameter changes update the whole report coherently. *Proposal:* valid committed changes trigger a request automatically; invalid or incomplete combinations show a validation message without issuing a calculation. Filter changes remain a draft until **Apply changes**, preserving the lists interaction.

### Result sections

A result is a set of typed sections that the shell understands and presentations bind to:

- **summary:** headline figures
- **series:** values over dates
- **hierarchy:** groups with exact amounts and children, supporting expansion
- **rows:** tabular detail
- **flows:** nodes and links, reserved for later (Sankey needs transactions)

All money is exact integer minor units with currency metadata, calculated on the server. A pie or donut is a hierarchy drawn as part-to-whole, so it needs no new data, but part-to-whole requires non-negative parts: a breakdown shows assets and liabilities as separate wholes, and a presentation declares that constraint. A new section kind can be added later without changing the shell. The flows schema is not designed until transaction data exists.

The frontend owns presentation, not authoritative financial arithmetic. Chart adapters convert values for rendering only; displayed totals and reconciliation use server results.

### Account positions

A balance is a recorded fact: an amount in the account's own currency on a date, unaffected by exchange rates (it can be corrected, but a rate never changes it). An account's **position** on a date is derived: its latest balance on or before the date, converted at the latest rate on or before the date, whatever date the balance has. It moves when a rate moves even though no balance was entered, and net worth is the sum of positions. The Dashboard already works this way.

`northstar/positions.py` is the one calculation of positions, and it is how a report obtains account values. Given a `Population` and one or many dates it returns, for each account and date, the fact (the balance's id, amount and date), the native currency and its minor units, the rate used and its date, the value in the system currency and the signed contribution to net worth. It reads the `account_days` view, which migration 0028 extended with the balance id, the balance date and the rate date, so the Dashboard and the reports share the SQL rule that picks the balance and the rate, and `conversion.convert`; the Python aggregation by class is written in both `networth.py` and `positions.py`, and permanent parity tests keep them together. Reports use positions, so a report as at today equals the Dashboard. The Accounts list and Balances list columns that convert a balance at its own date are a separate issue ([#243](https://github.com/declankenny/northstar/issues/243)).

An account with no balance by a date is listed with no balance, no rate and a value of zero, whatever its currency, which is not a missing-rate error; a recorded zero is a balance and in another currency still needs a rate. If any date asked about lacks a required rate the whole call fails, naming the earliest such date and every currency missing on it, and only the accounts in the population can cause it. It reads inside `db.read_transaction`, so everything comes from one snapshot.

### Request and lifecycle

*Proposal:* a read-only calculation endpoint per report, with a POST body containing `parameters` and `filters`, following the existing list request pattern. Return the effective parameters and filters, currency, the typed sections and coverage information. Validate authorization and capabilities before calculation.

All sections of a report come from one coherent calculation, from one consistent database read. Cancel or supersede stale frontend requests so a slow response cannot replace a newer selection.

The framework provides loading, invalid-parameter, incompatible-filter, empty-population, unavailable-data and calculation-error states. A missing required exchange rate prevents the complete result. It must never present an incomplete financial total as complete.

## Reuse the lists filter framework

The existing implementation already supplies field selection, operators, searchable choices, multi-selection, date and number ranges, validation, draft/apply/cancel behavior, applied-filter descriptions, saved filters, and personal/shared defaults.

Relevant existing code:

- `frontend/src/FilterDrawer.tsx`: condition editor, saved-filter interaction, draft application. It also owns a Columns tab and calls list-specific persistence APIs.
- `frontend/src/listFilters.ts`: validation, operator transitions, serialization, chip descriptions.
- `frontend/src/FieldPicker.tsx`: field selection.
- `frontend/src/listState.ts`: list state conventions; report views do not reuse its URL persistence.
- `northstar/list_filters.py`: list-only saved-filter behavior, which reports do not adopt.
- `northstar/lists/`: field registry, condition and request validation, query infrastructure.
- `northstar/web/lists_api.py`: list routing and saved-filter endpoints.

Extract the filter editor and chips into a core with explicit capabilities. Saved-filter controls and persistence, and the Columns tab, are capabilities that lists keep and reports disable. Reports never fetch or write saved filters. Do not copy the drawer, and do not route reports through a dummy list. Lists must pass their existing tests unchanged.

Preserve the filter language: conditions combine with AND; multiple selected values within a condition mean any of them. Native-currency filters are an ordinary account field.

### Filter availability and enforcement

A report is filtered by everything the shared registry offers from its population, except what it explicitly excludes. It declares no allowed list and no named preset (an earlier version of this design did, see the decisions entry for #237): the registry already decides what may be offered at all, so a report only restricts. The consequence is a rule: a field or relation added to the registry is available to every report that does not exclude it.

A report can exclude all dates (by kind, on every step of a path, so prohibiting dates cannot leave a date path through a relation and a date column added later is excluded too) and named fields (on whole path segments: `type` excludes `type` and everything beneath it, `type.name` only that field). A misspelled or obsolete exclusion is a fault in the report.

The same declaration governs the drawer's fields and operators, validation of declared defaults, validation of requests, and server-side scope, and it is checked whichever endpoint is asked first. Unsupported conditions are never silently applied or discarded; requests containing them are rejected with an error that names the condition and the part (`["filters", 0, "field"]`). An invalid declared default is a report-definition error, not a reason to silently broaden the report. URLs do not supply filter state. A request that omits `filters` means the report's own defaults, an empty list means none, and explicit conditions replace the defaults. Filtering only narrows the population the framework authorized, and the choices a filter by a record offers come from it.

### Defaults and transient state

Reports have no saved filters, personal/shared defaults or saved views. Each definition declares initial parameter values and filter conditions. Parameter changes, applied conditions and expansion live only in the current view; opening another report or reloading restores defaults. Within the view, clearing filters leaves an explicitly empty list until the next load. Existing lists keep their saved-filter, default and persistence behavior unchanged.

## Chart library selection

Chosen once, at the start, because many chart types are planned and switching later means rewriting every adapter. Chosen on November 11, 2026.

Required: waterfall, line and area, stacked and grouped bar, pie or donut and sparkline; Sankey later for income and expenditure flows.

Criteria:

- Native support for the types above (a waterfall faked on a bar chart is a warning sign).
- Theming from the app's light and dark CSS variables.
- Keyboard focus on marks and a data-table fallback.
- Horizontal scrolling for large charts.
- Bundle size, licence, maintenance, SVG or canvas (SVG is easier to test and to style).
- React integration and compatibility with the app's Content Security Policy.
- Each new dependency has a stated reason, per the project rules.

**Decision: Apache ECharts.** It covers every planned type (line and area, stacked and grouped bars, pie or donut, treemap and sunburst for hierarchies, Sankey later) in one library and ships an aria text description of each chart. Considered and not chosen: hand-written SVG (the Dashboard's `NetWorthChart.tsx` stays as it is), small D3 modules, Nivo, Recharts, Chart.js, Observable Plot. A throwaway prototype with synthetic data (ECharts and Nivo side by side under the app's CSP) found:

- **Bundle:** about 603 KB minified (205 KB gzipped) over React for four chart types, against about 369 KB (118 KB) for Nivo. It grows with each chart type, so import only the charts and components used (`echarts/core` with explicit `use`).
- **CSP:** the default tooltip writes `style` attributes, which the app's policy blocks (21 violations in the prototype). Every ECharts chart uses a shared tooltip formatter that emits class names only. Load, hover and re-theming produced no violations with it. Any other feature that produces HTML (toolbox, data zoom, custom components) is checked under the CSP before it is used.
- **Renderer:** use the SVG renderer, so charts can be styled and tested. The prototype did not try jsdom unit tests; confirm how chart code is tested when the first one is written.
- **Theming:** ECharts takes colors in JavaScript, so the shared chart wrapper reads the app's CSS variables and re-applies them when the theme changes.
- **Accessibility:** the aria description is on, but ECharts gives no keyboard-focusable marks. Keyboard access to the bridge's expand and collapse controls, and a data-table fallback, are ours to build.
- **Waterfall:** ECharts has no waterfall series, but the stacked-bar construction is a well-known pattern (an invisible base series plus increase and decrease series, with connectors) that other projects use successfully, and the bridge keeps the waterfall as its presentation. Points the build must handle: bars that cross zero (split into a negative and a positive segment) and negative running totals, connectors between steps, signed labels so meaning does not depend on color, horizontal scrolling for large account sets, and replacing a type's bar with its accounts on expansion. The expand and collapse controls are real HTML controls beside the chart (keyboard accessible, outside ECharts' canvas), and the supporting detail table, with a link per row, is the accessible and drill-down route. A table with inline bars is the fallback presentation if the construction proves too awkward. Not yet tried in a prototype; proved when the bridge is built, and the shared wrapper hides ECharts from the reports.

The decision and the rejected options go into `docs/decisions.md` with the code that adds the dependency, as the project rules require.

## Candidate reports

Used to test the contracts. Only Assets & Liabilities is committed to v0.6; the rest are not.

| Report | Question | Date shape | Result sections | Chart |
| --- | --- | --- | --- | --- |
| Assets & Liabilities | Where is my wealth held, and what do I owe? | As-of | summary, hierarchy, rows | Two treemaps |
| Net Worth Bridge | What changed? Which accounts explain the difference between two dates? | Pair | summary, hierarchy, rows | Waterfall |
| Freshness | How current is the information? | None | summary, rows | Table |
| Net worth over time | How has my financial position changed? | Range and interval | series, rows | Line or area |
| Currency exposure | How is my money distributed across currencies? | As-of | hierarchy, rows | Bars or composition |
| Income and expenditure (later) | Where does money come from and go? | Range | flows | Sankey |

## First report: Assets & Liabilities

### Question answered

**Where is my wealth held, and what do I owe?**

### Parameters

| Parameter | Behavior |
| --- | --- |
| As at date | Required calendar date that selects the valuation; defaults to today (`today()`); not in the future. Do not silently shift it to accommodate missing data |

### Filters

One account population used for the whole report, filtered by every account field the registry offers except dates, which the report excludes because it has its own as-at date. Date conditions are prohibited, including through related fields. No saved filters.

### Calculation

The shared account-positions calculation at one date, using the same valuation rules as the bridge (latest balance on or before the date, rate on or before the date, exact conversion and rounding per account, class convention for assets and liabilities, existing visibility and deletion rules). An account with no balance by the date counts zero and is marked "no balance". Assets, liabilities and net worth are summed from the exact per-account values, and net worth equals `net_worth_on(date)` for the same population. A missing required exchange rate prevents the whole result.

### Presentation

- **Summary tiles:** assets, liabilities and net worth, with the as-at date.
- **Two treemaps**, assets and liabilities, each a hierarchy of account type then account, sized by the system-currency value. Blocks are **colored by account type**, with one stable color per type used by both treemaps and the table, and a tint variation across the accounts of a type. Type labels are drawn on the blocks, so color is never the only carrier.
- **Drill:** the treemap opens at types (ECharts `leafDepth: 1`, with a breadcrumb to go back); clicking a type shows its accounts, and clicking an account goes to its account page. A type can also link to the Accounts list filtered by that type.
- **Tooltip:** path, value and share of the whole, through the shared class-only formatter.
- **Supporting detail:** the same hierarchy as a table, with type subtotals and, per account, the value, share, native balance and currency and the balance date, with a link per row. Freshness (days since the balance, the stale flag) is not part of this report. This is the keyboard-accessible route to every number and link.
- **Negative balances:** a block cannot be negative. An overdrawn asset or overpaid liability is left out of its treemap, kept in the table, and named in a note under the chart with its count and total, so the treemap and its note reconcile to the summary tile. Zero balances appear only in the table.
- **States:** an empty population, no assets, or no liabilities has its own honest message, not an empty chart.

## Next report (not in v0.6): Net Worth Bridge

### Question answered

**Why is my net worth different between these two dates?**

The report starts with opening net worth, adds the signed contribution of each account or account type, and ends at closing net worth. It explains balance changes, not investment performance, spending or cash flow.

### Parameters

| Parameter | Behavior |
| --- | --- |
| Opening date | Required calendar date; selects the opening valuation |
| Closing date | Required calendar date after the opening date; selects the closing valuation |

Defaults: closing date is today (the application's `today()`); opening date is one calendar year earlier, using February 28 when that date would be February 29 in a non-leap year. Closing must be strictly after opening and neither may be in the future, enforced in the interface and on the server. Do not silently shift an endpoint to accommodate missing data. There is no breakdown parameter: account types start collapsed and expand directly in the chart.

### Filters

Account filters choose one population used at both endpoints and in all steps. Closing an account does not remove it from a historical comparison: its reduction to zero can be a contribution. Date conditions are prohibited in defaults and requests, including through related fields. Allowed: account identity and metadata such as type and native currency. Balance-amount filters are excluded until an endpoint meaning is defined.

### Calculation and reconciliation

Reuse the shared positions calculation and `northstar/networth.py` rules. At each endpoint, use each account's latest balance on or before the date; an account with no balance counts zero, and detail distinguishes no prior balance from a recorded zero. Use the latest rate on or before the valuation date, convert and round each account with the existing exact-money rules, then aggregate. Signed contribution is asset value minus liability value; do not assume liabilities are stored negative. Existing visibility and deletion rules apply, and current classification is used (no historical metadata is reconstructed).

For each included account `i`:

```text
opening_i = signed system-currency value at opening date
closing_i = signed system-currency value at closing date
change_i  = closing_i - opening_i

opening net worth + sum(change_i) = closing net worth
```

Differences come from the already converted endpoint values, in integer minor units. Group by stable account and type IDs. Type contributions sum their accounts, so expanding or collapsing any combination of types leaves the totals and net change unchanged. The server returns the hierarchy with exact contributions so expansion needs no browser arithmetic.

Each contribution includes both native balance change and FX translation, explained with a clear note. There is no separate FX step. Splitting them exactly would need a rounding residual, and an unexplained adjustment is not allowed; a separate attribution is a future design, and #57's earlier FX requirement is replaced.

### Presentation

- Opening and closing totals anchor the baseline; intermediate bars float from the preceding running total with thin connectors.
- Positive and negative contributions have distinct, theme-aware styles, with signs and labels so meaning does not depend on color.
- Axes identify the currency. Hover and focus detail gives exact values; totals and labels are available without hover.
- Summary figures show opening net worth, net change and closing net worth with explicit dates.
- Supporting detail shows opening, closing and change per group, with account detail, and the balance and rate dates behind each contribution. Accounts with no opening balance are marked, which covers #57's "first appear during the comparison".

Example (illustrative USD): opening 498,708.80, Cash and savings +1,888.35, Investments +31,000.00, Mortgage reduction +12,000.00, Other debt reduction +3,301.61, Property +15,000.00, closing 561,898.76. Expanding Investments replaces its +31,000 step with Brokerage −5,000 then Retirement +36,000, in name order; the running total after the accounts equals the total after the collapsed type.

### Expansion, ordering and large reports

- Load with account types in alphabetical order, all collapsed. Expansion **replaces** a type's aggregate bar with its nonzero accounts, alphabetical by name, with a visible type label and collapse control. Multiple types expand independently; never count a parent with its children. Use stable IDs for expansion state and name-tie breaks.
- Expansion is a presentation interaction, not a parameter or filter, and reload collapses all types.
- Omit zero-change account steps but keep them in supporting detail. A type with zero net change but offsetting nonzero accounts stays visible and expandable. A type whose accounts are all unchanged may be omitted from chart steps. If everything is unchanged, show equal opening and closing totals.
- Show every nonzero contribution; scroll horizontally when needed. No truncation and no automatic Other grouping. The scrollable region is keyboard accessible without forcing page overflow.

## Candidate: Freshness (not committed to v0.6)

Freshness is not part of the Assets & Liabilities report. A separate Freshness report would be considered later, and if built it would exercise a report with no date parameters.

### Question answered

**How current is the information?**

Summarize stale accounts and accounts without balances, each with a working link to update it. It has no date parameters (as of today) and presents rows with a status, exercising the framework without a chart.

"Stale" is the existing rule (spec, Staleness; `northstar/staleness.py`): an open account is stale when the days from its latest balance to today exceed its type's `stale_after_days`, an open account with no balances is also flagged, and closed accounts are never flagged. "Today" is the system timezone's date. The report reuses that rule and adds no second definition.

The Accounts list already has Stale and days-since columns and a Stale filter, so the report must offer more than that list filtered. *Proposal:* a summary that says how far the net worth figure can be trusted (stale and empty counts by type, the oldest balance, and the share of net worth held in stale balances, calculated by the shared account-positions calculation), with the stale accounts listed and linked for update. Which filters apply and the exact rows are designed when the report is built.

## Implementation sequence

1. **Define contracts:** the report definition, parameter and date vocabulary, population declaration, result sections, filter capability model and request/result schemas, checked against the candidate reports and small synthetic definitions.
2. **Extract shared filters:** make the editor and chips reusable with saved filters and Columns as capabilities; add report capability validation at the UI and server boundaries. Lists tests unchanged.
3. **Add ECharts and the shared chart wrapper:** tree-shaken imports, SVG renderer, CSP-safe tooltip formatter, theme from the CSS variables, aria description, a unit-test approach, and the decisions entry.
4. **Build the report shell:** navigation, searchable selector, parameter renderer, transient view state, default initialization, request lifecycle, states. Validate with synthetic definitions.
5. **Shared account-positions calculation:** with tests against `net_worth_on`, the rate date settled (the rate on or before the valuation date), and `account_days` extended with where each figure came from.
6. **Assets & Liabilities report:** calculation on the shared positions, then the two treemaps, summary and supporting table. This is the first report through the shell.
7. **Validate and document:** targeted tests; update the specification and decisions log when the design is approved and implementation lands.

Step 5 depends only on existing valuation code, so it may run earlier than its position if useful.

## Acceptance criteria

Framework:

- Reports has one LHN entry; each report has its own address identifying the report, not saved view state.
- Opening or reloading initializes default parameters, filters and presentation. No saved-filter controls or requests, restored query parameters or remembered view preferences.
- Parameters render from definitions, including all three date shapes; filters use the shared drawer and chips.
- Draft filter edits do not affect results until Apply; Cancel discards them; Clear does not reapply a default.
- Disallowed conditions, including date conditions through related fields, cannot reach calculation by any path, and defaults are checked by the same rules.
- Synthetic report definitions with different date shapes and result sections run through the shell without changes to it.
- Reusing the filter components does not change existing lists behavior.
- Loading, invalid-parameter, incompatible-filter, empty, unavailable and error states exist; no stale chart remains under invalid parameters; no partial totals are shown.

Assets & Liabilities:

- Assets, liabilities and net worth equal `net_worth_on` for the same date and population, verified against a hand calculation on synthetic data.
- Filtering changes the summary, both treemaps and the table together; an as-at date in the future is rejected and explained.
- Type colors are consistent across both treemaps and the table; drilling in and back out leaves the figures unchanged.
- Negative and zero balances, accounts with no balance by the date, closed and deleted accounts, carried-forward balances and rates, rounding, and a missing required rate behave as described, with no partial totals shown.
- A type with one account, many accounts, and very long account names all stay readable; the table gives the keyboard route to every number and link.

Net Worth Bridge:

- Filtering changes the opening total, closing total, contributions and detail together.
- Collapsed, expanded and mixed views reconcile exactly to the same net change without counting aggregates and children together; multiple type controls work independently.
- Types and accounts are alphabetical. Zero-change accounts stay in detail; zero-net types with offsetting accounts stay visible and expandable; all-unchanged data shows equal totals.
- Every nonzero contribution stays available through horizontal scrolling; no Other grouping or truncation.
- Per-account contributions sum exactly to the change in net worth, verified against a hand calculation on synthetic data.
- Coverage: growing and shrinking assets, debt repayment and increase, negative net worth, sign crossings, zero movement, missing opening balances, closed and deleted accounts, current classification changes; carried-forward balances and rates, rounding boundaries, FX-only changes, missing required rates.
- Invalid endpoint order is explained. Empty and unchanged populations have distinct, honest states.
- Large account sets, long labels, narrow layouts, keyboard navigation and focus remain usable.

## Confirmed decisions

1. System currency only; no reporting-currency parameter or selector.
2. Framework first, and reuse of existing capabilities (filters) first.
3. Each account is valued in system currency at both endpoints; FX effects stay within its contribution, with no separate FX step.
4. Closing date defaults to today and opening to one calendar year earlier, with February 28 as the leap-day fallback; closing after opening; no future dates.
5. No saved filters for reports; reports reload with defaults and changes apply only to the current view.
6. Alphabetical order: account types first, accounts within an expanded type.
7. Omit zero-change account steps but keep detail; zero-net types with offsetting accounts stay expandable; unchanged types are omitted; an unchanged population shows equal totals.
8. Preserve every nonzero contribution, with horizontal scrolling and no automatic Other grouping.
9. No breakdown parameter: types load collapsed and expand in place; multiple types expand independently; reload collapses all.
10. **Confirmed:** Apache ECharts is the chart library, chosen up front for all planned chart types including pie, treemap and Sankey, with the constraints listed under Chart library selection.
11. **Confirmed:** the release goal is the framework; reports exist to prove it, and #57's original questions are not requirements.
12. **Confirmed:** the v0.6 proof of concept is Assets & Liabilities: an as-at date and two treemaps (assets, liabilities) colored by account type. The Net Worth Bridge and Freshness are not in v0.6.

## Related design references

- [Lists framework](../lists/design.md)
- [Currency and valuation](../currency/design.md)
- [Current specification](../../spec.md)
- [Current valuation implementation](../../../northstar/networth.py)
