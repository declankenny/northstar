# Managing lists: design

Status: a draft proposal, dated November 2, 2026, not yet reviewed. It has not been checked against the code, `docs/spec.md` or `docs/decisions.md`; the open questions are in the epic [#120](https://github.com/declankenny/northstar/issues/120). Nothing here is the spec or the decisions log.


Northstar lists will share sorting, filtering, configurable columns, pagination, and CSV export. Available columns include explicitly supported fields from related records. Database-backed definitions will describe each list, while shared UI components and server-side query handling provide consistent behavior. Users can tailor their views and exports without changing the records being displayed.

## Scope

A list is a read-only display of records produced by a SELECT. Row actions may open a separate edit screen or dialog; they do not make the list itself a data-entry screen.

The initial scope is Accounts, Account types, Users, and an account's Balance entries. Update balances is a data-entry screen and is excluded. Form dropdowns, charts, and dashboard tiles are also outside this proposal.

Accounts and Account types pages will each become one table with a Class column. The separate Assets and Liabilities groups will be removed in the same release that introduces filtering. Users can filter by class when they want the previous separation.

## Shared list layout

Each list has a search field and two entry points above its table: **Filters (N)** and **Columns**. They open the corresponding tab in one right-side drawer. N counts applied field conditions; search remains visible in its own field. Active filter chips remain above the table when the drawer is closed.

An **Export CSV** action above the table exports the applied list configuration. The table has clickable data-column headings, a visible sort indicator, and existing row actions where applicable. A footer contains the matching record range, page navigation, and rows-per-page selector.

For example: **26–50 of 138 · Page 2 of 6 · Previous · Next · Rows per page: 25**.

## Sorting

Every displayed data column supports sorting. Action controls are excluded. Clicking a heading selects that column; clicking it again reverses direction. Only one user-selected sort column is active at a time.

Text sorts alphabetically without case sensitivity, numbers by their numeric value, and dates chronologically. Empty values sort last in either direction. Money is sorted using integer cents, not formatted strings.

The backend adds a stable record ID as the final ascending tie-breaker. For example, sorting by latest balance descending is conceptually `ORDER BY latest_balance DESC, id ASC`. This keeps equal values in a predictable order; it does not expose a second sort control. Records may still move between pages when underlying data changes.

Proposed default sorts are Account name ascending, Account type name ascending, User name ascending, and Balance entry date descending. Selecting a sort returns the list to page 1. If a user hides the active sort column, revert to the default sort and make its indicator visible.

## Filter drawer

The Filters tab presents one row per condition. Each row contains a field, an appropriate operator, its value controls, and a remove action. **Add filter** offers the list's available display columns that do not already have a condition. Every display column supports filtering, and only display columns can be filtered. There are no filter-only fields. A display column remains available for filtering when it is not currently Included in the table.

Each field has at most one condition. Conditions across fields combine with AND. Multiple selected values within a category combine with OR. For example, Status is Open AND Type is any of Checking or Savings.

| Field type | Supported controls |
| --- | --- |
| Text | Contains, equals, is empty, is not empty |
| Category | Is any of, using multiple selections |
| Money or number | Equals, at least, at most, between; empty checks where applicable |
| Date | Before, after, between; empty checks where applicable |
| Boolean | Yes or No |

Between includes both endpoints. Before and after are exclusive; the labels must communicate this consistently. Invalid ranges prevent Apply and show an inline explanation. Empty values are distinct from zero and do not match numeric ranges. Dates remain calendar dates; money inputs are converted to integer cents.

Search matches designated available text fields such as names, types, emails, and notes, regardless of column visibility. Search combines with field conditions using AND. Search changes are debounced, run on the server, and return to page 1.

Accounts initially has **Status is Open**. Removing that condition includes open and closed accounts. The former Open/Closed buttons are replaced by this condition. Status must therefore be an available display column. Class, Type, balance freshness, latest balance, and latest balance date are additional filter candidates; balance freshness must also be an available display column to support its filter.

Other initial filters include date, balance, Change, and note text for Balance entries; class, stale-after days, and account count for Account types; and role and date added for Users. Each corresponds to an available display column. Balance entry notes must be available as their own display column to support a separate Note filter.

## Column drawer

The Columns tab presents two side-by-side lists: **Available but not included** and **Included**. Included shows the table's data columns in display order. Available but not included groups the remaining eligible display columns under the base record and expandable related records, with fields alphabetically ordered within each group. That arrangement does not assign them a table position.

Users can drag a column between the two lists. Dropping a column into Included assigns it the chosen insertion position, with a visible insertion marker between rows. Users can also drag columns up or down within Included to reorder them. Moving a column out of Included clears its position to NULL; it retains no previous position. Adding it again assigns a new position at the user's chosen location, rather than restoring its old position or automatically appending it.

Provide equivalent controls without dragging: Add with a choice of insertion location, Remove, and Move up / Move down. These controls support keyboard and touch use. On narrow screens, stack the two lists while preserving the same operations. Included positions are consecutive and unique; insertion, removal, and reordering renumber the affected included columns. These changes remain drafts until Apply changes.

Availability, inclusion, and order are separate properties. Filtering is supported for every available display column, with operators determined by its data type. Removing a column from Included does not remove it from the available display columns or remove a condition on that column; its filter chip remains visible. Fields that are not available display columns cannot appear in the filter picker or be accepted as user-facing filters by the backend.

Essential identifying columns remain visible. Proposed essential columns are Account name, Account type name, User name, and Balance entry date. They may move within the data columns. Action controls remain at the end and are not part of the user-configurable column set.

The Columns tab provides **Restore default columns**, which restores application-defined visibility and order.

## Related record fields

The shared available-column catalog can expose fields reached through approved many-to-one relationships. A balance can expose its Account name and, through Account, its Account type name. Following these relationships preserves one result row per balance.

Both the Columns selector and Add filter picker present expandable related-record groups. For example, Balance exposes Date, Amount, Change, and Note; Account exposes Name and Status; expanding Account type beneath Account exposes Name and Class. Group headings are navigation controls, not selectable fields. Users select or drag a leaf field into Included at their chosen position, or select it for a filter condition. Included columns, filter chips, and export headers use unambiguous labels such as **Account name** and **Account type name**.

Related fields belong to the same catalog as direct fields and support the same display, filter, sort, and export behavior. Stable path-based keys such as `account.name` and `account.type.name` distinguish fields with similar labels. The server resolves those keys through approved relationship mappings, not through client-supplied joins or arbitrary database traversal. Existing type or class columns that represent the same relationship field use one canonical catalog entry rather than appearing twice.

The initial release supports a small explicitly defined set of related fields, including Balance → Account → Account type. Only approved many-to-one paths are exposed; one-to-many traversal is excluded because it can produce multiple values or rows for one base record. Do not automatically expose every database relationship or field.

Backend authorization and hard exclusions apply to every related record. A missing or inaccessible optional related record contributes empty values and must not duplicate or accidentally remove an otherwise eligible base row. Required parent-scope rules may independently exclude the base row. Filter choices and search must not reveal inaccessible related values. Filtering on a related field then follows the normal empty-value rules.

Related fields show the current related record values. Renaming an account or account type changes the label shown beside earlier balances and in subsequent exports. Historical labels would require separate historical data and are outside this proposal. In the account-specific Balance entries list, Account name repeats on every row but can provide useful export context. A cross-account Balances list is not introduced by this feature.

## Applying and saving a view

The drawer has shared **Apply changes** and **Cancel** actions. Users can change both tabs before applying. Switching tabs preserves drafts and indicates which tabs have pending changes. Cancel, Escape, and closing discard unapplied changes. Applied filter chips reflect the committed view only; removing a chip applies that removal immediately.

Applying column visibility and order saves them as user preferences. Page-size changes also save automatically. Applying filters changes the current view; **Save as my default** explicitly saves the applied field conditions as the user's default. Search text and current page are not saved as defaults.

| Action | Effect |
| --- | --- |
| Clear filters | Removes all user-facing field conditions; does not remove backend restrictions or search text |
| Restore default filters | Restores the effective default: the user's saved default, otherwise the application's |
| Use application default filters | Removes the user's saved filter override and restores the application defaults |
| Restore default columns | Restores application visibility and order; Apply saves that choice |

An explicitly saved empty filter set means no user-facing default conditions. It must be distinguishable from having no saved override.

Effective state is resolved in this order: application defaults, saved user preferences, then explicit current-view state. Sort, search, filters, and page belong in the URL so refresh, browser Back, and returning from a record restore the current view. Serialize an explicitly cleared filter set so it does not accidentally reload default filters. Avoid storing sensitive filter values in application logs.

## Pagination and result states

Offer page sizes of 10, 25, 50, and 100, with an application default of 25. Save the user's choice per list in the database so it follows the user across browsers and devices. Balance entries use one list preference across accounts; the account itself remains a required query scope.

Filtering, sorting, and changing page size return to page 1. Disable unavailable navigation controls. Keep page sizing available even when there is only one page. If an edit or deletion leaves the requested page out of range, use the last valid page.

Counts and any list aggregate describe all matching records, not only the visible page. If Accounts displays aggregate balances, report assets and liabilities separately with clear filtered-total labels; do not introduce an ambiguous combined balance. List controls do not change dashboard totals or chart ranges.

Distinguish loading, failed requests, an empty underlying list, and no matching results. Failed requests offer retry and retain the last successfully applied view. Ignore stale responses from superseded requests. After a record action, refresh the current view; a changed record may no longer match its filters.

## CSV export

**Export CSV** uses the existing list configuration as the export definition. No separate export designer is needed. Make the scope visible beside the action, for example **138 matching rows**, so users understand that export includes all matching pages.

| Aspect | Export behavior |
| --- | --- |
| Rows | All matching records across all pages, within the list's required scope |
| Columns | Included data columns in their applied order, including selected related fields |
| Filters and search | Currently applied conditions and search text |
| Sorting | Current sort and the stable record ID tie-breaker |
| Page size and current page | Do not restrict the export |
| Unapplied drawer changes | Excluded |
| Action controls and aggregate summaries | Excluded from the record rows |

Generate exports on the server through the same validated field mappings, filters, sorting, and backend restrictions as the list. The export request captures the applied configuration when the user starts it; subsequent UI changes do not alter an in-progress export. Read the export from a consistent database snapshot. Values reflect data when the export runs, which may differ from the earlier table response or displayed count. An empty result produces a CSV with column headers and no data rows.

Use UTF-8, clear unambiguous column headings, calendar dates in `YYYY-MM-DD` format, and money as decimal amounts without currency symbols or thousands separators. Missing values produce blank cells. Serialize booleans consistently as `true` or `false`, and use plain text labels for category values. Export underlying values rather than HTML, badges, links, or presentation-only truncation.

Use a CSV serializer that correctly handles commas, quotes, and embedded line breaks. Neutralize spreadsheet formula prefixes in text cells; CSV quoting alone does not prevent formula execution. Preserve actual numeric values, including negative money amounts, as numeric output. Verify the chosen text-escaping policy with spreadsheet applications during implementation.

Provide progress or busy feedback and a clear error with retry if generation fails. Stream large exports rather than loading every row into application memory. Use a descriptive filename containing the list key and export date. CSV export does not create or change saved preferences.

## Database definitions and preferences

The following is a logical model; exact DDL and naming will follow existing schema conventions during implementation.

| Structure | Main contents |
| --- | --- |
| `list_definitions` | Stable list key, definition version, default sort field and direction, default page size, structured default filter conditions |
| `list_columns` | List key, stable field key or related-field path, label, data type, related-group path, nullable default position, required visibility, search eligibility; all entries support display, sorting, filtering, and export |
| `user_list_preferences` | User ID and list key, page size override, whether a custom column configuration exists, optional saved default filter conditions |
| `user_list_columns` | User ID, list key, field key, nullable position within the user's custom column configuration |

`list_columns` contains only available display columns. Every entry supports sorting and filtering; there is no separate filterability flag or filter-only field category. Each list/field pair is unique; each user/list preference pair and user/list/field column preference is unique. A non-NULL position means the column is included; NULL means it is not included. Do not store a separate visibility flag that can conflict with position. Included positions are consecutive positive integers and unique within their list configuration. Required columns must have a position. Default positions remain application settings; removing a column from a user's configuration clears that user's position only.

When no custom column configuration exists, use application default positions. When a user first applies a custom configuration, persist each eligible display field with its chosen position or explicit NULL. Within that configuration, NULL means intentionally excluded, not a request to inherit the application position. Store filter conditions as validated structured data rather than SQL. Column preferences must reference permitted field keys. Include normal audit metadata consistent with the application schema.

Definitions describe the UI contract. Code maps stable field keys and approved related-field paths to query expressions, relationship joins, renderers such as money, dates, or account links, and CSV value serializers. Relationship metadata controls the expandable picker groups but cannot authorize a join that code does not support. Neither definitions nor preferences contain executable SQL or UI code. Each exposed data column must have supported server-side sort and filter expressions and an export serializer.

Ship initial definitions through migrations. Renaming a label preserves its key. Removing a field drops obsolete preferences safely; invalid values fall back to supported defaults. Preserve valid user column order when adding a column, then insert the new field according to its application default position and visibility. Definition versions allow deliberate preference migration when semantics change.

## Backend rules and query processing

Authorization, required record scope, and hard exclusions are enforced by the backend and cannot be changed by list configuration or user preferences. Soft-deleted records are always excluded. The soft-delete flag is absent from available columns, filters, and search fields. Existing restrictions on system-user visibility also remain backend rules.

For Balance entries, calculate Change in a database view using the previous chronological non-deleted entry for the same eligible account. The earliest entry has no Change value. The view's chronology is independent of all UI sort orders and filters. Enforce hard exclusions before calculating that history; authorize access to the account independently when querying the view.

The logical query order is:

1. Enforce backend scope and hard exclusions; expose derived values from the relevant database view and resolve approved related-field joins without multiplying base rows.
2. Apply search and user-facing filter conditions to that result.
3. Calculate matching counts and any defined aggregates.
4. Sort the full matching result with the stable ID tie-breaker.
5. Return the requested page for the UI, or serialize all matching rows and Included columns for CSV export.

Validate list keys, field keys, operators, values, sort direction, and pagination bounds on the server. Parameterize values and allow only code-approved query expressions. Unknown or unsupported request fields receive a clear validation error. Reconcile obsolete saved preferences separately rather than silently broadening an invalid explicit query.

List responses provide rows, matching count, resolved pagination, and any defined aggregates. Related counts and rows should come from a consistent database read. Supporting indexes and query plans should be checked against representative synthetic data, particularly long balance histories.

## Accessibility and smaller screens

The drawer becomes a full-screen sheet on small screens. Provide a focus-managed dialog, labelled tabs and inputs, visible keyboard focus, and focus return to the opening control. Column reordering must work without dragging. Announce sort direction, result-count changes, and validation errors. Preserve access to all columns through horizontal table scrolling where needed.

## Acceptance criteria

- All four scoped lists use shared controls and server-side processing; Update balances remains outside the change.
- Accounts and Account types each have one table, with Class filtering available in the same release.
- Every displayed data column sorts correctly across the complete result; ties use stable IDs and nulls remain last.
- Filtering works across all pages, supports the specified operators, and visibly identifies applied conditions.
- Every available display column supports filtering, whether currently Included or not. The filter picker and backend reject fields outside that display-column set; there are no filter-only fields.
- Approved related fields appear in expandable groups in both pickers and can be included, filtered, sorted, and exported. Balance → Account → Account type preserves one row per balance; missing and inaccessible related values follow the defined backend rules.
- Drawer changes apply together or are discarded together; hiding a column does not remove its filter.
- Column order, visibility, page size, and explicitly saved default filters persist per user and list across browsers.
- Columns can move between Available but not included and Included, with insertion at any chosen position and reordering within Included. Removing a column sets its position to NULL; adding it again assigns only the newly selected position. Equivalent keyboard and touch controls support all operations.
- Clear, restore, and application-default actions have distinct behavior, including explicitly empty defaults.
- Soft-deleted records and other forbidden records cannot be exposed through crafted list requests or preferences.
- Balance Change remains identical for a given record under different UI filters, sorts, and page sizes.
- CSV export contains all matching records in the applied sort order and only Included columns in their chosen order, including related fields. Pagination and unapplied drawer changes do not affect it.
- CSV verification covers empty results, Unicode, quotes, commas, embedded line breaks, missing values, negative amounts, formula-like text, and rejection of unauthorized fields or relationships.
- Counts, aggregates, empty states, request failures, back navigation, and page correction behave as specified.
- Keyboard operation, small-screen layout, and preference migration are verified with synthetic data.

## Delivery and future scope

Implement the shared definitions, preferences, and query contract first, including the Balance Change view and approved related-field mappings. Then implement the common table controls, drawer, and CSV export and migrate the four lists. CSV export and the initial related-field catalog are part of the initial release. Release the unified Accounts and Account types tables together with filters, and verify the acceptance criteria before shipping.

Multi-column sorting, nested AND/OR expressions, and multiple named saved views are out of scope with no roadmap commitment. Column configuration does not include arbitrary computed columns, user-authored queries, unrestricted relationship traversal, or one-to-many related fields. A separate export designer, historical related-record labels, and a cross-account Balances screen are outside the initial scope.

### Proposed backlog item

**Admin editor for application list defaults**

Allow administrators to configure default column visibility and order, default filter conditions, sort, and page size for existing lists. Expose only fields and operations already supported by the application. Validate changes and provide restoration of shipped defaults.

The editor changes application defaults without modifying backend access rules, hard exclusions, query logic, or explicitly saved user preferences. This is a backlog proposal, not part of the initial release.

### Possible Libraries

Use TanStack Table for shared table behavior and dnd kit for the column selector’s drag-and-drop interactions. This combination supports the proposed interface while allowing Northstar to retain its existing appearance.

**TanStack Table**

TanStack Table provides sorting, filtering, pagination, column ordering, and visibility state without prescribing the visual interface. Its server-side mode lets Northstar’s backend perform the query operations while the frontend manages controls and displays returned rows. TanStack Table documentation

Build one shared Northstar list component around it. Each list supplies its definition and field renderers. The Filters and Columns drawer, Apply/Cancel behavior, and preference persistence remain application code.

**dnd kit**

Use dnd kit to support moving columns between Available but not included and Included, inserting at a chosen position, and reordering Included columns. It supports sortable items across multiple lists. dnd kit documentation

Northstar retains responsibility for clearing removed positions to NULL, assigning new positions, enforcing required columns, and providing equivalent controls without dragging.