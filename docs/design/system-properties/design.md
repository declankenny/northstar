# System Properties: design

Status: a draft dated November 3, 2026, for feature [#124](https://github.com/declankenny/northstar/issues/124). It has been checked against `docs/spec.md` and the change log schema in migration `0008`, but not against an implementation. Nothing here is the spec or the decisions log: those change only with the code.

Each item below is labelled. **Decided** means Declan agreed it. **Proposed** means it is the recommendation and has not been challenged or confirmed. **Open** means it is unresolved: do not guess it.

## Purpose

A single table holds the settings that belong to the whole installation, as typed values with a name. Admins can see and change the ones that are editable, every change is audited, and the rest of the application reads a setting through one function that returns a value of the right type. This document describes the table and the rules around it. It does not say which settings exist or what reads them.

## Tables

### `system_properties`

**Name** (decided). It does not carry the `sys_` prefix. The spec reserves that prefix for tables the application writes for itself, without audit columns and without an operation. Admins edit this table, so changes are audited and carry authors.

**Columns** (proposed unless noted):

| Column | Type | Notes |
|---|---|---|
| `id` | integer, primary key, autoincrement | Decided. The change log records a changed row by an integer `record_id`, so a text key cannot be logged. Every other table the application owns uses the same shape. |
| `name` | text, not null, unique | The key the code uses. See "Names". |
| `data_type_id` | integer, not null, foreign key to `ref_property_data_types` | Decides how `value` is validated and how it is edited. Never edited. |
| `value` | text, nullable | Always stored as text. NULL means unset. |
| `allow_null` | boolean, not null | Decided. When true the value may be set back to unset. When false the application never writes NULL to it, but a migration may create the property unset. |
| `hint` | text, not null | Plain text, at most 256 characters, never empty. Says what the setting does and what it accepts. Shown beside the name on the administration screen. Decided. See "Hint". |
| `read_only` | boolean, not null | When true the value cannot be changed through the application. Decided. |
| `created_at`, `created_by`, `updated_at`, `updated_by` | as every audited table | Decided. The two author columns are foreign keys to users. A row created by a migration is authored by the system user. |

Rows are created and removed by migrations only. No user and no endpoint adds or deletes a property, and a migration is also how a property changes its type.

### `ref_property_data_types`

One row per data type (decided). `id` and `name`. Loaded by a migration and never written at run time. See "Data types".

### `ref_property_lookups`

The allowed values of Lookup properties (proposed). `id`, `property_id` (foreign key to `system_properties`), `value` and `label`, unique on (`property_id`, `value`). Loaded by a migration and never written at run time. See "Lookup".

### `ref_property_validators`

The feature validations that apply to a property (decided). `id`, `property_id` (foreign key to `system_properties`), `validator` and `position`, unique on (`property_id`, `validator`) and on (`property_id`, `position`). `validator` is the name of a validation function in application code, never an expression, and `position` is the order the functions run in. A property with no rows is validated by its data type alone. Loaded by a migration and never written at run time. See "Validation".

### The `ref_` prefix

Decided in principle, details proposed. A table named `ref_*` is loaded by a migration, is never written at run time, has no audit columns, and is the target of foreign keys. The spec's rule that every table except the `sys_` ones has audit columns becomes "except the `sys_` and `ref_` ones". A test fails on any SQL write to a `ref_` table outside a migration, like the existing test that fails on SQL writes outside the writer. `account_classes` is the same kind of table but predates the prefix, so it keeps its audit columns: it is not renamed, because that would rebuild a released table for no gain, and the spec says so.

## Names

Proposed. A name is lowercase segments separated by dots, with at least two segments, for example `currency.exchangerate.staleness_days`. A CHECK enforces the pattern, and a test confirms every seeded name matches. The first segment is the property's group, and anything that lists properties groups by it. There is no category table, because the first segment does the same job and cannot disagree with the name. A name is a stable key: once a release has carried it, it is never renamed, so code and documentation can refer to it. A name that no release has carried can still be changed by a migration, as `balance.stale` was.

## Data types

The data type decides how a value is validated generically (decided). The validation lives in the setting service, which reads the type from `ref_property_data_types`, so the table is the one place that says what a property is. Conforming to the data type is the generic rule. It is not the only one: a property can also carry rules of its own, supplied by the feature that owns it (see "Validation").

| Type | Stored as | Valid when |
|---|---|---|
| String | the text itself | at most 256 characters (decided). Empty text is not a value: see "Unset". |
| Integer | decimal digits with an optional leading minus | a whole number inside the range JavaScript represents exactly, because the frontend reads it as a number |
| Date | an ISO calendar date, `YYYY-MM-DD` | a real date. Shown and edited in the person's format (decided in #130). |
| Lookup | the `value` of one allowed option | equal to the `value` of one of the property's rows in `ref_property_lookups` |

New types are added with a migration that adds a row here and a check for the type in the setting service, by the first feature that needs one. A Time, stored as `HH:MM` on a 24-hour clock without a time zone, is the likely next.

## Lookup

Decided in direction, details proposed. A Lookup property must hold one of a short, fixed list of allowed options, checked by the generic layer of the setting service.

- The options are the property's rows in `ref_property_lookups`. The `value` is what is saved in `system_properties.value`. The `label` is only what a person sees, so renaming a label never changes stored data.
- Lookup is for short lists only, the kind a person picks from at a glance. A list that is long, or that comes from somewhere else, is not a Lookup: it is a String whose property policy checks the value (see "Validation"). A Lookup never reads any table other than `ref_property_lookups`, so nothing stores a table name or a condition.
- A property has at most 20 options (decided). A test over the seeded rows enforces it.
- The database cannot enforce that a stored value is still an option, since a foreign key would apply to every property. The setting service enforces it, and a test checks that every stored Lookup value has its option.

## Validation

Decided in direction, details proposed. Validation has two layers and one framework that applies both.

**Generic layer.** Owned by the properties layer and the same for every property. The property exists, it is not read-only, the value conforms to its data type, for a Lookup the value is one of the allowed options, and an unset value is allowed only when `allow_null` is true.

**Property policy.** Owned by the feature that introduces the property. It supplies any additional constraint on the value, and any transition rule on changing the value from its current value. A policy is ordinary application code. It is never an expression stored in a column.

A policy is a plain function with a shared signature and no side effects (decided). It receives the property's identity (its name), the typed current and proposed values, the actor and the open database connection, which it may read but not write. It either raises a validation error carrying an error text written for the person who made the change, or returns a decision: accept, or accept and lock. Those are the only decisions for now (decided).

**Where policies live** (decided). Reusable validators, such as a positive integer, live with the System Properties framework. A validator specific to a feature lives beside the feature it serves. One explicit application mapping from stable validator names to functions, for example `"positive_integer": positive_integer`, is the only way a name is resolved: never a dynamic import or an arbitrary function lookup. `ref_property_validators.validator` stores one of those names. A name missing from the mapping is a configuration error, and the setting service refuses the change. A policy never writes a record. The service collects the decisions from every validator, and when none refuses it performs the value change and any lock as one update through the writer. That keeps validation predictable and respects the rule that one operation changes a record at most once.

Two kinds of rule use that one contract, and are kept apart in the tests. A **value rule** says whether a value is acceptable as a state, whatever the current value was. A **transition rule** says whether this change, from the current value to the proposed one, by this actor and in the current state, is allowed. A transition rule applies only when the proposed value differs from the current one, so a validator given the same value as both judges the value alone (decided). A **no-change save** is a submission that, once normalized, equals the stored value. The service applies the generic checks to it, so a read-only property still refuses, then writes nothing and runs no validator (decided). A value that has become invalid since it was stored, for example because a rule was tightened, is therefore not flagged until someone changes it.

**The framework** owns when and how policies run, and the feature owns what they enforce. The setting service runs the generic checks and then the validators listed for the property in `ref_property_validators`, inside the same write transaction as the write and before it commits. A check that depends on database state therefore sees the same state the write does. A failed check writes nothing and raises its error text to the caller, so an invalid configuration is refused when it is saved and not discovered later in an unrelated operation. The generic checks (unknown property, read-only, wrong type, not an allowed option, unset not allowed) give error text of the same kind. The setting service stops at the first refusal and raises it to its caller unchanged (decided), and the administration screen shows it as an alert against the property that was being saved. Other callers, such as the command line, print the same text.

**Declared only when there is something to declare.** The data type checks always run. The property's rows in `ref_property_validators` name the feature validations that run after them, in `position` order, and a property with no rows is validated by its data type alone. The functions are application code, found by the name in the table through the explicit mapping above, so a rule written once can be attached to many properties. A validator takes no parameters (decided): a rule that differs by a number is a separate function, until two properties need the same rule with different values. Validators run in `position` order, which is unique within a property so the order never needs a tie-breaker. A `validator` name that does not resolve to a function fails closed at runtime: the change is refused, nothing is written, and the failure is logged. Tests guard it in three ways:

- every `validator` name must be in the mapping, so a misspelt name cannot silently never run;
- every seeded value, when not unset, must pass the data type check and its validators, which are called with the seeded value as both the current and the proposed value so that no transition rule applies. This tests the seeded state. It does not apply the read-only check, because a legitimate initial state, an unset property or a read-only one, need not be reachable through the setting service;
- a feature's tests exercise accepted values, rejected values and permitted transitions through the setting service against a migrated database, not against the validator functions alone. That also proves the rows in `ref_property_validators` are attached, which a check on seeded values cannot show, since a migration that omitted a row would still pass it.

A function no row names is not an error.

**What a feature delivers** when it introduces a property, in the same change:

- a migration that creates the property row;
- the rows in `ref_property_validators` for the property, if it has feature validations;
- the validation and transition code the policy needs;
- tests for accepted values, rejected values and permitted transitions, run through the setting service against a migrated database.

**One path.** Every application write of `value` goes through the setting service, whether it comes from the administration screen, the command line or another workflow, so none can skip either layer.

**Locking.** The generic API cannot change `read_only`. A policy can declare that a transition locks the property, and the service then writes the new value and sets `read_only` in the same audited transaction. The lock is the feature's decision, taken through its own operation, and is never a flag an admin edits.

Code that reads a property may still check the value defensively. It should not be the first place a bad value is found.

## Hint

Decided. Every property carries a `hint`: a short statement of what the setting does and anything its validators enforce, for example "Days before an exchange rate counts as stale. Enter 1 or more." Validators are code and cannot describe themselves, so the hint is where an admin learns a rule before being refused by it.

- It is plain text of at most 256 characters, the same limit as a String value, with no markup.
- It is required and never empty, and a test over the seeded rows fails on an empty one, so every setting an admin sees is described.
- It does not repeat the format of the data type, which the screen shows by itself (an Integer input takes a whole number). It says what is specific to the setting.
- It is set by the migration that creates the property and changed only by a migration, so it is not an admin field. It is logged in the change log like any other column.
- It can drift from the validators it describes, and no test can check prose. Reviewing the hint with the validator is part of reviewing the feature that adds the property.

## Unset

Decided that `allow_null` controls it, details proposed. A property is unset when its `value` is NULL. Unset is the only way to say "no value": empty text is never stored, so a blank submission means unset. Blank means empty after removing leading and trailing whitespace, so whitespace-only input is blank too (proposed). The service normalizes the submitted text this way once, before validation and before it decides that a save changes nothing, so every check sees the same value. Setting a property to unset is refused when `allow_null` is false, and otherwise skips the data type checks, since there is no value to check. The property's validators still run, with the unset value, so a feature can refuse to clear a setting it needs or can only allow it from a certain state. A migration may create a property unset even when it does not allow NULL, so a property can start empty and then never be cleared once set.

On the administration screen the same facts use plain words (decided): a property that allows NULL is marked **Optional**, an empty value shows "Not set", and refusing to clear a property that does not allow NULL says "This setting is required." The words "unset" and `allow_null` stay in this document and in the code.

## Read-only

Decided. `read_only` is data, not a rule in code. When true, the value cannot be changed through the generic API. It is set by a migration, or by the service when a policy's transition locks the property (see "Validation"), so the lock is visible in the data and nothing else needs a special case.

## Access and audit

**Access** (decided). Only admins can see or change properties through the administration screen and its API, and the server enforces it, not only the page. The restriction applies to that screen and API: server code reads properties for every request, because a setting can affect what every user sees.

**Editing** (decided). Through the administration screen and its API only `value` can change, and only on a property that is not read-only. A name, a type, a hint and the validators attached to a property are changed by migrations. The read-only flag is changed by a migration or by a policy's locking transition, never by an admin.

**Audit** (proposed). A change is made through the writer as part of an operation whose kind matches where it came from (`ui_edit` from the screen, `cli` from the command line), so the existing change log records who changed what, when, and the old and new value. `system_properties` has a row in `sys_audited_fields` for each of its columns, and the id and the `updated_at` and `updated_by` columns are registered with `is_logged` 0, as the spec does for other tables. A save that changes nothing writes nothing. There is no version check (decided): if two admins save the same property, the later save wins, provided it still passes validation against the current state, so a locking transition made in between makes it refuse. The change log shows both saves.

## Reading and setting

**Reading** (proposed). One function takes a name and returns the value as its type: a string, an integer, or the value of a lookup option. It raises a clear error for a name that does not exist, so callers never parse `value` themselves. A NULL value is returned as unset and the caller decides what that means.

**Setting** (decided). One function, the setting service, takes an operation, a name and a text value. In one write transaction it applies the generic checks and the property's policy (see "Validation"), writes through the writer and returns the stored value. Every path that changes `value` uses it, so none writes a value unvalidated.

## Open questions

None at present.
