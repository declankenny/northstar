# v0.3 implementation plan

A draft order of work for the whole v0.3 milestone: the multi-currency and locale design in [design.md](design.md), and the standalone features that ship beside it. Each step is one feature branch and one pull request into `main`. A step is done when its issue is closed.

Every step follows the working rules: the spec and `docs/decisions.md` change in the same pull request as the code, a mockup comes before any new screen, schema changes are tested on a copy of a database, and tests use synthetic data. Each new dependency states its reason. Every step that changes the schema also tests backup, restore and upgrade from v0.2.

## Order and dependencies

Steps with the same number can be done in any order or in parallel.

| Seq | Feature | Epic | Issue | Depends on |
| --- | --- | --- | --- | --- |
| 1 | React sign-in screen | none | [#65](https://github.com/declankenny/northstar/issues/65) | none |
| 1 | New brand mark, light and dark | none | [#76](https://github.com/declankenny/northstar/issues/76) | none (best after #65) |
| 2 | System Properties | none | [#124](https://github.com/declankenny/northstar/issues/124) | none |
| 3 | Currency catalog, account currency and USD migration | #56 | [#125](https://github.com/declankenny/northstar/issues/125) | #124 |
| 4 | Locale core: per-user locale, parser, date formatter | #56 | [#126](https://github.com/declankenny/northstar/issues/126) | #125 |
| 4 | Importer and exporter on account currency | #56 | [#128](https://github.com/declankenny/northstar/issues/128) | #125 |
| 4 | Rates and conversion | #56 | [#130](https://github.com/declankenny/northstar/issues/130) | #125 |
| 5 | Locale controls: profile and new-user flow | #56 | [#127](https://github.com/declankenny/northstar/issues/127) | #126 |
| 5 | Import number style defaults from locale | #56 | [#129](https://github.com/declankenny/northstar/issues/129) | #126, #128 |
| 5 | Fetching rates and the Add Currency wizard | #56 | [#131](https://github.com/declankenny/northstar/issues/131) | #130, Frankfurter checks |
| 6 | First-run setup page | none | [#64](https://github.com/declankenny/northstar/issues/64) | #65, #124, #125, #126 |
| 7 | Integration, recovery rehearsal and operator guide | #56 | [#132](https://github.com/declankenny/northstar/issues/132) | all of the above |

The epic is [#56](https://github.com/declankenny/northstar/issues/56). System Properties, the setup page, the sign-in screen and the brand mark are standalone features in the milestone: they serve other purposes, so they are not completion requirements of the epic. System Alerts ([#133](https://github.com/declankenny/northstar/issues/133)) is a backlog feature with no milestone and is not part of v0.3.

## Decided for this plan

- **The money column is not renamed.** `amount_cents` keeps holding integers, now in the account currency's minor unit. A decisions entry in step 3 records the meaning, and the spec, `CLAUDE.md` and `docs/schema.md` say "minor units". Integer minor units suit SQLite, which has no decimal type and sums integers exactly in the database.
- **An existing installation's system currency** is USD if it has at least one account, and unset otherwise. While it is unset, the Add Account action warns and the server refuses to create an account, until an admin sets the currency on the System Properties screen.
- **`python -m northstar.users create` is removed** in v0.3, replaced by the setup page. `reset-password` stays.
- **The setup page's only condition** is whether an admin exists.

## Steps

### 1. React sign-in screen (#65) and brand mark (#76)

- Scope: the server-rendered sign-in page becomes a React screen with the same throttling, cookies and content security policy; then the new mark in the sidebar and sign-in page, with a light and a dark variant that follow `data-theme`.
- Tests: the existing sign-in and throttling tests against the new screen; the sign-in page needs no inline script or style.
- Docs: a mockup of the brand mark variants first; the spec's sign-in sentence changes with the code.

### 2. System Properties (#124)

- Scope: the settings table and the System Properties screen where all system properties live. v0.3 settings: the system currency, the default locale for new users and the rate staleness threshold. A control to set the system currency while it is unset.
- Tests: audited changes by admins; the currency settable only while unset; migration on a copy of a database.
- Docs: a mockup first, the table shape drafted on the issue, a decisions entry and `docs/schema.md`.

### 3. Catalog, account currency and migration (#125)

- Scope: the currencies table and catalog, `currency` on accounts set at creation and never edited, the migration rule for the system currency, the Add Account guard, and the single-currency interface.
- Tests: precision and entry limits per currency; an account's currency cannot change; migration from v0.2 for both the USD and the unset cases; the guard refuses on the server as well as in the UI; backup, restore and upgrade.
- Docs: a mockup of the currency choice first; the minor-unit decisions entry above.

### 4a. Locale core (#126)

- Scope: a saved locale per user with a system default, the shared server-side amount parser, and the chosen date formatter.
- Tests: parser vectors per supported locale including refused ambiguous input; a default affects new users only.
- Docs: a decisions entry for the date approach.

### 4b. Importer and exporter (#128)

- Scope: import trusts the account's currency, drops the Currency column mapping, and uses the account's precision for number-style detection and the review line; export writes the account's currency precision.
- Tests: no minor unit and three-decimal cases; round trip of an export; undo of an import made before the migration.

### 4c. Rates and conversion (#130)

- Scope: the rate table, manual entry and correction by an admin, the conversion with per-account rounding, the zero-balance rule, and the missing-coverage behaviour.
- Tests: hand-calculated fixtures; halfway cases of both signs; no future rate used; corrections change valuation and not balances.
- Docs: a mockup of rate maintenance and of the missing-coverage state first.

### 5a. Locale controls (#127)

- Scope: the locale control on the profile screen and on the admin's new-user flow.
- Docs: a mockup first.

### 5b. Import number style from locale (#129)

- Scope: the number style offered on a spreadsheet import starts from the user's locale and the user still confirms it. The Northstar CSV stays locale-independent.
- Tests: the offered default per locale; an export imports identically in any locale.

### 5c. Fetching rates (#131)

- Scope: `python -m northstar.rates fetch`, the Add Currency wizard with its rerun, the Fetch now button and the staleness warning.
- Tests: fetch never overwrites; a missed run is repaired by the next; provider timeout and invalid responses; a partial failure keeps what was committed.
- Docs: the cron example in `docs/operating.md`, and a mockup of the wizard first.

### 6. First-run setup page (#64)

- Scope: an unauthenticated page, available only while no admin exists and guarded by a one-time token printed in the container log, that creates the first admin and, in the same motion, sets initial system properties. It replaces `users create`, which is removed together with its operating guide text. The token lifecycle, whether the currency field is required, and the reserved route name are drafted on the issue.
- Tests: the page is gone once an admin exists; a wrong or reused token is refused; two simultaneous submissions create one admin; the admin and the properties are written in one transaction.
- Docs: a mockup first; the spec's "First admin" bullet and `docs/operating.md`.

### 7. Integration and release (#132)

- Scope: upgrade from v0.2 end to end, a restore of a pre-upgrade backup, a recovery rehearsal and the operator guide. The release candidate follows.
- Tests: the upgrade of an installation with accounts, and of one without; a fresh installation through the setup page.
