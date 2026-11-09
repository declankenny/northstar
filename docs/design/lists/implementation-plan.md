# Managing lists: implementation plan

An order of work for [design.md](design.md). Each step is one feature branch and one pull request into `main`, with its own issue under the epic [#120](https://github.com/declankenny/northstar/issues/120). A step is done when its issue is closed.

Every step follows the working rules: the spec and `docs/decisions.md` change in the same pull request as the code, a mockup comes before any new screen, tests use synthetic data, and each new dependency states its reason.

The framework (steps 1 to 6) is built before any list, so that a list is only data. The first real list, Balances (step 7), is a small pull request that adds a definition, a route and a navigation entry and edits no framework file. Which other existing pages move onto the framework is decided after this design, list by list, and adds steps after step 8.

## How the framework is built and checked

- It is built and exercised against a synthetic dataset that is not in the repository (see "Development approach" in the design), through an uncommitted local change on the developer's machine. Nothing from the dataset is committed, including in tests.
- The repository's own tests use a small generated schema with the same shapes (one table reached in several roles, deep paths, a view as a source, nullable Yes or No columns, scaled integers, timestamps) so CI covers them.
- Each framework pull request stages only the files that belong to it, and its description says what was checked against the dataset.

## Order and dependencies

| Step | What | Depends on | Issue |
| --- | --- | --- | --- |
| 0 | Derive an account's class from its type (remove `accounts.class_id`), merged first | the epic | [#181](https://github.com/declankenny/northstar/issues/181) |
| 1 | The registry, the request contract and the processing, with no list | 0 | [#184](https://github.com/declankenny/northstar/issues/184) |
| 2 | The shared table: sorting, pagination, address state and row actions, with no list | 1 | [#185](https://github.com/declankenny/northstar/issues/185) |
| 3 | Filters, search and saved filters (private and shared, defaults) | 2 | [#186](https://github.com/declankenny/northstar/issues/186) |
| 4 | The column drawer: the relation tree, dragging, saved columns | 2 | [#187](https://github.com/declankenny/northstar/issues/187) |
| 5 | Group by | 2 | [#188](https://github.com/declankenny/northstar/issues/188) |
| 6 | Export CSV | 1, 3 | [#189](https://github.com/declankenny/northstar/issues/189) |
| 7 | The Balances list: a definition, a route and a navigation entry | 2, 3, 4, 5, 6 | to create |
| 8 | Accounts as one table with Class and Stale | 3, 4 | [#190](https://github.com/declankenny/northstar/issues/190) |

## Steps

### 0. Derive an account's class from its type

- Scope: a migration that rebuilds `accounts` without `class_id`, recreates the views that read it, and replaces the composite key's protection with a trigger that refuses a class change on a type any account uses (deleted accounts included). No change in behaviour. Described in [#181](https://github.com/declankenny/northstar/issues/181).
- Its own pull request, merged before step 1, so the registry is written against one path to Class. It ships in v0.5 and is tested on a copy of a database.

### 1. The registry, the request contract and the processing

- Scope: the registry module (source, display column, tell-apart column, fields and their kinds, relations read from foreign keys with labels from the FK column, walkable, denied columns, searchable flags, record page, row actions), the validated request (list key, fields, operators, sort, group, page), the processing order, the converted-money kind with the conversion rule in framework code, the derived views, and the migration for `user_list_prefs` and `list_filters` with the partial unique index. No list is defined.
- Tests: a table with no entry fails; a denied column is unreachable; unknown keys and operators are refused; the same table by several roles gets separate joins and labels; a path stops at the safety limit and never repeats a table; a view works as a source; deleted records and the system user never appear; nullable Yes or No, scaled integers and timestamps filter and sort correctly; a converted amount follows the conversion rule, with an empty cell and the named currency when there is no rate; migration tested on a copy of a database.
- Docs: spec rules, a decisions entry, `docs/schema.md` and the changelog.
- Dependencies: none.

### 2. The shared table

- Scope: the shared list component on TanStack Table 9 in server mode, the header with its menu, nulls-last sorting, the footer, saved page size, the address carrying sort, search and page, states for loading, failure and empty, and the row menu drawn from a definition's row actions. It adds no route and no navigation entry.
- Tests: nulls last in both directions; the id tie-breaker; page correction; an overtaken response is ignored; Back restores the view; a disabled action shows its reason.
- Docs: the mockup is done (outside the repo); the dependency's reason, exact pin and bundle cost; the v9 server-mode features are confirmed in its documentation first.

### 3. Filters, search and saved filters

- Scope: the Filters tab, typed operators, chips, Apply and Cancel, server-side search over the searchable flags, and saved filters with private and shared kinds, names, defaults and the stale-filter fallback.
- Tests: operators and their edge cases; one condition per field; one shared default per list, enforced; a saved filter on a removed column degrades.

### 4. The column drawer

- Scope: the generated relation tree, Add and Move controls, dragging with dnd kit, the required column, restore defaults and saved columns.
- Tests: no table twice in a path; the safety limit; users never expand; a required column stays; obsolete saved fields fall back.
- Docs: the dependency's reason, exact pin, bundle cost and `npm audit` result.

### 5. Group by

- Scope: Group by and Ungroup on every header, group rows with counts, collapse, and groups that continue across pages.
- Tests: grouping across a page boundary; groups by a display value; an empty group value.

### 6. Export CSV

- Scope: the streamed export of the applied view, formula neutralisation, the filename and the match count.
- Tests: empty result, Unicode, quotes, commas, line breaks, missing values, negative amounts, formula-like text and an unauthorised field.

### 7. The Balances list

- Scope: the Balances definition (the live balances as its source; default columns Date, Account, Account type, Value, Currency, Reporting value and Note; default sort Date, newest first; no default filter; Edit and Delete as row actions using the existing dialogs, disabled with the reason on a closed account), a route, and a navigation entry between Accounts and Update balances.
- The rule for this pull request: it edits no framework file. If Balances needs something the framework lacks, a framework pull request comes first.
- Tests: the definition's behaviour through the framework (the default view, a row's actions, a closed account's disabled actions); the existing per-account export and Update balances are unchanged.
- Docs: the spec's list rules, the changelog.

### 8. Accounts as one table

- Scope: Class and Stale as columns, the Open and Closed buttons and the Assets and Liabilities cards replaced, Status as a filter. Whether it ships a shared default filter is decided with its mockup.
- Docs: a mockup first.
