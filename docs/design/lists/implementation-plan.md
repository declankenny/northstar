# Managing lists: implementation plan

An order of work for [design.md](design.md). Each step is one feature branch and one pull request into `main`, with its own issue under the epic [#120](https://github.com/declankenny/northstar/issues/120). A step is done when its issue is closed.

Every step follows the working rules: the spec and `docs/decisions.md` change in the same pull request as the code, a mockup comes before any new screen, tests use synthetic data, and each new dependency states its reason.

Which existing pages move onto the framework beyond Balances and Accounts is decided after this design, list by list, and adds steps after step 7.

## Order and dependencies

| Step | What | Depends on | Issue |
| --- | --- | --- | --- |
| 0 | Derive an account's class from its type (remove `accounts.class_id`), merged first | the epic | [#181](https://github.com/declankenny/northstar/issues/181) |
| 1 | The registry, the request contract and the derived views, with Balances as the first list in the API | 0 | to create |
| 2 | The shared table, sorting, pagination and address state, shown on a new Balances page | 1 | to create |
| 3 | Filters, search and saved filters (private and shared, defaults) | 2 | to create |
| 4 | The column drawer: the relation tree, dragging, saved columns | 2 | to create |
| 5 | Group by | 2 | to create |
| 6 | Export CSV | 1, 3 | to create |
| 7 | Accounts as one table with Class and Stale | 3, 4 | to create |

## Steps

### 0. Derive an account's class from its type

- Scope: a migration that rebuilds `accounts` without `class_id`, recreates the views that read it, and replaces the composite key's protection with a trigger that refuses a class change on a type any account uses (deleted accounts included). No change in behaviour. Described in [#181](https://github.com/declankenny/northstar/issues/181).
- Its own pull request, merged before step 1, so the registry is written against one path to Class. It ships in v0.5 and is tested on a copy of a database.

### 1. The registry, the request contract and the derived views

- Scope: the registry module (display column, fields, relations read from foreign keys, walkable, denied columns, record page), the validated request (list key, fields, operators, sort, group, page), the processing order including the Python step for Reporting value, the views for the latest balance, days since it, staleness and balance count, and a list endpoint for Balances. The migration for `user_list_prefs` and `list_filters` with the partial unique index.
- Tests: a table with no entry fails; a denied column is unreachable; unknown keys and operators are refused; deleted records and the system user never appear; Reporting value matches the conversion rule, with an empty cell and the named currency when there is no rate; migration tested on a copy of a database.
- Docs: spec rules, a decisions entry, `docs/schema.md` and the changelog.
- Dependencies: none.

### 2. The shared table, sorting, pagination and address state

- Scope: the shared list component on TanStack Table in server mode, the header with its menu, nulls-last sorting, the footer, saved page size, the address carrying sort, search and page, states for loading, failure and empty, and the Balances navigation entry.
- Tests: nulls last in both directions; the id tie-breaker; page correction; an overtaken response is ignored; Back restores the view.
- Docs: a mockup first (done, outside the repo); the dependency's reason and pin.

### 3. Filters, search and saved filters

- Scope: the Filters tab, typed operators, chips, Apply and Cancel, server-side search, and saved filters with private and shared kinds, names, defaults and the stale-filter fallback.
- Tests: operators and their edge cases; one condition per field; one shared default per list, enforced; a saved filter on a removed column degrades.

### 4. The column drawer

- Scope: the generated relation tree, Add and Move controls, dragging with dnd kit, the required column, restore defaults and saved columns.
- Tests: no table twice in a path; users never expand; depth limit; a required column stays; obsolete saved fields fall back.
- Docs: the dependency's reason and pin.

### 5. Group by

- Scope: Group by and Ungroup on every header, group rows with counts, collapse, and groups that continue across pages.
- Tests: grouping across a page boundary; groups by a display value; an empty group value.

### 6. Export CSV

- Scope: the streamed export of the applied view, formula neutralisation, the filename and the match count.
- Tests: empty result, Unicode, quotes, commas, line breaks, missing values, negative amounts, formula-like text and an unauthorised field.

### 7. Accounts as one table

- Scope: Class and Stale as columns, the Open and Closed buttons and the Assets and Liabilities cards replaced, Status as a filter. Whether it ships a shared default filter is decided with its mockup.
- Docs: a mockup first.
