# Managing lists: implementation plan

A draft order of work for [design.md](design.md), taken from its "Delivery and future scope" section. Each step is one feature branch and one pull request into `main`, created as issues when the epic is scheduled. Tick a step when its pull request is merged.

Every step follows the working rules: the spec and `docs/decisions.md` change in the same pull request as the code, a mockup comes before any new screen, and tests use synthetic data. Each new dependency states its reason.

## Order and dependencies

| Step | What | Depends on | Issue |
| --- | --- | --- | --- |
| 1 | Definitions, preferences and the query contract, with the Balance Change view | the epic is scheduled | to create |
| 2 | The approved related-field catalog | 1 | to create |
| 3 | Shared table, sorting, pagination and URL state, on Users | 1 | to create |
| 4 | Filter drawer and search | 3 | to create |
| 5 | Column drawer and saved preferences | 3 | to create |
| 6 | CSV export | 1, 4 | to create |
| 7 | Balance entries list on the shared components | 2, 4, 5 | to create |
| 8 | Accounts and Account types as single tables with Class filtering, released together | 4, 5 | to create |

The epic is [#120](https://github.com/declankenny/northstar/issues/120). The order is a first guess: the first question for step 1 is whether the four tables are the simplest thing that works.

## Steps

### 1. Definitions, preferences and the query contract

- Scope: the list definition and user preference tables as one migration, the Balance Change database view, the validated request shape (list key, field keys, operators, sort, page) and the code-side mapping from field keys to query expressions.
- Tests: unknown keys and operators are rejected; soft-deleted and system-user rows never appear; Change is identical under any sort or filter; migration tested on a copy of a database.
- Docs: spec rules, a decisions entry, `docs/schema.md`, and the changelog.
- [ ] Merged

### 2. The approved related-field catalog

- Scope: Balance to Account to Account type as the first approved many-to-one paths, with one row per base record.
- Tests: a missing related record leaves the row; no duplicated rows; unapproved paths are rejected.
- [ ] Merged

### 3. Shared table, sorting, pagination and URL state, on Users

- Scope: one shared list component with sort indicators, page controls and the saved page size, first used on Users, the smallest list. Sort, search, filters and page live in the address.
- Tests: nulls last in both directions; id tie-breaker; page correction after a deletion; stale responses ignored; Back restores the view.
- Docs: a mockup first.
- [ ] Merged

### 4. Filter drawer and search

- Scope: the Filters tab, typed operators, filter chips, Apply and Cancel, Clear and Restore actions, and server-side search.
- [ ] Merged

### 5. Column drawer and saved preferences

- Scope: the Columns tab, insertion at a chosen position, keyboard and touch controls, restore defaults, and saved column order.
- Tests: required columns stay; removal clears the position; renumbering; obsolete saved fields fall back safely.
- [ ] Merged

### 6. CSV export

- Scope: server-side streamed export of the applied view, formula neutralisation, and the filename.
- Tests: empty result, Unicode, quotes, commas, line breaks, missing values, negative amounts and formula-like text.
- [ ] Merged

### 7. Balance entries list

- Scope: the account's balance list on the shared components, including Change and related Account fields.
- [ ] Merged

### 8. Accounts and Account types

- Scope: one table each with a Class column, replacing the Assets and Liabilities groups, shipped together with filtering. Open decision: the default `Status is Open` condition.
- Docs: a mockup first.
- [ ] Merged
