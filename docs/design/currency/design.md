# Multi-currency and locale-aware formatting: design

Status: a draft dated November 3, 2026, updated November 6, 2026 with the design of exchange rates and conversion (#130). Nothing here is the spec or the decisions log. The open questions are listed at the end.

Each item below is labelled. **Decided** means Declan agreed it. **Proposed** means it is the recommendation and has not been challenged or confirmed. **Open** means it is unresolved: do not guess it.

## Outcome

A household whose accounts are all in one non-USD currency can use Northstar, and so can a household with accounts in several traditional currencies. Each account keeps its balances in its own currency. Net worth is calculated in one permanent system currency. Users type and read numbers and dates in their own locale. Locale never decides an account's currency or how a file must be read.

Northstar stays a balance-based tracker. Useful historical context matters more than the last digit of an old exchange rate.

## Currencies

**Catalog** (decided, built in #125). A `currencies` table holds the ISO 4217 code, name and minor-unit precision, supplied by Northstar and read-only to admins. Admins control whether a currency is enabled for new accounts and how its rates are collected. The entries are the 155 current ISO currencies with 0, 2 or 3 minor units, with ISO's names: funds, metals, units of account and special codes are left out, and the list is in [catalog.md](catalog.md). A catalog entry can exist without an automatic rate source.

**System currency** (decided). Chosen once, before the first account exists, and never changed. An existing installation is migrated to USD. A fresh installation chooses it on the first-run setup page. Another household currency means a fresh instance and an export and import, which must carry actual amounts and not relabel dollars.

**Single and multi-currency** (decided in #125). There is no switch and no stored flag. The catalog holds every ISO currency, so "single-currency" is derived: the interface hides currency choices and rate screens while no currency other than the system currency is enabled and no account uses one. A currency that has an account stays usable by it, because rows are never deleted. The server needs no separate enforcement: an account's currency must be usable, meaning enabled, and the system currency always is (saving it enables it). An admin enables any other currency on its page, and a foreign account needs at least one stored rate, which is what keeps a net worth from adding amounts in different currencies.

**Account currency** (decided). Set when the account is created and never edited. A wrong choice on an account with no balances is fixed by deleting and recreating it, since a deleted account frees its name. Creating an account needs an enabled currency and, for a foreign currency, at least one stored rate. This does not promise coverage for every older date.

**Availability and collection** (decided). Disabling a currency stops new accounts using it and keeps everything existing. Rate collection continues while any open, live account uses the currency, whether or not it is enabled. Closed accounts end in a zero balance and need no new rates.

## Rates

**Direction** (decided). One stored rate means 1 unit of the foreign currency = X units of the system currency. No separate reference currency. A system-currency row is unnecessary. Positive, finite decimals only. A provider adapter asks for the system currency as the quote, so no inversion is needed (to verify, see Provider).

**Identity** (decided). A rate is identified by currency and actual observation date, unique together. The exact shape of the table is open and gets locked down when it is designed.

**Selection** (decided). On reporting date D, each account uses its latest balance on or before D, then the latest stored rate on or before D. Balance carry-forward and rate carry-forward are separate. Today's spec rules for accounts with no balance by D are unchanged.

**Zero balances** (decided). A zero balance is converted like any other and needs a rate on its date. There is no special rule: a zero recorded before a currency's rates begin makes those dates unavailable, like any balance there, and the fix is the same, to add rates back to that date.

**Insert-only feeds and corrections** (decided). An automatic fetch inserts missing observations and never overwrites a stored rate for the same currency and date, whether that rate came from a provider or from an admin. An admin can correct a rate's value but cannot delete a rate or change its date. A correction can change historical totals and the screen says so. Provenance is a source column (provider or manual) and the change log records corrections. A separate "corrected" marker is not planned.

**History** (decided). Daily rates only. Each currency has a date its rates are wanted from, `currencies.rates_start`, chosen when it is first enabled and filled in from the system property `currency.rate.start.default`. It is an intent and is not enforced: the currency page compares it with the first stored rate and says which dates have none, and the coverage rule below comes from the rates that exist. Fetching rates from that date, and starting earlier, belong to #131. There is no monthly sampling, cutoff or per-currency override. TODO: confirm the volume and the provider's range limits before relying on a start date as far back as 2000.

## Valuation

**Exact money** (decided). Native amounts are integers in the currency's minor unit. Input with more decimals than the currency allows is refused, never rounded. No floating point anywhere.

**Conversion** (decided). For native integer N, native precision p, reporting precision q and exact decimal rate R, the result is `round_half_away_from_zero(N × R × 10^q / 10^p)`. Each account is converted and rounded on its own and the converted integers are summed. The asset-minus-liability sign convention is unchanged.

**Where it runs** (decided). The server computes every number. A view, `account_days`, holds one row for every day from the first balance to the newest balance or rate and every account that has a balance by then, with that account's latest balance and the latest rate of its currency on or before the day. It does only the lookup: the conversion is exact decimal arithmetic in Python (`networth.convert`), because SQLite has no decimal type and a 10^13 amount times a scaled rate overflows 64 bits, which SQLite turns into a float without saying so. The rate is stored as text and parsed as a decimal. The calendar stops at the newest balance or rate, because nothing changes after it, and a later date is answered with the last day. It cannot end at today: SQLite's `'now'` is UTC, and the application reads the date in one place, `clock.today()`.

**Limits** (proposed). Keep the current ceiling of about 10^13 in minor units, which stays inside JavaScript's safe integer range for any system currency.

**Missing coverage** (decided). A requested result is never a partial total and never silently omits an unconverted account. A date on which a balance has no rate is refused, naming the currencies. The uncovered dates are not always a prefix of the series: a EUR account that starts in March with EUR rates that start in May leaves March and April uncovered while January and February, before the account, are covered. So a series starts at the first date from which every later date can be converted, says where it starts and which currencies have no rate before then ("Starts May 1, 2026: EUR has no rate before this"), and offers admins the page of each currency. It is empty, with that explanation, when no date up to the end can be converted. Stale rates beyond the threshold (`currency.rate.stale_days`, default 14) warn on the currency page and still calculate. **Per-account views** (decided) are in the account's own currency, with no conversion and no coverage rule: only household totals convert.

**Calculated on demand** (decided). Converted balances are never stored as authoritative. Any later cache must be invalidated by balance changes, rate changes and account changes.

## Locale

**Per-user locale** (decided). Saved on the user, with a system default copied to new users when they are created. Changing the system default does not change existing users. The migration default for existing users is US English (proposed, since it preserves behaviour). Interface text stays English.

**What locale controls** (decided). How numbers and dates are shown and typed. Stored dates stay `YYYY-MM-DD` and stored amounts stay integers.

**Entry** (decided). One shared server-side parser turns typed text in the user's locale into minor units, used by every route that takes money. It reads with the user's locale and the account's currency, and never guesses another locale. The frontend repeats the rules so a change can show as it is typed, and the server stays authoritative. More decimals than the currency has is refused, never rounded.

**Dates** (decided). Shown by a small function that fills a locale's template from the `YYYY-MM-DD` text, with English month names. The frontend never creates a JavaScript `Date`. Entry stays on the native date input, which always yields an ISO value.

**Locales** (decided). The conventions are CLDR-derived data held in a read-only reference table, `ref_locales`, generated into a migration by a developer tool. The first six are `en-US`, `en-GB`, `de-DE`, `fr-FR`, `de-CH` and `ja-JP`.

**Symbols and codes** (decided). `$` is shown only for US dollars in `en-US`. Every other case shows the currency code, placed and spaced by the locale.

The detail is in [locale.md](../locale.md).

## CSV

**Export** (decided). The Northstar CSV stays canonical and independent of locale: `YYYY-MM-DD` and a plain decimal amount, now in the account's currency and precision. Export changes, including any informational Currency column, are outside #128. The existing four-column export stays as it is.

**Import** (decided). Import trusts that the file is in the account's currency. There is no Currency column mapping and no currency-symbol block, so the spec's current handling of a mapped Currency column is removed when this ships. The review says "all balances are treated as" followed by the chosen account's currency, as it says dollars today. Number-style detection must use the account's precision: `1.234` is only thousands for a currency with no minor unit, and is ambiguous for one with three decimals, so the person chooses. A file in another currency imported into the wrong account is a user error that Northstar does not try to detect.

## Provider and collection

**Provider** (proposed). [Frankfurter](https://frankfurter.dev/). Checked on November 3, 2026: a public API (`/v2/rates`, with `base`, `quotes`, `date`, `from` and `to`) with rates from central banks, free of keys and quotas but rate limited, history going back to 1948 for some currencies, per-currency coverage available at `/v2/currencies`, and open source. TODO: it does not state a time of day for publication, a maximum range size, or attribution terms; check these and the license page before building, and confirm `base` and `quotes` give the foreign-to-system direction directly.

**Daily run** (proposed). There is no scheduler in Northstar. A command, `python -m northstar.rates fetch`, run from the operator's cron like the nightly backup, fetches from the day after the newest stored rate for each collected currency up to today. A missed run fixes itself on the next one and no job table or stored last-run value is needed. The run time lives in the crontab and is documented in `docs/operating.md`. An admin Fetch now button runs the same code. Background writes are authored by the system user. A manual fetch is authored by the admin who pressed the button.

**Safety** (decided). Fetch outside write transactions and commit validated batches through the shared writer. A partial failure keeps committed rates and a rerun is safe. A provider failure never stops balance entry. Requests carry only currencies and dates.

## Currency page

A currency's page is where an admin works with it: the name on the Currencies list opens it. The Enabled switch saves at once in both directions, with no confirmation, because disabling deletes nothing and is undone by switching it on again, and helper text under it states the effect. The Rates start date is a field on the page. Rates are listed newest first, and one Add rate button opens a dialog that also serves Correct. The page allows rates only while the currency is enabled or has an account, and the system currency's page says it needs none. There is no Add Currency wizard: what it was to decide moves here, and #131 adds a rate source (manual or automatic) and "fetch rates from [date]" to this page.

## Migration and recovery

An existing installation gets the catalog and no change to any amount. Its system currency is USD, and USD is on every account, if it has at least one account; otherwise the system currency is unset and an admin sets it on the System Properties screen before an account can be created. Users get the default locale, `en-US`. The money columns keep the name `amount_cents` and now hold integers in the account currency's minor unit (decided, see the implementation plan). Test upgrade from v0.2, a backup before the upgrade, and restore after it. Update `docs/schema.md`, the audited-field registry and the operator guide with the code.

## Validation

The acceptance list from the interview carries over: existing USD results unchanged; system currency fixed once set; accounts always have a valid enabled currency; native amount entry enforces precision; direction, exact conversion, per-account rounding, halfway cases of both signs, zero, liabilities and differing precisions; no future rate used for an earlier date; fetch never overwrites; corrections change valuation and not the balance; date edits and deletes refused; stale rates warn; locale defaults affect new users only; locale does not change how a CSV is read; backup, restore and upgrade preserve currency settings, rates and balances. Hand-calculated fixtures on synthetic data and rendered checks, not tests that mirror the implementation.

## Open questions

Resolved in #130: the missing-coverage presentation, the rate table and the view, and zero balances. Still open:

- Whether a later feature adds an informational export Currency column (outside #128).
- Catalog policy for withdrawn and special codes, and for precision changes.
- Provider terms, publication time and range limits, and whether a rates start date as far back as 2000 fits them (#131).
- Whether the System Properties design adds a multi-currency toggle.
