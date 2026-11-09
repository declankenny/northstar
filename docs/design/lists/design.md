# Managing lists: design

Status: agreed in discussion on November 9, 2026, not implemented. It replaces the draft of November 2. It is not the spec or the decisions log: each step's pull request changes those. Which existing pages move onto the framework is decided after this design, list by list. Anything marked TODO is unresolved: do not guess it.

Northstar lists share sorting, grouping, filtering, configurable columns, pagination and CSV export, processed on the server and tailored per user. A list is a read-only display of records. Row actions open a record page or a dialog, and a list is never a data-entry screen. Lists are navigation, not reporting: they show no totals.

## Decisions at a glance

- One server-side contract, validated against a registry in code. No definitions in the database.
- Two stored things per user: list preferences (columns, page size) and saved filters, private or shared.
- Filters are conditions only. Sort and group live in the address only.
- Defaults are shared filters that an admin owns, first inserted by a migration. There is no separate class of shipped default, and the framework has no rule against them: each list decides.
- Every list has the same controls: search, Filters, Columns, Export CSV, a footer with the page range, page navigation and page size.
- The column picker is a tree generated from the tables' many-to-one relations.
- A relation column shows the target's display value, never its id.
- Money: Value is in the account's currency and Reporting value is in the system currency. No totals.
- Libraries (checked on npm on November 9, 2026): TanStack Table 9 (`@tanstack/react-table`, stable, MIT, peer `react >=18`) for table state, and the dnd kit rewrite (`@dnd-kit/react`, 0.x, MIT, peers name React 19) for column dragging. Both are pinned exactly and each is justified in its pull request. The rewrite is pre-1.0, so the drawer keeps Add and Move controls that work without dragging. The legacy `@dnd-kit/core` was passed over because it has had no release since December 2024. TODO before step 2: confirm in the v9 documentation that server-side sorting, pagination, grouping, column order and visibility work as this design assumes. TODO in steps 2 and 4: measure the bundle cost with a build before and after, and run `npm audit` and the image scan on the new packages.

## The registry

A Python module holds one entry per table. A list is a base table plus its scope, and it reaches everything else through the registry.

- **Display column**: the one column an FK to the table shows (Account: Name, Account type: Name, Class: Name, Currency: Code, User: Display name).
- **Fields**: the other columns that may be offered, with their type, and the code that sorts, filters, groups and exports each.
- **Relations**: the many-to-one relations, read from the database's foreign keys at startup. One-to-many is never offered, because it multiplies rows.
- **Walkable**: whether a person can expand into the table to reach more of its columns. Users are leaf-only.
- **Denied columns**: never offered, searched, filtered or exported. Password hashes, tokens and emails (as a related field), the deleted flag.
- **Record page**: the route of the table's single-record page, if any, and who may open it.

The entry belongs to the table, not to a list. A test fails if a table has no entry, if a denied column can be reached, or if a request names a field outside the registry. Unknown lists, fields, operators, sort and group keys are refused with a clear message. Values are parameterised, and the registry holds no executable SQL a client can influence.

Derived fields are columns computed in code from views: the latest balance and its date, days since it, whether the account is stale, the balance count and Reporting value. They behave like any other column. There are no user-defined fields, no formulas and no unrestricted traversal.

## Columns and the picker

Included columns are shown in order. Everything else the registry offers for the list is available.

- **The tree.** Columns opens a drawer with two lists: Available, not included, and Included. Available is a tree starting at the list's base table. A relation is a leaf (its display value) and also expands when its table has more to offer. Depth is limited to three relations. No table appears twice in a path, and Users never expand. Derived fields are not marked.
- **Moving columns.** Drag between the lists or within Included. Add, Move up, Move down and Remove do the same without dragging, for keyboard and touch. Changes stay a draft until Apply changes.
- **Required column.** The row's own display column (Name on Accounts) can be moved but not hidden, so a row can always be opened. A list whose rows have no record page has none.
- **One path to Class.** An account's class is its type's class, so Class is reached only through Account type. A prerequisite change, [#181](https://github.com/declankenny/northstar/issues/181), removes `accounts.class_id`, which was a redundant copy kept consistent by a composite foreign key. No registry rule is needed for equivalent paths.
- **Restore default columns** returns to the list's default order. Applying saves the columns and page size per user and list.
- Hiding a column does not remove a filter on it.

## Display values and links

An FK column shows the target's display value. It sorts, groups and exports by that value, and filters on the id underneath, with the values as the choices. A display value need not be unique (user names are not), and the picker then adds a second detail to tell two apart.

A link belongs to a column, not to a position:

- the row's own display column opens the row's record;
- a relation column opens the target's record when that table has a page the viewer can open (Currency for admins only);
- every other column is plain text.

Moving a column never changes its link. A list with no record page, such as Balances, has no row link and opens rows from the row menu. A page added later makes every list that has the column link to it, with no further work. Exports never carry links.

## Money

- **Value** is the amount in the account's currency, and its cell carries the currency (`$1,234.56`, `JPY 1,234`), so it reads correctly when the Currency column is hidden or moved. Currency is an ordinary column.
- **Reporting value** is the amount in the system currency, with the code in its header. A balance converts at the latest rate on or before its own date. An account's latest balance converts at today's latest rate, so the column agrees with the Dashboard. Conversion is the spec's rule (exact decimal arithmetic, in Python).
- A row with no usable rate shows "No CHF rate" (the currency named) in the cell. The cell is empty, not zero: it sorts last, a blank-value filter finds it, and an export leaves it blank. The list never refuses.
- Sorting or filtering by Value compares amounts in each account's own currency, so across currencies it is only meaningful together with a Currency filter. The filter's help text says so. Reporting value compares converted amounts.
- **No totals or aggregates.** Counts are not totals: the footer range, the match count beside Export CSV and a group's row count stay.

## Sorting, grouping and pagination

- Every column sorts. Clicking a header selects it and clicking again reverses it. One user-chosen sort at a time. Empty values sort last in either direction. Text sorts without case, numbers by value, dates in order. The record id is the final ascending tie-breaker.
- **Group by** and **Ungroup** are on every column's header menu. One level. Rows are ordered by the group value, then the active sort. A group header shows the value and a row count, never a sum, and groups collapse. Pages cut through groups, and a group that continues on the next page repeats its header marked as continued, with the group's total and how many rows are on this page ("Savings · 14 rows (4 on this page)"). A collapsed group stays collapsed across pages during a visit. The footer range still counts rows, so it reads as it does for a flat list.
- Page sizes are 10, 25, 50 and 100, default 25, saved per user and list. Any change of filter, search, sort, group or page size returns to page 1, and a page beyond the end shows the last. Counts describe all matching rows.
- Sort, group, filters, search and page are in the address, so refresh, Back and returning from a record restore the view (this also delivers #68). An explicitly cleared filter is carried in the address so a default does not return by itself. Keep filter values out of logs.
- States are kept apart: loading, a failed request with retry (the last good view stays), an empty list and no matches. A response that has been overtaken by a newer request is ignored.

## Filters and saved filters

The Filters tab has one row per condition: a field, an operator for its type and the value controls. One condition per field. Conditions combine with AND, and several chosen values within one category combine with OR. Add filter offers every column the registry exposes, shown or not, using the same relation tree as Columns.

| Field type | Operators |
| --- | --- |
| Text | contains, equals, is empty, is not empty |
| Category | is any of |
| Number or money | equals, at least, at most, between, is empty |
| Date | before, after, between, is empty |
| Yes or No | is Yes, is No |

Between includes both ends. Before and after exclude the date. An invalid range prevents Apply. Empty is distinct from zero and never matches a numeric range. Search matches the designated text fields of the list whether or not their columns are shown, combines with the filters by AND and is applied on the server after a short pause.

**Saved filters** hold conditions only.

- A person saves, applies, renames, overwrites and deletes private filters for any list they can see.
- Admins also create, change and delete shared filters. Everyone can apply them. A shared filter never widens what a person may see.
- A name is unique among a person's private filters and among the shared filters of a list.
- A person can mark one visible filter as their default. An admin can mark one shared filter per list as the default for everyone, and the database enforces at most one with a partial unique index. Marking another clears the old mark in the same transaction.
- Opening a list uses the person's default, then the shared default, then nothing. A migration may insert a shared default for a list, and a later migration never touches a row an admin has changed.
- A saved filter that names a column that no longer exists degrades safely: it says so and skips that condition.
- The drawer's Apply changes and Cancel apply or discard both tabs together. Removing a chip applies immediately. Hard exclusions (deleted records, the hidden system user) are not filters and cannot be removed.

## Export

Export CSV is a view export, distinct from the per-account Export CSV, which stays the canonical format that round-trips on import. It writes every row that matches, in the applied order, with the included columns in their order, read by the server through the same registry. A page, a page size and an unapplied draft never limit it, and an empty result gives the headers alone. The match count is shown beside the button.

- UTF-8, dates as `YYYY-MM-DD`, amounts as plain decimals in their own currency with no symbol or separator, Reporting value in the system currency, empty cells for missing values, and `true` or `false` for Yes or No.
- A relation column writes its display value.
- Text that starts like a formula is neutralised, and the policy is checked with spreadsheet programs. The serializer handles quotes, commas and line breaks.
- The response streams, from one consistent read, with a name that contains the list and the date. It changes no saved preference.

## Storage

Two tables, in one migration, with the usual audit columns. The exact DDL follows the schema conventions when the step is built.

- **user_list_prefs**: user, list key, page size, columns as validated JSON.
- **list_filters**: owner (empty means shared), list key, name, conditions as validated JSON, whether it is the owner's default or the shared default.

Preferences hold only keys the registry accepts, and invalid ones fall back to the list's defaults. Conditions are data, never SQL.

## Processing

1. Enforce the scope and hard exclusions, and resolve the approved relations without multiplying rows.
2. Apply search and filters on native fields in SQL.
3. If the request touches a converted field (Reporting value), convert the scoped rows in Python, then filter, sort, group and page that result. Household data is small, and the conversion rule stays in one place.
4. Count, sort with the id tie-breaker, group and return the page, or stream every row for an export.

Supporting indexes are checked against synthetic data with long balance histories.

## Accessibility and small screens

The drawer is a focused dialog with labelled tabs and inputs, visible focus and focus returned to the opening control. Reordering works without dragging. Sort direction, count changes and errors are announced, and no control depends on hover.

A phone layout is not part of this release. It touches entry, navigation, charts and dialogs as well as lists, and warrants its own epic and release, which would also cover the phone layout for balance entry (#66). Lists only have to stay usable at a narrow width, with no layout of their own: the table scrolls horizontally when its columns do not fit, and the drawer fills the width of a narrow window. Rows as stacked cards, a pinned column and a phone toolbar are left to that epic. Nothing in the shared table's state, server contract or saved preferences depends on the layout, so a later phone layout is a renderer, not a redesign.

## First lists

- **Balances** is the first list, with its own navigation entry across all accounts. It is the proof of concept for the framework: related fields, Value and Reporting value. The balance history on an account's page is a report of that account, not a list, and is outside this epic.
- **Accounts** becomes one table with Class and Stale as columns, replacing the Assets and Liabilities cards, their totals and the Open and Closed buttons. Whether it ships a default filter is decided with its page.
- Update balances is a data-entry screen and is not a list. Which other pages move over is decided after this design.

## Acceptance

- Balances and Accounts share the controls and the server-side contract. Update balances is unchanged.
- Every column sorts across the full result, with nulls last and a stable tie-breaker.
- Filters work across all pages, with the operators above, and applied conditions are visible. A hidden column keeps its filter.
- The relation tree is generated from the registry, shows no table twice in a path, never offers a denied column and has one row per base record.
- A relation column shows the display value and filters, sorts, groups and exports by it. Links follow the column, whatever its position.
- Reporting value follows the spec's conversion, shows the named currency when it has no rate, and no list shows a total.
- Group by works from any header and pages correctly.
- Columns, page size and saved filters persist per user across browsers. Shared filters are admin-managed, one default at most per list, and an explicit empty filter is distinct from none.
- Crafted requests and preferences cannot reach deleted records or any field outside the registry.
- The export contains every matching row in order, only the included columns, and the cases in the tests below.
- Tests cover empty results, Unicode, quotes, commas, line breaks, missing values, negative amounts, formula-like text and a request for an unauthorised field. Everything uses synthetic data. Backup, restore and upgrade are tested with the new tables.

## Out of scope

Multi-column sorting, nested AND and OR, named views beyond conditions, a phone layout, user-defined fields or queries, one-to-many fields, an export designer, historical related-record labels, totals, and an export of every account in one file (#117).
