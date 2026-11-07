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
| 3 | Admin Currencies page: the catalog as a read-only list | #56 | [#141](https://github.com/declankenny/northstar/issues/141) | #125 |
| 4 | Locale core: per-user locale, parser, date formatter | #56 | [#126](https://github.com/declankenny/northstar/issues/126) | #125 |
| 4 | Importer on account currency | #56 | [#128](https://github.com/declankenny/northstar/issues/128) | #125 |
| 4 | Rates and conversion | #56 | [#130](https://github.com/declankenny/northstar/issues/130) | #125 |
| 4 | Accounts in other currencies | #56 | [#149](https://github.com/declankenny/northstar/issues/149) | #130 |
| 5 | Locale controls: profile and new-user flow | #56 | [#127](https://github.com/declankenny/northstar/issues/127) | #126 |
| 5 | Fetching rates | #56 | [#131](https://github.com/declankenny/northstar/issues/131) | #130, Frankfurter checks |
| 6 | First-run setup page | none | [#64](https://github.com/declankenny/northstar/issues/64) | #65, #124, #125, #126 |
| 7 | Integration, recovery rehearsal and operator guide | #56 | [#132](https://github.com/declankenny/northstar/issues/132) | all of the above |

The epic is [#56](https://github.com/declankenny/northstar/issues/56). System Properties, the setup page, the sign-in screen and the brand mark are standalone features in the milestone: they serve other purposes, so they are not completion requirements of the epic. System Alerts ([#133](https://github.com/declankenny/northstar/issues/133)) is a backlog feature with no milestone and is not part of v0.3.

## Decided for this plan

- **The money column is not renamed.** `amount_cents` keeps holding integers, now in the account currency's minor unit. A decisions entry in step 3 records the meaning, and the spec, `CLAUDE.md` and `docs/schema.md` say "minor units". Integer minor units suit SQLite, which has no decimal type and sums integers exactly in the database.
- **An existing installation's system currency** is USD if it has at least one account, and unset otherwise. While it is unset, the Add Account action warns and the server refuses to create an account, until an admin sets the currency on the System Properties screen.
- **`python -m northstar.users create` is removed** in v0.3, replaced by the setup page. `set-password` stays (the plan first called it `reset-password`).
- **The setup page's only condition** is whether an admin exists.
- **#126 and #127 ship together** as stacked pull requests, so the locale can be chosen in the interface from the first release.

## Steps

### 1. React sign-in screen (#65) and brand mark (#76)

- Scope: the server-rendered sign-in page becomes a React screen with the same throttling, cookies and content security policy; then the new mark in the sidebar and sign-in page, with a light and a dark variant that follow `data-theme`.
- Tests: the existing sign-in and throttling tests against the new screen; the sign-in page needs no inline script or style.
- Docs: a mockup of the brand mark variants first; the spec's sign-in sentence changes with the code.

### 2. System Properties (#124)

- Scope: the settings table, the setting service with its data type checks and feature validators, and the System Properties screen where all system properties live. A property is added by the feature that reads it, so the system currency (and its control while unset) arrives with the catalog, the default locale with the locale feature, and the rate staleness threshold with fetching rates. The design is `docs/design/system-properties/design.md`.
- Tests: audited changes by admins; refused values through the service against a migrated database; the seeded state; migration on a copy of a database.
- Docs: a mockup first, the table shape drafted on the issue, a decisions entry and `docs/schema.md`.

### 3. Catalog, account currency and migration (#125)

- Scope: the currencies table and catalog, `currency` on accounts set at creation and never edited, the migration rule for the system currency, the Add Account guard, and the single-currency interface.
- Tests: precision and entry limits per currency; an account's currency cannot change; migration from v0.2 for both the USD and the unset cases; the guard refuses on the server as well as in the UI; backup, restore and upgrade.
- Docs: a mockup of the currency choice first; the minor-unit decisions entry above.

### 3b. Admin Currencies page (#141)

- Scope: a read-only admin page, Currencies under Admin in the sidebar, listing the catalog as stored with each currency's decimal places, its enabled flag and its live account count, with search and filters. It does not know the system currency. The name links to a currency's page, where the enable switch and the rates live (#130).
- Tests: the list and counts through the endpoint (open and closed counted, deleted not), admin-only on the server and the page, search and filters.
- Docs: a mockup first, which was agreed on the issue.

### 4a. Locale core (#126)

- Scope: the `ref_locales` catalog (six locales) generated into a migration, `users.locale` and the `ui.locale.default` property, the shared amount parser and the date and amount formatter with their shared test vectors, `/api/me` carrying the locale, and the authenticated shell waiting for `/api/me`. The design is [locale.md](../locale.md).
- Tests: parser and formatter vectors per supported locale, including refused input; a changed default affects new users only; the foreign key rejects an unsupported tag; backup, restore and upgrade.
- Docs: a decisions entry for the table, the generator and the date approach.

### 4b. Importer (#128)

- Scope: import trusts the account's currency, drops the Currency column mapping and symbol block, and uses the account's precision for number-style detection and the review line. The Date picker stays inline and Balance gains an inline number-style picker with an interpreted-amount preview. Exports are outside this feature.
- Tests: no minor unit and three-decimal imports, ambiguous styles and excess precision; importing existing Northstar CSV independently of locale; undo of an import made before the migration.

### 4c. Rates and conversion (#130)

- Scope: the rate table and the view `account_days`; a page for each currency, opened from its name on the list, with the Enabled switch (saved at once), the date its rates start from, and adding and correcting rates in one dialog; the system currency always enabled; a new foreign account needing a stored rate; the conversion with per-account rounding done in Python; the missing-coverage rule (a series starts at the first date from which every later date can be converted, and says so); the stale-rate warning on the currency page; and the Date system property type with `currency.rate.stale_days` and `currency.rate.start.default`. Per-account views stay in the account's own currency. The design is on #130.
- Tests: hand-calculated fixtures; halfway cases of both signs; liabilities; differing decimal places; no future rate used; a date with no rate is refused, not partly totalled; the series start with a gap in the middle; corrections change valuation and not balances; a rate cannot be deleted or re-dated; the system currency cannot be switched off; backup, restore and upgrade.
- Docs: mockups of the currency page, the Add rate dialog and the chart note were agreed first.

### 4d. Accounts in other currencies (#149)

- Scope: the Add account dialog and API choose the currency (the system currency, or one that is enabled and has a rate); every account view carries its currency; a Currency column on the Accounts list and Update balances; every balance written, typed and read in the account's own currency; a Currency tile on the account page. Totals stay in the system currency, and a foreign account's worth in it is v0.5 household reporting.
- Tests: choosable currencies; creating accounts in 0-, 2- and 3-decimal currencies; refusals; each view carrying the currency; the screens in the person's format.
- Docs: mockups agreed first.

### 5a. Locale controls (#127)

- Scope: the "Number and date format" dropdown on the profile screen and on the admin's new-user form, the interpreted-amount preview on single and bulk balance entry, and the check that refuses a save made under a different locale than the saved one. It is stacked on #126 and ships with it.
- Tests: the preview on every row in the account's own currency; the refusal when the preference changed since the form opened; the dropdown saves on choice.
- Docs: the mockup is agreed.

### 5c. Fetching rates (#131)

- Scope: the rate fetch as the first job of the in-app scheduler (design in `docs/design/scheduler/`): `currency.rates.fetch`, the Time property `currency.rate.fetch_time` (18:00), insert-only fetching from Frankfurter in spans of a year, `python -m northstar.rates fetch`, a Rate source block on the currency page (when it runs, in which zone, how the last run went, no counts) and the source label Frankfurter. Built without the Fetch now button (#154) and without a "fetch rates from [date]" action, which the rates start date and the backfill of the days before the oldest stored rate replace.
- Tests: fetch never overwrites; a missed run is repaired by the next; provider timeout and invalid responses; a partial failure keeps what was committed.
- Docs: an Exchange rates section in `docs/operating.md` in place of a cron example, and the mockup of the currency page block, agreed first.

### 6. First-run setup page (#64)

- Scope: an unauthenticated page, available only while no admin exists and guarded by a one-time token printed in the container log, that creates the first admin and, in the same motion, sets initial system properties. It replaces `users create`, which is removed together with its operating guide text. The agreed design, including the token lifecycle, is [../first-run-setup.md](../first-run-setup.md).
- Tests: the page is gone once an admin exists; a wrong or reused token is refused; two simultaneous submissions create one admin; the admin and the properties are written in one transaction.
- Docs: a mockup first; the spec's "First admin" bullet and `docs/operating.md`.

### 7. Integration and release (#132)

- Scope: upgrade from v0.2 end to end, a restore of a pre-upgrade backup, a recovery rehearsal and the operator guide. The release candidate follows.
- Tests: the upgrade of an installation with accounts, and of one without; a fresh installation through the setup page.
