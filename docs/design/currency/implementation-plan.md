# Multi-currency and locale-aware formatting: implementation plan

A draft order of work for [design.md](design.md). Each step is one feature branch and one pull request into `main`, created as issues when the epic is scheduled. Tick a step when its pull request is merged.

Every step follows the working rules: the spec and `docs/decisions.md` change in the same pull request as the code, a mockup comes before any new screen, schema changes are tested on a copy of a database, and tests use synthetic data. Each new dependency states its reason.

## Order and dependencies

| Step | What | Depends on | Issue |
| --- | --- | --- | --- |
| 1 | Rename `amount_cents` to `amount_minor`, with the change log and undo compatibility | the epic is scheduled | to create |
| 2 | Currency catalog, account currency, and the USD migration | 1, System Properties | to create |
| 3 | Locale: user and system default, number parser, date formatter | 2 | to create |
| 4 | Importer and exporter on account currency and precision | 2 | to create |
| 5 | Rate table, manual rates, conversion and net worth | 2 | to create |
| 6 | Rate fetch command, Add Currency wizard and Fetch now | 5, Frankfurter checks | to create |
| 7 | First-run integration, recovery rehearsal and operator guide | 6, first-run setup page | to create |

The epic is [#56](https://github.com/declankenny/northstar/issues/56). System Properties and the first-run setup page are separate features and must ship before steps 2 and 7. System Alerts is independent. The order is a first guess: the first question for step 1 is whether to rename at all, once the undo design has been read.

## Steps

### 1. Rename the money column

- Scope: `amount_minor` replaces `amount_cents` across the schema, API and frontend, and old change log records still read correctly for undo.
- Tests: migration on a copy of a database; undo of an import made before the rename; the change log's integer-preserving JSON.
- Docs: spec, a decisions entry, `docs/schema.md`, the audited-field registry and the changelog.
- [ ] Merged

### 2. Catalog, account currency and migration

- Scope: the currencies table and catalog, `currency` on accounts set at creation and never edited, USD as system currency for existing installations, and the single-currency interface.
- Tests: precision and entry limits per currency; an account's currency cannot change; migration from v0.2; backup, restore and upgrade.
- Docs: a mockup of the currency choice first.
- [ ] Merged

### 3. Locale

- Scope: a saved locale per user with a system default, the shared server-side amount parser, and the chosen date formatter.
- Tests: parser vectors per supported locale including refused ambiguous input; a default affects new users only.
- Docs: a decisions entry for the date approach.
- [ ] Merged

### 4. Importer and exporter

- Scope: import trusts the account's currency, drops the Currency column mapping, uses the account's precision for number-style detection and for the review line; export writes the account's currency precision.
- Tests: no minor unit and three-decimal cases; round trip of an export.
- [ ] Merged

### 5. Rates and conversion

- Scope: the rate table, manual entry and correction by an admin, the conversion with per-account rounding, the zero-balance rule, and the missing-coverage behaviour.
- Tests: hand-calculated fixtures; halfway cases of both signs; no future rate used; corrections change valuation and not balances.
- Docs: a mockup of rate maintenance and of the missing-coverage state first.
- [ ] Merged

### 6. Fetching rates

- Scope: `python -m northstar.rates fetch`, the Add Currency wizard with its rerun, the Fetch now button and the staleness warning.
- Tests: fetch never overwrites; a missed run is repaired by the next; provider timeout and invalid responses; a partial failure keeps what was committed.
- Docs: the cron example in `docs/operating.md`, and a mockup of the wizard first.
- [ ] Merged

### 7. Integration and release

- Scope: the first-run page supplies system currency and locale, a recovery rehearsal, and the operator guide.
- Tests: upgrade from v0.2 end to end and a restore of a pre-upgrade backup.
- [ ] Merged
